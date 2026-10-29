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

from .. import catalogo, proposte, strumenti
from ..gateway import ChiamataStrumento, ErroreModello, Fine, Inizio, Testo, Uso, esegui as gateway
from ..models import Evento, MessaggioChat, Turno
from . import prompt

log = logging.getLogger("ai.motore")

MAX_PASSI = 12
MAX_SECONDI = 300
MAX_COSTO = Decimal("0.50")                     # dollari per turno
INTERVALLO_SALVATAGGIO = 0.25                   # secondi tra due salvataggi del testo in uscita
SENZA_BATTITO = timedelta(seconds=90)

MESSAGGI_ERRORE = {
    "AUTENTICAZIONE": "La chiave API del modello non è valida: avvisa l'amministratore.",
    "RATE_LIMIT": "Il servizio del modello è sovraccarico in questo momento: riprova tra poco.",
    "CONTESTO": "La conversazione è diventata troppo lunga: aprine una nuova.",
    "CONFIGURAZIONE": "L'assistente non è configurato: manca un modello o una chiave API.",
    "RICHIESTA": "Il provider ha rifiutato la richiesta: controlla URL, modello e chiave nelle impostazioni "
                 "dell'assistente.",
}


def messaggi_del_modello(conversazione):
    """La storia neutra per il gateway, dal log degli eventi."""
    return [ev.dati for ev in conversazione.eventi.order_by("pk")]


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
    ultimo = turno.conversazione.eventi.order_by("-pk").first()
    if ultimo is None or ultimo.tipo != Evento.ASSISTENTE:
        return
    aperte = [b for b in ultimo.dati.get("blocchi", []) if b["tipo"] == "strumento"]
    if aperte:
        Evento.objects.create(conversazione=turno.conversazione, turno=turno, tipo=Evento.STRUMENTO, dati={
            "ruolo": "strumento", "risultati": [{"id": b["id"], "contenuto": f"ESITO SCONOSCIUTO: {motivo}",
                                                 "errore": True} for b in aperte]})


def avvia(conversazione, testo, utente, azienda=None, compito="chat", sincrono=False, nota=""):
    """Registra la domanda e avvia il turno: in un thread, oppure nel processo stesso con `sincrono` (worker delle
    pianificate) o AI_TURNI_SINCRONI (test). `nota` va al modello nel <contesto>, non nella chat."""
    segna_interrotti(conversazione)
    in_corso = conversazione.turni.filter(stato=Turno.IN_CORSO).first()
    if in_corso is not None:
        return in_corso
    with transaction.atomic():
        turno = Turno.objects.create(conversazione=conversazione, utente=utente, azienda=azienda, compito=compito)
        esiti = proposte.da_comunicare(conversazione)
        Evento.objects.create(conversazione=conversazione, turno=turno, tipo=Evento.UTENTE, dati={
            "ruolo": "utente", "testo": prompt.con_contesto(testo, utente, azienda, conversazione.ambito, esiti,
                                                            nota)})
        MessaggioChat.objects.create(conversazione=conversazione, ruolo=MessaggioChat.UTENTE, testo=testo)
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
        self.turno = turno
        self.inizio = time.monotonic()
        self.ultimo_salvataggio = 0.0
        self.testo_turno = []                     # tutto il testo visibile del turno (tra un passo e l'altro)

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
        if time.monotonic() - self.inizio > MAX_SECONDI:
            return "il tempo massimo del turno"
        if self.turno.costo > MAX_COSTO:
            return "la spesa massima per una risposta"
        return None


def esegui(turno_id):
    turno = Turno.objects.select_related("conversazione", "utente", "azienda").get(pk=turno_id)
    conversazione, utente = turno.conversazione, turno.utente
    e = _Esecuzione(turno)
    try:
        from .. import limiti
        limiti.verifica(turno.azienda, utente)
        profilo = catalogo.profilo_per(turno.compito, turno.azienda, conversazione.ambito)
        catena = catalogo.catena(profilo, turno.azienda)
        ammessi = {s.nome: s for s in strumenti.disponibili(utente, conversazione.ambito)}
        contesto = strumenti.Contesto(utente=utente, azienda=turno.azienda, conversazione=conversazione, turno=turno)
        for passo in range(1, MAX_PASSI + 1):
            motivo = e.oltre_budget()
            if motivo:
                _chiudi(e, Turno.COMPLETATO, f"\n\n_Mi fermo qui: ho raggiunto {motivo}. Chiedimi di continuare._")
                return turno
            turno.passi = passo
            modello, chiamate, fine = None, [], None
            testo_passo = []
            try:
                for pezzo in gateway(catena, sistema=prompt.sistema(), messaggi=messaggi_del_modello(conversazione),
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
    turno.save()
    if turno.conversazione_id and testo:
        MessaggioChat.objects.create(conversazione=turno.conversazione, ruolo=MessaggioChat.ASSISTENTE, testo=testo,
                                     turno=turno)
        turno.conversazione.save(update_fields=["aggiornata"])
    if stato == Turno.COMPLETATO and turno.compito == "chat" and turno.conversazione_id:
        from . import titoli
        try:
            titoli.genera(turno.conversazione, turno.utente, turno.azienda)
        except Exception:                          # il titolo è un di più: non deve rompere il turno
            log.exception("titolo della conversazione %s", turno.conversazione_id)
