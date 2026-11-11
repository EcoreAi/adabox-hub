"""Tenere allineati persone, aziende e opportunità con il sistema esterno (HubSpot, Salesforce, Zoho: il motore è uno,
ogni sistema ha il suo connettore in sistemi/). Per ogni collegamento comanda uno solo dei due:

- comanda l'esterno: a intervalli si leggono i record cambiati e si copiano qui (prima le aziende, poi le persone che
  ci lavorano, poi le opportunità con il loro cliente). Ciò che arriva non riparte verso fuori.
- comanda adabox: contatti e opportunità salvati qui si scrivono di là, uno per uno, in background, con le
  associazioni (la persona alla sua azienda, l'opportunità al cliente).

Mai cancellazioni, in nessun verso, e un campo vuoto non cancella un valore: perdere un dato costa più di tenerne uno
vecchio. Se una chiave (email, nome dell'azienda) porta a più record non si sceglie a caso: si salta e si segnala."""
import datetime
import logging

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core import lavori, sequenze

from . import eventi, riferimenti, sistemi
from .models import CollegamentoEsterno
from .sistemi.base import AZIENDE, OPPORTUNITA, PERSONE, ErroreConnettore, ErroreTemporaneo, dominio

CONTATTI = PERSONE

log = logging.getLogger("connettori.sincronia")
MARGINE = datetime.timedelta(minutes=5)       # i record cambiati compaiono nella ricerca con un po' di ritardo
MASSIMO_PAGINE = 50                           # il resto al prossimo giro: il cursore è già avanzato
LUNGHEZZE = {"nome": 200, "ruolo": 100, "indirizzo": 200, "citta": 100, "cap": 10, "telefono": 40, "cellulare": 40, "sito": 200,
             "email": 254, "nazione": 2}
NOMI = {CONTATTI: ("persone", "create", "aggiornate"), AZIENDE: ("aziende", "create", "aggiornate"),
        OPPORTUNITA: ("opportunità", "create", "aggiornate")}
# campi che cambiano da soli (calcoli periodici): un salvataggio che tocca solo questi non riparte verso l'esterno
SOLO_CALCOLATI = {"classe_abc", "fatturato_12_mesi", "vies_valido", "vies_il", "punteggio", "punteggio_fattori", "punteggio_il"}


def client(collegamento):
    return sistemi.client(collegamento)


def crm_attivo():
    return apps.is_installed("crm")


def _esito(collegamento, testo, errore=False):
    CollegamentoEsterno.objects.filter(pk=collegamento.pk).update(ultimo_giro=timezone.now(), ultimo_esito=testo[:500], in_errore=errore)


def chiave_azienda(id_est):
    """Persone e aziende sono entrambe Contatti: gli id delle aziende si distinguono con un prefisso, perché un sistema
    (HubSpot) può dare lo stesso numero a una persona e a un'azienda."""
    return f"{AZIENDE}:{id_est}"


def _taglia(dati):
    return {k: v[:LUNGHEZZE[k]] if k in LUNGHEZZE else v for k, v in dati.items()}


def _aggiorna(obj, dati):
    cambiati = [k for k, v in dati.items() if getattr(obj, k) != v]
    for k in cambiati:
        setattr(obj, k, dati[k])
    if cambiati:
        obj.save(update_fields=cambiati)
    return bool(cambiati)


# --- dall'esterno ad adabox ----------------------------------------------------------------------------------------

def _azienda_collegata(collegamento, ids):
    from contatti.models import Contatto
    for id_est in ids or []:
        trovata = riferimenti.trova(Contatto, collegamento.azienda, collegamento.sistema, chiave_azienda(id_est))
        if trovata is not None:
            return trovata
    return None


def _applica(collegamento, sistema, record, aziende_associate=None):
    """Una persona esterna su un contatto: 'creato', 'aggiornato', 'uguale' o 'dubbio'."""
    from contatti.models import Contatto
    dati = _taglia(sistema.in_adabox(PERSONE, record))
    if not dati.get("nome"):
        return "dubbio"
    azienda = collegamento.azienda
    contatto = riferimenti.trova(Contatto, azienda, collegamento.sistema, record["id"])
    if contatto is None and dati.get("email"):
        stessi = list(Contatto.objects.filter(azienda=azienda, email__iexact=dati["email"])[:2])
        if len(stessi) > 1:
            return "dubbio"
        if stessi:
            contatto = stessi[0]
    if collegamento.aziende and (societa := _azienda_collegata(collegamento, aziende_associate)) is not None:
        dati["societa"] = societa
    esito = "uguale"
    if contatto is None:
        contatto = Contatto.objects.create(azienda=azienda, codice=sequenze.prossimo("contatti.contatto", azienda), tipo=Contatto.PERSONA,
                                           cliente=True, **dati)
        esito = "creato"
    elif _aggiorna(contatto, dati):
        esito = "aggiornato"
    riferimenti.collega(contatto, collegamento.sistema, record["id"])
    return esito


def _applica_azienda(collegamento, sistema, record):
    """Un'azienda esterna su un contatto di tipo azienda: si riconosce dal collegamento, poi dal nome."""
    from contatti.models import Contatto
    dati = _taglia(sistema.in_adabox(AZIENDE, record))
    if not dati.get("nome"):
        return "dubbio"
    azienda = collegamento.azienda
    chiave = chiave_azienda(record["id"])
    contatto = riferimenti.trova(Contatto, azienda, collegamento.sistema, chiave)
    if contatto is None:
        stessi = list(Contatto.objects.filter(azienda=azienda, tipo=Contatto.AZIENDA, nome__iexact=dati["nome"])[:2])
        if len(stessi) > 1:
            return "dubbio"
        contatto = stessi[0] if stessi else None
        if contatto is not None and riferimenti.id_esterno(contatto, collegamento.sistema):
            return "dubbio"                               # già collegata a un'altra azienda esterna con lo stesso nome
    esito = "uguale"
    if contatto is None:
        contatto = Contatto.objects.create(azienda=azienda, codice=sequenze.prossimo("contatti.contatto", azienda), tipo=Contatto.AZIENDA,
                                           cliente=True, **dati)
        esito = "creato"
    elif _aggiorna(contatto, dati):
        esito = "aggiornato"
    riferimenti.collega(contatto, collegamento.sistema, chiave)
    return esito


def fase_in_adabox(fase_esterna):
    """(fase del CRM, stato) per una fase esterna: chiusa vinta è la fase di vittoria, chiusa persa è persa (la fase
    resta quella che era); aperta va alla fase con lo stesso nome o, se non c'è, a quella con la probabilità più
    vicina. Le fasi del CRM non si creano da qui: valgono per tutte le aziende dell'istanza."""
    from crm.models import FaseCrm, Opportunita
    fasi = list(FaseCrm.objects.order_by("ordine", "pk"))
    if fase_esterna["chiusa"]:
        if fase_esterna.get("vinta", fase_esterna["probabilita"] >= 1):
            return next((f for f in fasi if f.vinta), None), Opportunita.VINTA
        return None, Opportunita.PERSA
    aperte = [f for f in fasi if not f.vinta]
    if not aperte:
        return None, Opportunita.APERTA
    uguale = next((f for f in aperte if f.nome.strip().lower() == fase_esterna["label"].strip().lower()), None)
    obiettivo = fase_esterna["probabilita"] * 100
    return uguale or min(aperte, key=lambda f: (abs(f.probabilita - obiettivo), f.ordine)), Opportunita.APERTA


def fase_fuori(opportunita, fasi):
    """La fase esterna per un'opportunità di adabox (None se il sistema non ha fasi)."""
    from crm.models import Opportunita
    if opportunita.stato == Opportunita.VINTA:
        return next((f for f in fasi if f["chiusa"] and f["vinta"]), None)
    if opportunita.stato == Opportunita.PERSA:
        return next((f for f in fasi if f["chiusa"] and not f["vinta"]), None)
    aperte = [f for f in fasi if not f["chiusa"]]
    if not aperte:
        return None
    nome = opportunita.fase.nome.strip().lower() if opportunita.fase_id else ""
    uguale = next((f for f in aperte if f["label"].strip().lower() == nome), None)
    obiettivo = opportunita.fase.probabilita if opportunita.fase_id else opportunita.probabilita
    return uguale or min(aperte, key=lambda f: (abs(f["probabilita"] * 100 - obiettivo), f["ordine"]))


def _applica_opportunita(collegamento, sistema, record, fasi, aziende_associate=None, persone_associate=None):
    """Un'opportunità esterna: titolo, valore, chiusura prevista, fase e stato, cliente (l'azienda, altrimenti la
    persona associata)."""
    from contatti.models import Contatto
    from crm.models import Opportunita
    dati = sistema.in_adabox(OPPORTUNITA, record, fasi)
    fase_esterna = dati.pop("fase_esterna", None)
    azienda = collegamento.azienda
    opportunita = riferimenti.trova(Opportunita, azienda, collegamento.sistema, record["id"])
    if opportunita is None and not dati.get("titolo"):
        return "dubbio"
    cliente = _azienda_collegata(collegamento, aziende_associate) if collegamento.aziende else None
    if cliente is None:
        cliente = next((c for c in (riferimenti.trova(Contatto, azienda, collegamento.sistema, i) for i in persone_associate or []) if c), None)
    if cliente is not None:
        dati["contatto"] = cliente
    if fase_esterna is not None:
        fase, stato = fase_in_adabox(fase_esterna)
        if fase is not None:
            dati["fase"] = fase
        if stato == Opportunita.PERSA:
            dati["stato"] = Opportunita.PERSA
            if opportunita is not None and opportunita.fase_id and opportunita.fase.vinta:      # vinta e poi persa
                from crm.models import FaseCrm
                dati["fase"] = FaseCrm.objects.filter(vinta=False).order_by("-ordine", "-pk").first() or opportunita.fase
            if opportunita is None or opportunita.stato != Opportunita.PERSA:
                dati["chiusa_il"] = dati.get("chiusura_prevista") or timezone.localdate()
        elif opportunita is not None and opportunita.stato == Opportunita.PERSA:
            dati["stato"], dati["chiusa_il"] = Opportunita.APERTA, None             # riaperta di là
    if opportunita is None:
        from crm.models import FaseCrm
        if "fase" not in dati and not FaseCrm.objects.exists():
            return "dubbio"                                   # il CRM non ha ancora fasi
        opportunita = Opportunita(azienda=azienda, origine=collegamento.get_sistema_display())
        for k, v in dati.items():
            setattr(opportunita, k, v)
        opportunita.save()
        esito = "creato"
    else:
        esito = "aggiornato" if _aggiorna(opportunita, dati) else "uguale"
    riferimenti.collega(opportunita, collegamento.sistema, record["id"])
    return esito


def _cursore(collegamento, tipo):
    if tipo == CONTATTI:
        return collegamento.cursore
    valore = (collegamento.cursori or {}).get(tipo)
    return parse_datetime(valore) if valore else None


def _salva_cursore(collegamento, tipo, istante):
    if tipo == CONTATTI:
        CollegamentoEsterno.objects.filter(pk=collegamento.pk).update(cursore=istante)
        collegamento.cursore = istante
    elif istante is not None:
        collegamento.cursori = {**(collegamento.cursori or {}), tipo: istante.isoformat()}
        CollegamentoEsterno.objects.filter(pk=collegamento.pk).update(cursori=collegamento.cursori)


def _importa_tipo(collegamento, sistema, tipo, fasi=None):
    """I record di un tipo cambiati dall'ultimo giro. Il cursore si salva a ogni pagina: un errore non fa ripartire
    da capo."""
    conti = {"creato": 0, "aggiornato": 0, "uguale": 0, "dubbio": 0}
    cursore = _cursore(collegamento, tipo)
    da = cursore - MARGINE if cursore else datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    dopo = None
    for _ in range(MASSIMO_PAGINE):
        record, dopo = sistema.modificati(tipo, da, dopo)
        verso_aziende = sistema.associazioni(tipo, AZIENDE, record) if collegamento.aziende and tipo in (CONTATTI, OPPORTUNITA) and record else {}
        verso_persone = sistema.associazioni(tipo, CONTATTI, record) if tipo == OPPORTUNITA and record else {}
        with eventi.senza_eventi(), transaction.atomic():
            for r in record:
                if tipo == AZIENDE:
                    esito = _applica_azienda(collegamento, sistema, r)
                elif tipo == OPPORTUNITA:
                    esito = _applica_opportunita(collegamento, sistema, r, fasi or [], verso_aziende.get(str(r["id"])), verso_persone.get(str(r["id"])))
                else:
                    esito = _applica(collegamento, sistema, r, verso_aziende.get(str(r["id"])))
                conti[esito] += 1
                istante = sistema.istante(tipo, r)
                if istante is not None and (cursore is None or istante > cursore):
                    cursore = istante
            _salva_cursore(collegamento, tipo, cursore)
        if not dopo:
            break
    return conti


def importa(collegamento):
    """Legge aziende, persone e opportunità cambiate dall'ultimo giro: {tipo: conti}. Le aziende prima, così le
    persone e le opportunità trovano il loro cliente."""
    sistema = client(collegamento)
    conti = {}
    if collegamento.aziende:
        conti[AZIENDE] = _importa_tipo(collegamento, sistema, AZIENDE)
    conti[CONTATTI] = _importa_tipo(collegamento, sistema, CONTATTI)
    if collegamento.opportunita and crm_attivo():
        conti[OPPORTUNITA] = _importa_tipo(collegamento, sistema, OPPORTUNITA, fasi=sistema.fasi())
    return conti


def riassunto(conti):
    """«Creati 1, aggiornati 0, uguali 3» per le persone, poi le aziende e le opportunità se è successo qualcosa."""
    p = conti.get(CONTATTI, {"creato": 0, "aggiornato": 0, "uguale": 0, "dubbio": 0})
    testo = f"Creati {p['creato']}, aggiornati {p['aggiornato']}, uguali {p['uguale']}"
    if p["dubbio"]:
        testo += f", saltati {p['dubbio']} (senza nome o con più contatti per la stessa email)"
    for tipo in (AZIENDE, OPPORTUNITA):
        c = conti.get(tipo)
        if not c or not any(c.values()):
            continue
        nome, create, aggiornate = NOMI[tipo]
        testo += f"; {nome}: {create} {c['creato']}, {aggiornate} {c['aggiornato']}, uguali {c['uguale']}"
        if c["dubbio"]:
            testo += f", saltate {c['dubbio']} (senza nome o con più record uguali)"
    return testo


def giro(collegamento_id):
    """Un giro di un collegamento in cui comanda l'esterno. Rilancia gli errori temporanei: ci ripensa il lavoro."""
    collegamento = CollegamentoEsterno.objects.select_related("azienda").filter(pk=collegamento_id, attivo=True).first()
    if collegamento is None or collegamento.comanda != CollegamentoEsterno.ESTERNO:
        return None
    try:
        conti = importa(collegamento)
    except ErroreTemporaneo as e:
        _esito(collegamento, str(e), errore=True)
        raise
    except ErroreConnettore as e:
        _esito(collegamento, str(e), errore=True)
        return str(e)
    testo = riassunto(conti)
    _esito(collegamento, testo)
    return testo


giro.senza_transazione = True


def giro_di_tutti():
    """Dal cron: un lavoro per collegamento, così uno lento o in errore non ferma gli altri."""
    for pk in CollegamentoEsterno.objects.filter(attivo=True, comanda=CollegamentoEsterno.ESTERNO).values_list("pk", flat=True):
        lavori.accoda("connettori.sincronia.giro", collegamento_id=pk, max_tentativi=3)


# --- da adabox all'esterno -----------------------------------------------------------------------------------------

def _collegamento_che_scrive(collegamento_id, obj):
    collegamento = CollegamentoEsterno.objects.select_related("azienda").filter(pk=collegamento_id, attivo=True).first()
    if collegamento is None or obj is None or obj.azienda_id != collegamento.azienda_id or collegamento.comanda != CollegamentoEsterno.ADABOX:
        return None
    return collegamento


def _id_azienda_fuori(collegamento, sistema, contatto):
    """L'id esterno dell'azienda: dal collegamento, poi dal dominio del sito, poi dal nome; se non c'è si crea.
    ErroreConnettore se il nome porta a più aziende di là."""
    chiave = riferimenti.id_esterno(contatto, collegamento.sistema)
    proprieta = sistema.fuori(AZIENDE, contatto)
    if chiave and chiave.startswith(f"{AZIENDE}:"):
        id_est = chiave.split(":", 1)[1]
        sistema.aggiorna(AZIENDE, id_est, proprieta)
    else:
        id_est = None
        if dominio_sito := dominio(contatto.sito):
            id_est = sistema.trova(AZIENDE, "dominio", dominio_sito)
        if not id_est:
            id_est = sistema.trova(AZIENDE, "nome", contatto.nome)
        if id_est is False:
            raise ErroreConnettore(f"Su {collegamento.get_sistema_display()} ci sono più aziende chiamate «{contatto.nome}»: collegane una a mano.")
        if id_est:
            sistema.aggiorna(AZIENDE, id_est, proprieta)
        else:
            id_est = sistema.crea(AZIENDE, proprieta)
    with eventi.senza_eventi():
        riferimenti.collega(contatto, collegamento.sistema, chiave_azienda(id_est))
    return id_est


def _id_persona_fuori(collegamento, sistema, contatto):
    """L'id esterno della persona (creata o aggiornata), con l'associazione alla sua azienda."""
    proprieta = sistema.fuori(PERSONE, contatto)
    id_est = riferimenti.id_esterno(contatto, collegamento.sistema) or sistema.trova(PERSONE, "email", contatto.email) or None
    if id_est:
        sistema.aggiorna(PERSONE, id_est, proprieta)
    else:
        id_est = sistema.crea(PERSONE, proprieta)
    with eventi.senza_eventi():
        riferimenti.collega(contatto, collegamento.sistema, id_est)
    if collegamento.aziende and contatto.societa_id:
        sistema.associa(CONTATTI, id_est, AZIENDE, _id_azienda_fuori(collegamento, sistema, contatto.societa))
    return id_est


def _scrivi(collegamento, cosa, funzione):
    try:
        funzione()
    except ErroreTemporaneo as e:
        _esito(collegamento, str(e), errore=True)
        raise
    except ErroreConnettore as e:
        _esito(collegamento, f"{cosa}: {e}", errore=True)
        return str(e)
    _esito(collegamento, f"Scritto {cosa} su {collegamento.get_sistema_display()}")
    return "scritto"


def scrivi_fuori(collegamento_id, contatto_id):
    """Un contatto di adabox verso il sistema esterno: le persone con un'email (è la chiave con cui si riconoscono di
    là), le aziende se il collegamento le comprende."""
    from contatti.models import Contatto
    contatto = Contatto.objects.select_related("societa").filter(pk=contatto_id).first()
    collegamento = _collegamento_che_scrive(collegamento_id, contatto)
    if collegamento is None:
        return None
    if contatto.tipo == Contatto.AZIENDA:
        if not collegamento.aziende:
            return "saltato: le aziende non passano in questo collegamento"
        sistema = client(collegamento)
        return _scrivi(collegamento, contatto, lambda: _id_azienda_fuori(collegamento, sistema, contatto))
    if not contatto.email:
        return "saltato: serve una persona con un'email"
    sistema = client(collegamento)
    return _scrivi(collegamento, contatto, lambda: _id_persona_fuori(collegamento, sistema, contatto))


scrivi_fuori.senza_transazione = True


def scrivi_opportunita(collegamento_id, opportunita_id):
    """Un'opportunità di adabox verso il sistema esterno, nella fase corrispondente e associata al cliente."""
    from contatti.models import Contatto
    from crm.models import Opportunita
    opportunita = Opportunita.objects.select_related("contatto__societa", "fase").filter(pk=opportunita_id).first()
    collegamento = _collegamento_che_scrive(collegamento_id, opportunita)
    if collegamento is None or not collegamento.opportunita:
        return None
    sistema = client(collegamento)

    def scrivi():
        proprieta = sistema.fuori(OPPORTUNITA, opportunita, fase_fuori(opportunita, sistema.fasi()))
        id_est = riferimenti.id_esterno(opportunita, collegamento.sistema)
        if id_est:
            sistema.aggiorna(OPPORTUNITA, id_est, proprieta)
        else:
            id_est = sistema.crea(OPPORTUNITA, proprieta)
        with eventi.senza_eventi():
            riferimenti.collega(opportunita, collegamento.sistema, id_est)
        cliente = opportunita.contatto
        if cliente is None:
            return
        if cliente.tipo == Contatto.AZIENDA:
            if collegamento.aziende:
                sistema.associa(OPPORTUNITA, id_est, AZIENDE, _id_azienda_fuori(collegamento, sistema, cliente))
            return
        if cliente.email:
            sistema.associa(OPPORTUNITA, id_est, CONTATTI, _id_persona_fuori(collegamento, sistema, cliente))
        if collegamento.aziende and cliente.societa_id:
            sistema.associa(OPPORTUNITA, id_est, AZIENDE, _id_azienda_fuori(collegamento, sistema, cliente.societa))
    return _scrivi(collegamento, f"l'opportunità {opportunita}", scrivi)


scrivi_opportunita.senza_transazione = True


def _da_mandare(instance, raw, update_fields):
    if raw or eventi.muto():
        return False
    return not (update_fields and set(update_fields) <= SOLO_CALCOLATI)


def _collegamenti_che_scrivono(azienda_id, **filtri):
    return list(CollegamentoEsterno.objects.filter(azienda_id=azienda_id, attivo=True, comanda=CollegamentoEsterno.ADABOX, **filtri)
                .values_list("pk", flat=True))


def contatto_salvato(sender, instance, raw=False, update_fields=None, **_):
    if not _da_mandare(instance, raw, update_fields):
        return
    pk = instance.pk
    for collegamento_id in _collegamenti_che_scrivono(instance.azienda_id):
        transaction.on_commit(lambda c=collegamento_id: lavori.accoda("connettori.sincronia.scrivi_fuori", collegamento_id=c, contatto_id=pk, max_tentativi=5))


def opportunita_salvata(sender, instance, raw=False, update_fields=None, **_):
    if not _da_mandare(instance, raw, update_fields):
        return
    pk = instance.pk
    for collegamento_id in _collegamenti_che_scrivono(instance.azienda_id, opportunita=True):
        transaction.on_commit(lambda c=collegamento_id: lavori.accoda("connettori.sincronia.scrivi_opportunita", collegamento_id=c,
                                                                      opportunita_id=pk, max_tentativi=5))
