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
import re

from django.apps import apps
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core import lavori, sequenze

from . import eventi, riferimenti, sistemi
from .models import AccountEsterno, CollegamentoEsterno, RiferimentoEsterno, VisibilitaEsterna
from .sistemi.base import AZIENDE, EVENTI, OPPORTUNITA, ORDINI, PERSONE, ErroreConnettore, ErroreTemporaneo, dominio

CONTATTI = PERSONE

log = logging.getLogger("connettori.sincronia")
MARGINE = datetime.timedelta(minutes=5)       # i record cambiati compaiono nella ricerca con un po' di ritardo
MASSIMO_PAGINE = 50                           # il resto al prossimo giro: il cursore è già avanzato
LUNGHEZZE = {"nome": 200, "ruolo": 100, "indirizzo": 200, "citta": 100, "cap": 10, "telefono": 40, "cellulare": 40, "sito": 200,
             "email": 254, "nazione": 2, "partita_iva": 28, "codice_fiscale": 16}
NOMI = {CONTATTI: ("persone", "create", "aggiornate"), AZIENDE: ("aziende", "create", "aggiornate"),
        OPPORTUNITA: ("opportunità", "create", "aggiornate"), EVENTI: ("appuntamenti", "creati", "aggiornati"),
        ORDINI: ("ordini di vendita", "creati", "aggiornati")}
# campi che cambiano da soli (calcoli periodici): un salvataggio che tocca solo questi non riparte verso l'esterno
SOLO_CALCOLATI = {"classe_abc", "fatturato_12_mesi", "vies_valido", "vies_il", "punteggio", "punteggio_fattori", "punteggio_il"}


def client(collegamento, account=None):
    return sistemi.client(collegamento, account)


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


def _fiscali(dati):
    """Partita IVA senza il prefisso del paese (come la salva l'anagrafica), il paese dal prefisso se manca, codice
    fiscale in maiuscolo: così si confrontano con quelle già in adabox."""
    from contatti import validatori
    if dati.get("partita_iva"):
        grezza = re.sub(r"[\s.\-]", "", dati["partita_iva"]).upper()
        if not dati.get("nazione") and len(grezza) > 2 and grezza[:2].isalpha():
            dati["nazione"] = "GR" if grezza[:2] == "EL" else grezza[:2]
        dati["partita_iva"] = validatori.normalizza_partita_iva(grezza, dati.get("nazione") or "IT")[:28]
    if dati.get("codice_fiscale"):
        dati["codice_fiscale"] = dati["codice_fiscale"].strip().upper()[:16]
    return dati


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
    societa = _azienda_collegata(collegamento, aziende_associate) if collegamento.aziende else None
    if societa is not None:
        dati["societa"] = societa
        if contatto is None:                           # senza email: per nome, ma solo tra le persone di quell'azienda
            stessi = list(Contatto.objects.filter(azienda=azienda, tipo=Contatto.PERSONA, societa=societa, nome__iexact=dati["nome"])[:2])
            if len(stessi) > 1:
                return "dubbio"
            if stessi and riferimenti.id_esterno(stessi[0], collegamento.sistema) in (None, str(record["id"])):
                contatto = stessi[0]
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
    dati = _fiscali(_taglia(sistema.in_adabox(AZIENDE, record)))
    if not dati.get("nome"):
        return "dubbio"
    azienda = collegamento.azienda
    chiave = chiave_azienda(record["id"])
    contatto = riferimenti.trova(Contatto, azienda, collegamento.sistema, chiave)
    if contatto is None and dati.get("partita_iva"):         # la partita IVA prima del nome: è la chiave più sicura
        stessi = list(Contatto.objects.filter(azienda=azienda, tipo=Contatto.AZIENDA, partita_iva=dati["partita_iva"])[:2])
        if len(stessi) > 1:
            return "dubbio"
        if stessi:
            if riferimenti.id_esterno(stessi[0], collegamento.sistema) not in (None, chiave):
                return "dubbio"                           # già collegata a un'altra azienda esterna con la stessa partita IVA
            contatto = stessi[0]
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
    if (utente := utenti_esterni(collegamento).get(dati.pop("utente_esterno", None))) is not None:
        dati["commerciale"] = utente                   # il venditore di là, se ha collegato il suo account
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


def _silenzio_calendario():
    """Ciò che arriva dal sistema esterno non riparte nemmeno verso Google o Microsoft (modulo Posta e calendario)."""
    import contextlib
    if apps.is_installed("posta"):
        from posta import agenda
        return agenda.senza_eventi()
    return contextlib.nullcontext()


def _applica_evento(collegamento, sistema, record, utenti_dei_partner):
    """Un appuntamento esterno su un evento del calendario: organizzatore e partecipanti interni dagli account
    collegati, i clienti invitati dai contatti già collegati; senza promemoria né inviti."""
    from calendario.models import Evento
    from contatti.models import Contatto
    dati = sistema.in_adabox(EVENTI, record)
    if dati.get("inizio") is None:
        return "dubbio"
    utenti = utenti_esterni(collegamento)
    partecipanti = dati.pop("partecipanti_esterni", [])
    organizzatore = utenti.get(dati.pop("utente_esterno", None))
    interni = [u for u in (utenti.get(utenti_dei_partner.get(p)) for p in partecipanti) if u is not None and u != organizzatore]
    contatti = [c for c in (riferimenti.trova(Contatto, collegamento.azienda, collegamento.sistema, p)
                            or riferimenti.trova(Contatto, collegamento.azienda, collegamento.sistema, chiave_azienda(p))
                            for p in partecipanti if p not in utenti_dei_partner) if c is not None]
    evento = riferimenti.trova(Evento, collegamento.azienda, collegamento.sistema, record["id"])
    if organizzatore is not None:
        dati["organizzatore"] = organizzatore
    with _silenzio_calendario():
        if evento is None:
            evento = Evento.objects.create(azienda=collegamento.azienda, promemoria=0, **dati)
            esito = "creato"
        else:
            esito = "aggiornato" if _aggiorna(evento, dati) else "uguale"
        if set(evento.partecipanti.values_list("pk", flat=True)) != {u.pk for u in interni}:
            evento.partecipanti.set(interni)
            esito = "aggiornato" if esito == "uguale" else esito
        if contatti and not {c.pk for c in contatti} <= set(evento.contatti.values_list("pk", flat=True)):
            evento.contatti.add(*contatti)
            esito = "aggiornato" if esito == "uguale" else esito
    riferimenti.collega(evento, collegamento.sistema, record["id"])
    return esito


def _aliquota(tassa):
    """L'aliquota IVA di adabox per una tassa esterna: per percentuale; allo 0% per natura IVA (N1…N7)."""
    from decimal import Decimal

    from fiscale.models import AliquotaIva
    if tassa is None:
        return None
    percentuale = Decimal(str(tassa.get("amount") or 0)).quantize(Decimal("0.01"))
    voci = AliquotaIva.objects.filter(percentuale=percentuale, attiva=True)
    if percentuale == 0:
        natura = str(tassa.get("l10n_it_exempt_reason") or "")
        return (voci.filter(natura=natura).first() or voci.filter(codice=natura).first()) if natura else voci.order_by("codice").first()
    return voci.filter(natura="").order_by("codice").first() or voci.first()


def _prodotto(collegamento, dati, aliquota):
    """Il prodotto di adabox per un prodotto esterno: dal collegamento, poi dal codice, poi dal codice a barre; se non
    c'è si crea (scelta del 2026-11-11), con codice, nome, prezzo, tipo e aliquota."""
    from decimal import Decimal

    from prodotti.models import Prodotto
    azienda = collegamento.azienda
    prodotto = riferimenti.trova(Prodotto, azienda, collegamento.sistema, dati["id"])
    for campo, valore in (("codice", dati.get("default_code")), ("codice_barre", dati.get("barcode"))):
        if prodotto is None and valore:
            stessi = list(Prodotto.objects.filter(azienda=azienda, **{campo: str(valore)[:40]})[:2])
            prodotto = stessi[0] if len(stessi) == 1 else None
    if prodotto is None:
        from prodotti.models import aliquota_predefinita, unita_predefinita
        if (aliquota is None and aliquota_predefinita() is None) or unita_predefinita() is None:
            return None                                 # anagrafica dei prodotti non pronta (aliquote, unità): la riga resta descrittiva
        campi = {"azienda": azienda, "codice": str(dati.get("default_code") or "")[:40], "nome": str(dati.get("name") or "Prodotto")[:200],
                 "tipo": Prodotto.SERVIZIO if dati.get("type") == "service" else Prodotto.BENE,
                 "prezzo_vendita": Decimal(str(dati.get("list_price") or 0)), "codice_barre": str(dati.get("barcode") or "")[:40]}
        if aliquota is not None:
            campi["aliquota_iva"] = aliquota
        prodotto = Prodotto.objects.create(**campi)
    riferimenti.collega(prodotto, collegamento.sistema, dati["id"])
    return prodotto


def _applica_ordine(collegamento, sistema, record, righe, prodotti, tasse):
    """Un ordine di vendita esterno, in sola lettura (core.esterni): testata con il numero di Odoo, cliente (l'azienda
    del contatto), commerciale e opportunità dai collegati; righe ricreate a ogni modifica; totali ricalcolati.
    Non manda il segnale di conferma: consegne e fatture restano al sistema esterno."""
    from decimal import Decimal

    from contatti.models import Contatto
    from vendite.models import OrdineVendita, RigaVendita

    from .sistemi.odoo import aliquota_iva
    dati = sistema.in_adabox(ORDINI, record)
    azienda = collegamento.azienda
    partner = dati.pop("partner_esterno", "")
    contatto = (riferimenti.trova(Contatto, azienda, collegamento.sistema, partner)
                or riferimenti.trova(Contatto, azienda, collegamento.sistema, chiave_azienda(partner))) if partner else None
    if contatto is None or not dati.get("numero"):
        return "dubbio"
    dati["cliente"] = contatto.societa if contatto.tipo == Contatto.PERSONA and contatto.societa_id else contatto
    if (utente := utenti_esterni(collegamento).get(dati.pop("utente_esterno", None))) is not None:
        dati["commerciale"] = utente
    if (id_opp := dati.pop("opportunita_esterna", None)) and crm_attivo():
        from crm.models import Opportunita
        if (opp := riferimenti.trova(Opportunita, azienda, collegamento.sistema, id_opp)) is not None:
            dati["opportunita_id"] = opp.pk
    dati["numero_ordine"] = dati["numero"] if dati["stato"] == OrdineVendita.CONFERMATO else ""
    dati = {k: v for k, v in dati.items() if v is not None}
    ordine = riferimenti.trova(OrdineVendita, azienda, collegamento.sistema, record["id"])
    nuove = []
    for r in righe:
        if r.get("display_type"):                      # sezioni e note: righe descrittive
            nuove.append({"descrizione": str(r.get("name") or "")[:250], "quantita": Decimal(0), "prezzo": Decimal(0)})
            continue
        aliquota = _aliquota(aliquota_iva([tasse[str(t)] for t in r.get("tax_ids") or [] if str(t) in tasse]))
        dati_prodotto = prodotti.get(str(_id_lista(r.get("product_id")))) if r.get("product_id") else None
        prodotto = _prodotto(collegamento, dati_prodotto, aliquota) if dati_prodotto else None
        nuove.append({"prodotto": prodotto, "descrizione": str(r.get("name") or "")[:250], "quantita": Decimal(str(r.get("product_uom_qty") or 0)),
                      "prezzo": Decimal(str(r.get("price_unit") or 0)), "sconto": Decimal(str(r.get("discount") or 0)), "aliquota": aliquota})
    impronta_righe = [(n.get("prodotto").pk if n.get("prodotto") else None, n["descrizione"], n["quantita"], n["prezzo"], n.get("sconto", 0),
                       n.get("aliquota").pk if n.get("aliquota") else None) for n in nuove]
    esito = "uguale"
    if ordine is None:
        ordine = OrdineVendita.objects.create(azienda=azienda, **dati)
        esito = "creato"
    elif _aggiorna(ordine, dati):
        esito = "aggiornato"
    attuali = [(r.prodotto_id, r.descrizione, r.quantita, r.prezzo, r.sconto, r.aliquota_id) for r in ordine.righe.order_by("pk")]

    def uguali(riga):                                  # 2.000 e 2 sono la stessa quantità
        valori = [v.normalize() if isinstance(v, Decimal) else v for v in riga]
        if valori[0] is None and not valori[3]:         # riga descrittiva: adabox ci mette l'aliquota predefinita, non conta
            valori[5] = None
        return tuple(valori)
    if [uguali(x) for x in attuali] != [uguali(x) for x in impronta_righe]:
        ordine.righe.all().delete()
        for n in nuove:
            RigaVendita.objects.create(ordine=ordine, **n)
        ordine.ricalcola()
        esito = "aggiornato" if esito == "uguale" else esito
    riferimenti.collega(ordine, collegamento.sistema, record["id"])
    return esito


def _id_lista(valore):
    return valore[0] if isinstance(valore, (list, tuple)) and valore else valore


def _cursore(collegamento, tipo, account=None):
    """Fin dove si è letto: per il collegamento o, con una chiave per utente, per l'account (ognuno vede altro)."""
    if account is not None:
        valore = (account.cursori or {}).get(tipo)
        return parse_datetime(valore) if valore else None
    if tipo == CONTATTI:
        return collegamento.cursore
    valore = (collegamento.cursori or {}).get(tipo)
    return parse_datetime(valore) if valore else None


def _salva_cursore(collegamento, tipo, istante, account=None):
    if account is not None:
        if istante is not None:
            account.cursori = {**(account.cursori or {}), tipo: istante.isoformat()}
            AccountEsterno.objects.filter(pk=account.pk).update(cursori=account.cursori)
    elif tipo == CONTATTI:
        CollegamentoEsterno.objects.filter(pk=collegamento.pk).update(cursore=istante)
        collegamento.cursore = istante
    elif istante is not None:
        collegamento.cursori = {**(collegamento.cursori or {}), tipo: istante.isoformat()}
        CollegamentoEsterno.objects.filter(pk=collegamento.pk).update(cursori=collegamento.cursori)


def utenti_esterni(collegamento):
    """{id dell'utente nel sistema esterno: utente di adabox} degli account collegati: il venditore di un'opportunità
    di Odoo diventa il commerciale in adabox se ha collegato il suo account."""
    if not hasattr(collegamento, "_utenti_esterni"):
        collegamento._utenti_esterni = {a.id_utente_esterno: a.utente for a in AccountEsterno.objects.filter(
            collegamento=collegamento, utente__is_active=True).exclude(id_utente_esterno="").select_related("utente")}
    return collegamento._utenti_esterni


def _importa_tipo(collegamento, sistema, tipo, fasi=None, account=None):
    """I record di un tipo cambiati dall'ultimo giro. Il cursore si salva a ogni pagina: un errore non fa ripartire
    da capo."""
    conti = {"creato": 0, "aggiornato": 0, "uguale": 0, "dubbio": 0}
    cursore = _cursore(collegamento, tipo, account)
    da = cursore - MARGINE if cursore else datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    dopo = None
    for _ in range(MASSIMO_PAGINE):
        record, dopo = sistema.modificati(tipo, da, dopo)
        verso_aziende = sistema.associazioni(tipo, AZIENDE, record) if collegamento.aziende and tipo in (CONTATTI, OPPORTUNITA) and record else {}
        verso_persone = sistema.associazioni(tipo, CONTATTI, record) if tipo == OPPORTUNITA and record else {}
        utenti_dei_partner = (sistema.utenti_dei_partner({p for r in record for p in (r.get("partner_ids") or [])})
                              if tipo == EVENTI and record else {})
        righe = sistema.righe_ordini([r["id"] for r in record]) if tipo == ORDINI and record else {}
        prodotti = sistema.prodotti({_id_lista(x["product_id"]) for rr in righe.values() for x in rr if x.get("product_id")}) if righe else {}
        tasse = sistema.tasse({t for rr in righe.values() for x in rr for t in (x.get("tax_ids") or [])} |
                              {t for p in prodotti.values() for t in (p.get("taxes_id") or [])}) if righe else {}
        with eventi.senza_eventi(), transaction.atomic():
            for r in record:
                if tipo == EVENTI:
                    esito = _applica_evento(collegamento, sistema, r, utenti_dei_partner)
                elif tipo == ORDINI:
                    esito = _applica_ordine(collegamento, sistema, r, righe.get(str(r["id"]), []), prodotti, tasse)
                elif tipo == AZIENDE:
                    esito = _applica_azienda(collegamento, sistema, r)
                elif tipo == OPPORTUNITA:
                    esito = _applica_opportunita(collegamento, sistema, r, fasi or [], verso_aziende.get(str(r["id"])), verso_persone.get(str(r["id"])))
                else:
                    esito = _applica(collegamento, sistema, r, verso_aziende.get(str(r["id"])))
                conti[esito] += 1
                istante = sistema.istante(tipo, r)
                if istante is not None and (cursore is None or istante > cursore):
                    cursore = istante
            _salva_cursore(collegamento, tipo, cursore, account)
        if not dopo:
            break
    return conti


def tipi_attivi(collegamento):
    """Le aziende prima, poi le persone, le opportunità e gli appuntamenti (per ora solo da Odoo): così ognuno trova i
    suoi collegati."""
    odoo = collegamento.sistema == CollegamentoEsterno.ODOO
    eventi_attivi = collegamento.calendario and odoo and apps.is_installed("calendario")
    ordini_attivi = collegamento.ordini and odoo and apps.is_installed("vendite")
    return [t for t, attivo in ((AZIENDE, collegamento.aziende), (CONTATTI, True), (OPPORTUNITA, collegamento.opportunita and crm_attivo()),
                                (ORDINI, ordini_attivi), (EVENTI, eventi_attivi)) if attivo]


def importa(collegamento, sistema=None, account=None):
    """Legge aziende, persone e opportunità cambiate dall'ultimo giro: {tipo: conti}. Le aziende prima, così le
    persone e le opportunità trovano il loro cliente."""
    sistema = sistema or client(collegamento, account)
    conti = {}
    for tipo in tipi_attivi(collegamento):
        conti[tipo] = _importa_tipo(collegamento, sistema, tipo, fasi=sistema.fasi() if tipo == OPPORTUNITA else None, account=account)
    return conti


def _modello_di(tipo):
    from django.apps import apps as registro
    if tipo == EVENTI:
        return registro.get_model("calendario", "Evento")
    if tipo == ORDINI:
        return registro.get_model("vendite", "OrdineVendita")
    return registro.get_model("crm", "Opportunita") if tipo == OPPORTUNITA else registro.get_model("contatti", "Contatto")


def riconcilia(collegamento, sistema, account):
    """La visibilità dell'account allineata a ciò che il sistema gli mostra adesso: i record che vede in più si
    aggiungono, quelli che non vede più (regole cambiate, record riassegnato) si tolgono. {"aggiunti", "tolti"}."""
    from django.contrib.contenttypes.models import ContentType
    conti = {"aggiunti": 0, "tolti": 0}
    for tipo in tipi_attivi(collegamento):
        ids = sistema.ids_visibili(tipo)
        chiavi = {chiave_azienda(i) for i in ids} if tipo == AZIENDE else ids
        rif = RiferimentoEsterno.objects.filter(azienda=collegamento.azienda, sistema=collegamento.sistema,
                                                content_type=ContentType.objects.get_for_model(_modello_di(tipo)))
        if tipo == AZIENDE:
            rif = rif.filter(id_esterno__startswith=chiave_azienda(""))
        elif tipo == CONTATTI:
            rif = rif.exclude(id_esterno__startswith=chiave_azienda(""))
        visti = dict(rif.values_list("id_esterno", "pk"))
        dovuti = {visti[c] for c in chiavi if c in visti}
        attuali = set(VisibilitaEsterna.objects.filter(account=account, riferimento__in=visti.values()).values_list("riferimento_id", flat=True))
        VisibilitaEsterna.objects.bulk_create([VisibilitaEsterna(account=account, riferimento_id=r) for r in dovuti - attuali],
                                              ignore_conflicts=True)
        conti["tolti"] += VisibilitaEsterna.objects.filter(account=account, riferimento_id__in=attuali - dovuti).delete()[0]
        conti["aggiunti"] += len(dovuti - attuali)
    return conti


def riassunto(conti):
    """«Creati 1, aggiornati 0, uguali 3» per le persone, poi le aziende e le opportunità se è successo qualcosa."""
    p = conti.get(CONTATTI, {"creato": 0, "aggiornato": 0, "uguale": 0, "dubbio": 0})
    testo = f"Creati {p['creato']}, aggiornati {p['aggiornato']}, uguali {p['uguale']}"
    if p["dubbio"]:
        testo += f", saltati {p['dubbio']} (senza nome o con più contatti per la stessa email)"
    for tipo in (AZIENDE, OPPORTUNITA, ORDINI, EVENTI):
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
    if collegamento.per_utente:                        # con una chiave per utente i giri sono per account
        for pk in collegamento.account.filter(utente__is_active=True).values_list("pk", flat=True):
            lavori.accoda("connettori.sincronia.giro_account", account_id=pk, azienda=collegamento.azienda, max_tentativi=3)
        return "giri accodati per gli account"
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


def _esito_account(account, testo, errore=False):
    AccountEsterno.objects.filter(pk=account.pk).update(ultimo_giro=timezone.now(), ultimo_esito=testo[:500], in_errore=errore)


def giro_account(account_id):
    """Un giro con la chiave di un utente: legge ciò che il sistema mostra a lui e allinea la sua visibilità."""
    account = (AccountEsterno.objects.select_related("collegamento__azienda", "utente")
               .filter(pk=account_id, utente__is_active=True, collegamento__attivo=True, collegamento__per_utente=True).first())
    if account is None or account.collegamento.comanda != CollegamentoEsterno.ESTERNO:
        return None
    collegamento = account.collegamento
    try:
        sistema = client(collegamento, account)
        conti = importa(collegamento, sistema, account)
        visibilita = riconcilia(collegamento, sistema, account)
    except ErroreTemporaneo as e:
        _esito_account(account, str(e), errore=True)
        raise
    except ErroreConnettore as e:
        _esito_account(account, str(e), errore=True)
        return str(e)
    testo = riassunto(conti) + (f"; visibili in più {visibilita['aggiunti']}, non più visibili {visibilita['tolti']}"
                                if visibilita["aggiunti"] or visibilita["tolti"] else "")
    _esito_account(account, testo)
    _esito(collegamento, f"{account.utente}: {testo}")
    return testo


giro_account.senza_transazione = True


def giro_di_tutti():
    """Dal cron: un lavoro per collegamento (o per account, con una chiave per utente), così uno lento o in errore non
    ferma gli altri."""
    for pk in CollegamentoEsterno.objects.filter(attivo=True, comanda=CollegamentoEsterno.ESTERNO, per_utente=False).values_list("pk", flat=True):
        lavori.accoda("connettori.sincronia.giro", collegamento_id=pk, max_tentativi=3)
    for pk in AccountEsterno.objects.filter(collegamento__attivo=True, collegamento__per_utente=True, collegamento__comanda=CollegamentoEsterno.ESTERNO,
                                            utente__is_active=True).values_list("pk", flat=True):
        lavori.accoda("connettori.sincronia.giro_account", account_id=pk, max_tentativi=3)


# --- da adabox all'esterno -----------------------------------------------------------------------------------------

def _collegamento_che_scrive(collegamento_id, obj, account=None):
    """Il collegamento se deve scrivere quel record: comanda adabox, oppure (con l'account di chi ha salvato) un
    collegamento per utente con «le modifiche fatte in adabox tornano lì»."""
    collegamento = CollegamentoEsterno.objects.select_related("azienda").filter(pk=collegamento_id, attivo=True).first()
    if collegamento is None or obj is None or obj.azienda_id != collegamento.azienda_id:
        return None
    if account is not None:
        return collegamento if collegamento.per_utente and collegamento.scrive_da_adabox and account.collegamento_id == collegamento.pk else None
    return collegamento if collegamento.comanda == CollegamentoEsterno.ADABOX and not collegamento.per_utente else None


def _account_di(collegamento_id, utente_id):
    if utente_id is None:
        return None
    return (AccountEsterno.objects.select_related("utente").filter(collegamento_id=collegamento_id, utente_id=utente_id, utente__is_active=True)
            .exclude(chiave_cifrata="").first())


def _rendi_visibile(account, *oggetti):
    """Ciò che l'utente ha appena scritto nel sistema esterno resta suo anche in adabox, senza aspettare il giro."""
    if account is None:
        return
    from django.contrib.contenttypes.models import ContentType
    for obj in oggetti:
        if obj is None:
            continue
        rif = RiferimentoEsterno.objects.filter(azienda_id=obj.azienda_id, sistema=account.collegamento.sistema,
                                                content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk).first()
        if rif is not None:
            VisibilitaEsterna.objects.get_or_create(riferimento=rif, account=account)


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
        if contatto.partita_iva and "piva" in getattr(sistema, "CHIAVI_AZIENDA", ()):
            id_est = sistema.trova(AZIENDE, "piva", contatto.partita_iva)
            if id_est is False:
                raise ErroreConnettore(f"Su {collegamento.get_sistema_display()} ci sono più aziende con la partita IVA {contatto.partita_iva}: collegane una a mano.")
        if not id_est and (dominio_sito := dominio(contatto.sito)):
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


def _scrivi(collegamento, cosa, funzione, account=None, obj=None):
    try:
        funzione()
    except ErroreTemporaneo as e:
        (_esito_account(account, str(e), errore=True) if account else _esito(collegamento, str(e), errore=True))
        raise
    except ErroreConnettore as e:
        if account is None:
            _esito(collegamento, f"{cosa}: {e}", errore=True)
            return str(e)
        _esito_account(account, f"{cosa}: {e}")       # un rifiuto su un record non vuol dire chiave da rifare
        if obj is not None:                            # chi ha salvato lo vede sul record: non è passato di là
            from core import chatter
            from core.models import Messaggio
            with eventi.senza_eventi():
                chatter.scrivi(obj, None, f"Non scritto in {collegamento.get_sistema_display()} con l'account di {account.utente}: {e}",
                               tipo=Messaggio.SISTEMA)
        return str(e)
    if account is None:
        _esito(collegamento, f"Scritto {cosa} su {collegamento.get_sistema_display()}")
    else:
        _esito_account(account, f"Scritto {cosa} su {collegamento.get_sistema_display()}")
    return "scritto"


def scrivi_fuori(collegamento_id, contatto_id, utente_id=None):
    """Un contatto di adabox verso il sistema esterno: le persone con un'email (è la chiave con cui si riconoscono di
    là), le aziende se il collegamento le comprende. Con `utente_id` (collegamento per utente) con la sua chiave."""
    from contatti.models import Contatto
    contatto = Contatto.objects.select_related("societa").filter(pk=contatto_id).first()
    account = _account_di(collegamento_id, utente_id) if utente_id else None
    if utente_id and account is None:
        return "saltato: chi ha salvato non ha collegato il suo account"
    collegamento = _collegamento_che_scrive(collegamento_id, contatto, account)
    if collegamento is None:
        return None
    sistema = client(collegamento, account)
    if contatto.tipo == Contatto.AZIENDA:
        if not collegamento.aziende:
            return "saltato: le aziende non passano in questo collegamento"
        esito = _scrivi(collegamento, contatto, lambda: _id_azienda_fuori(collegamento, sistema, contatto), account, contatto)
    elif not contatto.email:
        return "saltato: serve una persona con un'email"
    else:
        esito = _scrivi(collegamento, contatto, lambda: _id_persona_fuori(collegamento, sistema, contatto), account, contatto)
    _rendi_visibile(account, contatto, contatto.societa)
    return esito


scrivi_fuori.senza_transazione = True


def scrivi_opportunita(collegamento_id, opportunita_id, utente_id=None):
    """Un'opportunità di adabox verso il sistema esterno, nella fase corrispondente e associata al cliente. Con
    `utente_id` (collegamento per utente) con la sua chiave."""
    from contatti.models import Contatto
    from crm.models import Opportunita
    opportunita = Opportunita.objects.select_related("contatto__societa", "fase").filter(pk=opportunita_id).first()
    account = _account_di(collegamento_id, utente_id) if utente_id else None
    if utente_id and account is None:
        return "saltato: chi ha salvato non ha collegato il suo account"
    collegamento = _collegamento_che_scrive(collegamento_id, opportunita, account)
    if collegamento is None or not collegamento.opportunita:
        return None
    sistema = client(collegamento, account)

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
    esito = _scrivi(collegamento, f"l'opportunità {opportunita}", scrivi, account, opportunita)
    cliente = opportunita.contatto
    _rendi_visibile(account, opportunita, cliente, getattr(cliente, "societa", None))
    return esito


scrivi_opportunita.senza_transazione = True


def _da_mandare(instance, raw, update_fields):
    if raw or eventi.muto():
        return False
    return not (update_fields and set(update_fields) <= SOLO_CALCOLATI)


def _collegamenti_che_scrivono(azienda_id, **filtri):
    return list(CollegamentoEsterno.objects.filter(azienda_id=azienda_id, attivo=True, comanda=CollegamentoEsterno.ADABOX, per_utente=False, **filtri)
                .values_list("pk", flat=True))


def _per_utente_che_scrivono(azienda_id, **filtri):
    """I collegamenti per utente in cui le modifiche di adabox tornano nel sistema, con la chiave di chi salva."""
    return list(CollegamentoEsterno.objects.filter(azienda_id=azienda_id, attivo=True, per_utente=True, scrive_da_adabox=True, **filtri)
                .values_list("pk", flat=True))


def _accoda_scritture(funzione, azienda_id, chiave, pk, **filtri):
    for collegamento_id in _collegamenti_che_scrivono(azienda_id, **filtri):
        transaction.on_commit(lambda c=collegamento_id: lavori.accoda(f"connettori.sincronia.{funzione}", collegamento_id=c, max_tentativi=5,
                                                                      **{chiave: pk}))
    from core import registro
    utente = registro.utente_corrente()                # senza un utente (lavori di sistema) non c'è una chiave con cui scrivere
    if utente is None:
        return
    for collegamento_id in _per_utente_che_scrivono(azienda_id, **filtri):
        transaction.on_commit(lambda c=collegamento_id, u=utente.pk: lavori.accoda(f"connettori.sincronia.{funzione}", collegamento_id=c,
                                                                                  utente_id=u, max_tentativi=5, **{chiave: pk}))


def contatto_salvato(sender, instance, raw=False, update_fields=None, **_):
    if _da_mandare(instance, raw, update_fields):
        _accoda_scritture("scrivi_fuori", instance.azienda_id, "contatto_id", instance.pk)


def opportunita_salvata(sender, instance, raw=False, update_fields=None, **_):
    if _da_mandare(instance, raw, update_fields):
        _accoda_scritture("scrivi_opportunita", instance.azienda_id, "opportunita_id", instance.pk, opportunita=True)
