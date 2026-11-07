"""Il turno dell'assistente: dalla domanda alla risposta, passo dopo passo (modello → strumenti → modello...).

- Il contesto del modello si ricostruisce solo dal log degli eventi (sola aggiunta).
- Budget per turno: passi, secondi, costo. Al superamento si chiude in modo controllato, mai con un'eccezione.
- Ogni chiamata a uno strumento ha un risultato: se il turno si ferma a metà, se ne scrive uno sintetico.
- Il testo in uscita si salva sul turno a intervalli brevi: lo streaming lo segue dal database.
"""
import logging
import threading
import time
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import close_old_connections, connection, transaction
from django.utils import timezone

from .. import catalogo, proposte, protezione, strumenti
from ..gateway import ChiamataStrumento, ErroreModello, Fine, Inizio, Testo, Uso, esegui as gateway
from core import allegati as core_allegati

from .. import allegati_chat, contesto_utente
from ..models import Artifact, Evento, MessaggioChat, Proposta, Turno
from . import prompt

log = logging.getLogger("ai.motore")

MAX_PASSI = 12
MAX_SECONDI = 300
MAX_COSTO = Decimal("0.50")                     # dollari per turno
MAX_TOKEN_DESCRIZIONE = 350                     # descrizione di un'immagine fatta in locale (su CPU circa 40 secondi)
INTERVALLO_SALVATAGGIO = 0.25                   # secondi tra due salvataggi del testo in uscita
SENZA_BATTITO = timedelta(seconds=90)

MESSAGGI_ERRORE = {
    "AUTENTICAZIONE": "La chiave API del modello non è valida: avvisa l'amministratore.",
    "RATE_LIMIT": "Il servizio del modello è sovraccarico in questo momento: riprova tra poco.",
    "CONTESTO": "La conversazione è diventata troppo lunga: aprine una nuova.",
    "CONFIGURAZIONE": "L'assistente non è configurato: manca un modello o una chiave API.",
    "RICHIESTA": "Il provider ha rifiutato la richiesta: controlla URL, modello e chiave nelle impostazioni "
                 "dell'assistente.",
    "PII": "Il servizio che protegge i dati personali non risponde: per sicurezza non ho inviato nulla al modello. "
           "Riprova tra poco o avvisa l'amministratore.",
}


def messaggi_del_modello(conversazione):
    """La storia neutra per il gateway, dal log degli eventi (dall'ultimo riassunto, se la conversazione è lunga)."""
    from .compattazione import messaggi
    return messaggi(conversazione)


def segna_interrotti(conversazione=None):
    """I turni senza segno di vita da troppo: interrotti (processo riavviato), con la storia rimessa in ordine."""
    limite = timezone.now() - SENZA_BATTITO
    qs = Turno.objects.filter(stato=Turno.IN_CORSO, battito__lt=limite)
    if conversazione is not None:
        qs = qs.filter(conversazione=conversazione)
    for t in qs:
        _chiudi_chiamate_aperte(t, "Il turno si è interrotto prima del risultato: verifica lo stato prima di riprovare.")
        t.stato, t.finito, t.errore = Turno.INTERROTTO, timezone.now(), "nessun segno di vita"
        t.save(update_fields=["stato", "finito", "errore"])


def _chiudi_chiamate_aperte(turno, motivo):
    """Se l'ultimo evento dell'assistente ha chiamate senza risultato, si aggiunge un risultato sintetico."""
    if turno.conversazione_id is None:
        return
    ultimo = turno.conversazione.eventi.exclude(tipo=Evento.RIASSUNTO).order_by("-pk").first()
    if ultimo is None or ultimo.tipo != Evento.ASSISTENTE:
        return
    aperte = [b for b in ultimo.dati.get("blocchi", []) if b["tipo"] == "strumento"]
    if aperte:
        Evento.objects.create(conversazione=turno.conversazione, turno=turno, tipo=Evento.STRUMENTO, dati={
            "ruolo": "strumento", "risultati": [{"id": b["id"], "contenuto": f"ESITO SCONOSCIUTO: {motivo}",
                                                 "errore": True} for b in aperte]})


def in_corso_di(conversazione):
    """La risposta che l'utente sta aspettando. Il turno del titolo non conta: gira dopo la risposta, e se bloccasse la
    chat il messaggio scritto in quel momento andrebbe perso."""
    return conversazione.turni.filter(stato=Turno.IN_CORSO).exclude(compito="titoli").first()


class NonSiPuoRipartire(Exception):
    """Il messaggio per l'utente: perché non si può rigenerare o modificare da quel punto."""


def riparti(conversazione, messaggio, testo, utente, azienda=None):
    """Rigenera o modifica: il messaggio resta con i suoi allegati, ciò che viene dopo sparisce, e la cronologia del
    modello (ricostruita dagli eventi) torna a quel punto, riassunti compresi. I turni restano: i costi sono stati
    pagati. Una proposta già eseguita ferma tutto: cancellare la risposta non annullerebbe la modifica ai dati."""
    segna_interrotti(conversazione)
    with transaction.atomic():
        if in_corso_di(conversazione) is not None:
            raise NonSiPuoRipartire("C'è già una risposta in corso: fermala o aspetta che finisca.")
        posizione = conversazione.messaggi.filter(ruolo=MessaggioChat.UTENTE, pk__lt=messaggio.pk).count()
        domande = list(conversazione.eventi.filter(tipo=Evento.UTENTE).order_by("pk").values_list("pk", flat=True))
        if messaggio.ruolo != MessaggioChat.UTENTE or posizione >= len(domande):
            raise NonSiPuoRipartire("Da questo messaggio non si può ripartire.")
        da_togliere = conversazione.eventi.filter(pk__gte=domande[posizione])
        domanda = Evento.objects.filter(pk=domande[posizione]).select_related("turno").first()
        originale, conferma = domanda.turno, domanda.dati.get("immagini_confermate")
        compito, con_web = getattr(originale, "compito", "chat"), getattr(originale, "web", True)
        turni_tolti = set(da_togliere.exclude(turno=None).values_list("turno_id", flat=True))
        decise = Proposta.objects.filter(turno_id__in=turni_tolti)
        if decise.filter(stato=Proposta.ESEGUITA).exists():
            raise NonSiPuoRipartire("In questa parte della chat una modifica ai dati è già stata eseguita: ripartire non "
                                    "la annullerebbe. Scrivi un nuovo messaggio.")
        decise.filter(stato=Proposta.IN_ATTESA).update(stato=Proposta.ANNULLATA, esito="Chat ripartita da un messaggio precedente.")
        decise.update(comunicata=True)
        Artifact.objects.filter(turno_id__in=turni_tolti, salvato=False).delete()
        conversazione.messaggi.filter(pk__gt=messaggio.pk).delete()
        da_togliere.delete()
        messaggio.testo = testo
        messaggio.save(update_fields=["testo"])
    if compito == "ricerca":
        from .. import ricerca
        return avvia(conversazione, testo, utente, azienda, messaggio=messaggio, compito=compito, nota=ricerca.ISTRUZIONI,
                     immagini_confermate=conferma)
    return avvia(conversazione, testo, utente, azienda, messaggio=messaggio, web=con_web, immagini_confermate=conferma)


def avvia(conversazione, testo, utente, azienda=None, compito="chat", sincrono=False, nota="", file=(), messaggio=None, web=True,
          immagini_confermate=None):
    """Registra la domanda e avvia il turno: in un thread, oppure nel processo stesso con `sincrono` (worker delle
    pianificate) o AI_TURNI_SINCRONI (test). `nota` va al modello nel <contesto>, non nella chat. `file`: gli allegati
    del messaggio, già controllati. `messaggio`: quello esistente, quando si riparte da lì."""
    segna_interrotti(conversazione)
    in_corso = in_corso_di(conversazione)
    if in_corso is not None:
        return in_corso
    with transaction.atomic():
        turno = Turno.objects.create(conversazione=conversazione, utente=utente, azienda=azienda, compito=compito, web=web)
        esiti = proposte.da_comunicare(conversazione)
        if messaggio is None:
            messaggio = MessaggioChat.objects.create(conversazione=conversazione, ruolo=MessaggioChat.UTENTE, testo=testo)
        for f in file:
            core_allegati.salva(messaggio, f, utente)
        nota = "\n".join(n for n in (contesto_utente.nota_memoria_per(conversazione, utente, azienda), contesto_utente.nota_progetto(conversazione),
                                     nota, allegati_chat.nota(messaggio)) if n)
        immagini = [a.pk for a in allegati_chat.immagini_di(messaggio)]
        # chi ha confermato l'invio delle immagini verso il cloud, e quando: resta nella storia della chat
        conferma = immagini_confermate if immagini and immagini_confermate else None
        if conferma is True:
            conferma = {"utente": utente.username, "quando": timezone.now().isoformat()}
        Evento.objects.create(conversazione=conversazione, turno=turno, tipo=Evento.UTENTE, dati={
            "ruolo": "utente", "testo": prompt.con_contesto(testo, utente, azienda, conversazione.ambito, esiti, nota),
            **({"immagini": immagini} if immagini else {}), **({"immagini_confermate": conferma} if conferma else {})})
        if conferma:
            log.info("immagini verso il cloud confermate da %s (chat %s, allegati %s)", utente.username, conversazione.pk, immagini)
    if sincrono or getattr(settings, "AI_TURNI_SINCRONI", False):
        esegui(turno.pk)
    else:
        threading.Thread(target=_in_thread, args=(turno.pk,), daemon=True, name=f"ai-turno-{turno.pk}").start()
    return turno


def _in_thread(turno_id):
    close_old_connections()
    try:
        esegui(turno_id)
    finally:
        connection.close()


def ferma(turno):
    Turno.objects.filter(pk=turno.pk, stato=Turno.IN_CORSO).update(richiesta_stop=True)


class _Fermati(Exception):
    pass


class _Esecuzione:
    def __init__(self, turno):
        from .. import ricerca
        self.turno = turno
        self.inizio = time.monotonic()
        lunga = turno.compito == ricerca.COMPITO          # la ricerca approfondita ha un budget più ampio
        self.passi, self.secondi, self.costo = (ricerca.PASSI, ricerca.SECONDI, ricerca.COSTO) if lunga else (MAX_PASSI, MAX_SECONDI, MAX_COSTO)
        self.ultimo_salvataggio = 0.0
        self.testo_turno = []                     # tutto il testo visibile del turno (tra un passo e l'altro)
        self.protezione = None

    def salva_testo(self, forza=False):
        adesso = time.monotonic()
        if forza or adesso - self.ultimo_salvataggio >= INTERVALLO_SALVATAGGIO:
            self.ultimo_salvataggio = adesso
            self.turno.testo, self.turno.battito = "".join(self.testo_turno), timezone.now()
            self.turno.save(update_fields=["testo", "battito"])
            if Turno.objects.filter(pk=self.turno.pk, richiesta_stop=True).exists():
                raise _Fermati

    def avanzamento(self, voce):
        self.turno.avanzamento = [*self.turno.avanzamento, voce]
        self.turno.battito = timezone.now()
        self.turno.save(update_fields=["avanzamento", "battito"])

    def aggiungi_uso(self, modello, uso):
        totale = dict(self.turno.uso)
        for k, v in uso.come_dict().items():
            totale[k] = totale.get(k, 0) + v
        self.turno.uso = totale
        self.turno.costo += modello.costo(uso.come_dict())

    def oltre_budget(self):
        if time.monotonic() - self.inizio > self.secondi:
            return "il tempo massimo del turno"
        if self.turno.costo > self.costo:
            return "la spesa massima per una risposta"
        return None


def esegui(turno_id):
    turno = Turno.objects.select_related("conversazione", "utente", "azienda").get(pk=turno_id)
    conversazione, utente = turno.conversazione, turno.utente
    e = _Esecuzione(turno)
    try:
        from .. import limiti
        limiti.verifica(turno.azienda, utente)
        from .. import assistenti
        assistente = assistenti.risolvi(conversazione, utente)
        if assistente is not None and assistente.profilo_id and assistente.profilo.attivo:
            profilo, anelli = assistente.profilo, catalogo.catena(assistente.profilo, turno.azienda)
        else:
            profilo = catalogo.profilo_per(turno.compito, turno.azienda, conversazione.ambito)
            anelli = (catalogo.automatico(profilo, turno.azienda) if profilo.compito == "chat"
                      else catalogo.catena(profilo, turno.azienda))
        catena = catalogo.con_scelta(anelli, conversazione.modello, turno.azienda)
        from ..strumenti import web
        ammessi = {s.nome: s for s in assistenti.filtra_strumenti(
            web.filtra(strumenti.disponibili(utente, conversazione.ambito, turno.azienda), turno.azienda, turno.web), assistente, esperto=turno.compito == "esperto")}
        if turno.compito == "aiuto":                      # «Scrivi con Ada»: solo letture del gestionale
            from .. import aiuto_testi
            ammessi = aiuto_testi.filtra_strumenti(ammessi)
        copia, con_immagine, nell_ultimo = allegati_chat.con_immagini(messaggi_del_modello(conversazione))
        senza_immagini = False
        if con_immagine:
            confermate = _immagini_confermate(conversazione)
            adatti = [a for a in catena if allegati_chat.modello_ammesso_per_immagini(a[0], turno.azienda, confermate)]
            locali = allegati_chat.visione_locale(turno.azienda)
            if not adatti and nell_ultimo and locali:
                # l'immagine non può uscire: la descrive un modello sui nostri server e la descrizione (testo, mascherato
                # come il resto) va al modello della chat, che tiene strumenti e dati del gestionale
                _descrivi_in_locale(e, conversazione, copia, locali)
                copia, con_immagine, nell_ultimo = allegati_chat.con_immagini(messaggi_del_modello(conversazione))
        if con_immagine:
            if adatti:
                catena = adatti
            elif nell_ultimo:
                raise catalogo.NessunModello("Nessun modello abilitato può leggere questa immagine.")
            else:                                      # un'immagine di prima: la chat continua senza vederla
                senza_immagini = True
        sistema = prompt.sistema(assistente)
        contesto = strumenti.Contesto(utente=utente, azienda=turno.azienda, conversazione=conversazione, turno=turno)
        e.protezione = protezione.Protezione(conversazione)
        from . import compattazione
        if compattazione.se_serve(turno):
            e.avanzamento({"strumento": "riassunto", "stato": "fatto", "passo": 0})
        for passo in range(1, e.passi + 1):
            motivo = e.oltre_budget()
            if motivo:
                _chiudi(e, Turno.COMPLETATO, f"\n\n_Mi fermo qui: ho raggiunto {motivo}. Chiedimi di continuare._")
                return turno
            turno.passi = passo
            modello, chiamate, fine = None, [], None
            testo_passo = []
            try:
                for pezzo in gateway(catena, protezione=e.protezione, sistema=sistema,
                                     messaggi=(messaggi_del_modello(conversazione) if senza_immagini
                                               else allegati_chat.con_immagini(messaggi_del_modello(conversazione))[0]),
                                     strumenti=[s.definizione() for s in ammessi.values()],
                                     max_token=profilo.max_token, effort=profilo.effort):
                    if isinstance(pezzo, Inizio):
                        modello = pezzo.modello
                        turno.modello = modello
                    elif isinstance(pezzo, Testo):
                        testo_passo.append(pezzo.testo)
                        e.testo_turno.append(pezzo.testo)
                        e.salva_testo()
                    elif isinstance(pezzo, ChiamataStrumento):
                        chiamate.append(pezzo)
                    elif isinstance(pezzo, Uso):
                        e.aggiungi_uso(modello, pezzo)
                    elif isinstance(pezzo, Fine):
                        fine = pezzo
            except _Fermati:
                _registra_parziale(turno, testo_passo)
                _chiudi(e, Turno.FERMATO, "\n\n_Risposta interrotta._")
                return turno
            dati = {"ruolo": "assistente", "blocchi": fine.blocchi if fine else [{"tipo": "testo",
                                                                                 "testo": "".join(testo_passo)}]}
            if fine and fine.nativo:
                dati["nativo"] = fine.nativo
            if e.protezione.ultima_mascherata:
                dati["mascherato"] = True                 # i blocchi nativi contengono i segnaposto
            Evento.objects.create(conversazione=conversazione, turno=turno, tipo=Evento.ASSISTENTE, dati=dati)
            if not chiamate:
                if fine and fine.motivo == "limite":
                    e.testo_turno.append("\n\n_La risposta ha raggiunto la lunghezza massima._")
                elif fine and fine.motivo == "rifiuto":
                    e.testo_turno.append("\n\n_Il modello non ha voluto rispondere a questa richiesta._")
                _chiudi(e, Turno.COMPLETATO)
                return turno
            if e.testo_turno and not "".join(e.testo_turno).endswith("\n"):
                e.testo_turno.append("\n\n")
            for c in chiamate:
                e.avanzamento({"strumento": c.nome, "stato": "in corso", "passo": passo})
            risultati = strumenti.esegui(chiamate, contesto, ammessi)
            Evento.objects.create(conversazione=conversazione, turno=turno, tipo=Evento.STRUMENTO,
                                  dati={"ruolo": "strumento", "risultati": risultati})
            e.avanzamento({"passo": passo, "fatti": [{"strumento": c.nome, "errore": r["errore"]}
                                                     for c, r in zip(chiamate, risultati)]})
            e.salva_testo(forza=True)
        _chiudi(e, Turno.COMPLETATO, "\n\n_Mi fermo qui: troppi passi per una sola risposta. Chiedimi di continuare._")
    except _Fermati:
        _chiudi(e, Turno.FERMATO, "\n\n_Risposta interrotta._")
    except (ErroreModello, catalogo.NessunModello) as errore:
        codice = getattr(errore, "codice", "CONFIGURAZIONE")
        log.warning("turno %s: %s", turno.pk, errore)
        _chiudi_chiamate_aperte(turno, "il turno si è fermato per un errore")
        messaggio = MESSAGGI_ERRORE.get(codice, "Il modello non ha risposto: riprova tra poco.")
        if isinstance(errore, catalogo.NessunModello) or codice == "LIMITE":
            messaggio = str(errore)
        if isinstance(errore, catalogo.NessunModello) or codice in ("AUTENTICAZIONE", "CONFIGURAZIONE", "RICHIESTA"):
            messaggio += (" Un amministratore la sistema da **Impostazioni dell'assistente → Provider e chiavi** "
                          "(/ai/provider/).")
        _chiudi(e, Turno.ERRORE, f"\n\n⚠️ **{messaggio}**", errore=str(errore))
    except Exception as errore:                    # mai lasciare un turno appeso
        log.exception("turno %s", turno.pk)
        _chiudi_chiamate_aperte(turno, "il turno si è fermato per un errore interno")
        _chiudi(e, Turno.ERRORE, "\n\n_Si è verificato un errore interno._", errore=repr(errore))
    return turno


DESCRIVI = ("Descrivi in italiano, in modo fedele e concreto, l'immagine allegata: che cosa mostra e i testi leggibili, trascritti "
            "esattamente. Non inventare ciò che non si vede. Domanda dell'utente sull'immagine: {domanda}")


def _descrivi_in_locale(e, conversazione, messaggi, locali):
    """Fa descrivere le immagini dell'ultimo messaggio a un modello locale e mette la descrizione nella domanda, al posto
    dei file: il modello della chat (anche cloud) riceve solo il testo."""
    indice = max(i for i, m in enumerate(messaggi) if m.get("immagini_dati"))
    domanda = messaggi[indice]["testo"].rsplit("</contesto>", 1)[-1].strip()[:1000]
    e.avanzamento({"strumento": "leggi_immagine", "stato": "in corso", "passo": 0})
    pezzi, modello = [], None
    for pezzo in gateway(locali, protezione=None, sistema="Descrivi le immagini in modo fedele, senza inventare.",
                         messaggi=[{"ruolo": "utente", "testo": DESCRIVI.format(domanda=domanda), "immagini_dati": messaggi[indice]["immagini_dati"]}],
                         strumenti=[], max_token=MAX_TOKEN_DESCRIZIONE, effort="none"):
        if isinstance(pezzo, Inizio):
            modello = pezzo.modello
        elif isinstance(pezzo, Testo):
            pezzi.append(pezzo.testo)
        elif isinstance(pezzo, Uso):
            e.aggiungi_uso(modello, pezzo)
    descrizione = "".join(pezzi).strip() or "(il modello locale non ha saputo descriverla)"
    ultimo = conversazione.eventi.filter(tipo=Evento.UTENTE, dati__has_key="immagini").order_by("-pk").first()
    dati = dict(ultimo.dati)
    dati["immagini_descritte"] = dati.pop("immagini")
    dati["testo"] += (f"\n\n<immagini_allegate descritte_da=\"{getattr(modello, 'etichetta', 'modello locale')}, sui nostri server\">\n"
                      f"Le immagini non ti vengono inviate: questa è la loro descrizione, fatta da un modello piccolo che può sbagliare "
                      f"i dettagli.\n{descrizione}\n</immagini_allegate>")
    ultimo.dati = dati
    ultimo.save(update_fields=["dati"])
    e.avanzamento({"passo": 0, "fatti": [{"strumento": "leggi_immagine", "errore": False}]})


def _immagini_confermate(conversazione):
    """Se l'utente ha confermato l'invio verso il cloud dell'ultima immagine (quella che va al modello)."""
    ultimo = conversazione.eventi.filter(tipo=Evento.UTENTE, dati__has_key="immagini").order_by("-pk").first()
    return bool(ultimo and ultimo.dati.get("immagini_confermate"))


def _registra_parziale(turno, testo_passo):
    if turno.conversazione_id:
        Evento.objects.create(conversazione=turno.conversazione, turno=turno, tipo=Evento.ASSISTENTE, dati={
            "ruolo": "assistente", "blocchi": [{"tipo": "testo", "testo": "".join(testo_passo) or "…"}]})


def _chiudi(e, stato, coda="", errore=""):
    turno = e.turno
    if coda:
        e.testo_turno.append(coda)
    testo = "".join(e.testo_turno).strip()
    turno.testo, turno.stato, turno.finito, turno.errore = testo, stato, timezone.now(), errore[:2000]
    turno.battito = turno.finito
    if stato == Turno.COMPLETATO and turno.compito == "ricerca" and turno.conversazione_id:
        from .. import ricerca
        try:
            ricerca.concludi(turno)
        except Exception:                          # le fonti sono un di più: non devono rompere il turno
            log.exception("fonti della ricerca %s", turno.pk)
    if stato == Turno.COMPLETATO and turno.conversazione_id:
        from .. import provenienza
        try:
            turno.provenienza = provenienza.calcola(turno, testo, len(e.protezione.protetti) if e.protezione else 0)
        except Exception:                          # la provenienza è un di più: non deve rompere il turno
            log.exception("provenienza del turno %s", turno.pk)
    with transaction.atomic():                         # insieme: chi vede il turno concluso trova già il messaggio
        turno.save()
        if turno.conversazione_id and testo:
            MessaggioChat.objects.create(conversazione=turno.conversazione, ruolo=MessaggioChat.ASSISTENTE, testo=testo,
                                         turno=turno)
            turno.conversazione.save(update_fields=["aggiornata"])
    if stato == Turno.COMPLETATO and turno.compito in ("chat", "ricerca") and turno.conversazione_id \
            and not turno.conversazione.nascosta:
        from . import titoli
        try:
            titoli.genera(turno.conversazione, turno.utente, turno.azienda)
        except Exception:                          # il titolo è un di più: non deve rompere il turno
            log.exception("titolo della conversazione %s", turno.conversazione_id)
