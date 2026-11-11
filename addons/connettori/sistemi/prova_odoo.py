"""La prova di Odoo: un'istanza finta che risponde come l'API JSON-2 della 19 (POST /json/2/<modello>/<metodo>,
bearer, valori JSON, errori {"name", "message"}), senza uscire in rete. Riproduce ciò che conta per il connettore,
verificato su un Odoo vero: gli utenti con le loro regole (un venditore vede solo le sue opportunità, una
responsabile tutte), le persone che ereditano la partita IVA dall'azienda, gli utenti e l'azienda dell'istanza
che sono anch'essi contatti, le opportunità perse archiviate con won_status «lost». La chiave «prova:<uid>»
sceglie l'utente."""
import datetime
import json
import re

import httpx2 as httpx

from ..models import RecordProva
from .base import AZIENDE, OPPORTUNITA, PERSONE
from .prova import scrivi

URL, DATABASE = "https://prova.odoo.example", "prova"
UTENTI = {2: ("Amministratore", "tutto"), 28: ("Mario Venditore", "suoi"), 29: ("Lucia Responsabile", "tutto")}
PARTNER_UTENTI = {2: 3, 28: 36, 29: 37}          # anche gli utenti sono contatti
PARTNER_AZIENDA = 1                               # l'azienda dell'istanza
FASI = [(1, "New", 1, False), (2, "Qualified", 2, False), (3, "Proposition", 3, False), (4, "Won", 70, True)]
TIPI = {PERSONE: "res.partner", AZIENDE: "res.partner", OPPORTUNITA: "crm.lead"}


def chiave(uid):
    return f"prova:{uid}"


def _quando(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _partner(r):
    """Un contatto come lo legge Odoo, con il partner commerciale e la partita IVA ereditata dall'azienda."""
    p = dict(r.proprieta)
    madre = RecordProva.objects.filter(collegamento=r.collegamento, tipo=AZIENDE, id_esterno=str(p.get("parent_id") or "")).first()
    commerciale = madre or r
    return {**p, "id": int(r.id_esterno), "is_company": r.tipo == AZIENDE, "user_ids": [],
            "parent_id": [int(madre.id_esterno), madre.proprieta.get("name")] if madre else False,
            "commercial_partner_id": [int(commerciale.id_esterno), commerciale.proprieta.get("name")],
            "vat": commerciale.proprieta.get("vat") or False, "write_date": _quando(r.modificato_ms)}


def _lead(r):
    p = dict(r.proprieta)
    cliente = RecordProva.objects.filter(collegamento=r.collegamento, tipo__in=[PERSONE, AZIENDE], id_esterno=str(p.get("partner_id") or "")).first()
    commerciale = None
    if cliente is not None:
        commerciale = cliente if cliente.tipo == AZIENDE else RecordProva.objects.filter(
            collegamento=r.collegamento, tipo=AZIENDE, id_esterno=str(cliente.proprieta.get("parent_id") or "")).first() or cliente
    fase = next((f for f in FASI if f[0] == p.get("stage_id", 1)), FASI[0])
    won = "lost" if p.get("perso") else ("won" if fase[3] else "pending")
    return {"id": int(r.id_esterno), "type": "opportunity", "name": p.get("name"), "expected_revenue": p.get("expected_revenue", 0.0), "date_deadline": p.get("date_deadline") or False,
            "stage_id": [fase[0], fase[1]], "won_status": won, "active": not p.get("perso"), "probability": 0.0 if p.get("perso") else 10.0,
            "partner_id": [int(cliente.id_esterno), cliente.proprieta.get("name")] if cliente else False,
            "commercial_partner_id": [int(commerciale.id_esterno), commerciale.proprieta.get("name")] if commerciale else False,
            "user_id": [p["user_id"], UTENTI.get(p["user_id"], ("?",))[0]] if p.get("user_id") else False,
            "description": p.get("description") or False, "write_date": _quando(r.modificato_ms)}


def _vale(record, condizione):
    campo, op, valore = condizione
    attuale = record.get(campo)
    if isinstance(attuale, list) and attuale and not isinstance(valore, list) and campo not in ("user_ids",):
        attuale = attuale[0]
    if op == "=":
        return (attuale or False) == valore if valore is False else attuale == valore
    if op == "!=":
        return attuale != valore
    if op == ">=":
        return str(attuale or "") >= str(valore)
    if op == "in":
        return attuale in valore
    if op == "not in":
        return attuale not in valore
    if op in ("=ilike", "ilike"):
        testo = str(attuale or "").lower()
        return testo == str(valore).lower() if op == "=ilike" else str(valore).lower() in testo
    raise ValueError(f"operatore {op} non previsto dalla prova")


def _tutti(collegamento, modello, uid, contesto):
    qs = RecordProva.objects.filter(collegamento=collegamento)
    if modello == "res.partner":
        voci = [_partner(r) for r in qs.filter(tipo__in=[PERSONE, AZIENDE])]
        voci += [{"id": PARTNER_AZIENDA, "name": "Azienda dell'istanza", "is_company": True, "user_ids": [], "write_date": "2000-01-01 00:00:00"}]
        voci += [{"id": p, "name": UTENTI[u][0], "is_company": False, "user_ids": [u], "write_date": "2000-01-01 00:00:00"} for u, p in PARTNER_UTENTI.items()]
        return voci
    voci = [_lead(r) for r in qs.filter(tipo=OPPORTUNITA)]
    if UTENTI[uid][1] == "suoi":                       # la regola di Odoo «solo i propri documenti»
        voci = [v for v in voci if v["user_id"] and v["user_id"][0] == uid]
    if not (contesto or {}).get("active_test") is False:
        voci = [v for v in voci if v["active"]]
    return voci


def _cerca(collegamento, modello, uid, corpo):
    voci = [v for v in _tutti(collegamento, modello, uid, corpo.get("context")) if all(_vale(v, c) for c in corpo.get("domain") or [])]
    voci.sort(key=lambda v: (v.get("write_date") or "", v["id"]))
    inizio = int(corpo.get("offset") or 0)
    return voci[inizio:inizio + corpo["limit"]] if corpo.get("limit") else voci[inizio:]


def _errore(stato, nome, messaggio):
    return httpx.Response(stato, json={"name": nome, "message": messaggio, "arguments": [messaggio], "context": {}, "debug": ""})


def trasporto(collegamento):
    def rispondi(richiesta):
        if richiesta.url.host != "prova.odoo.example":
            return httpx.Response(404)
        trovato = re.match(r"bearer prova:(\d+)$", richiesta.headers.get("Authorization", ""))
        uid = int(trovato.group(1)) if trovato else None
        if uid not in UTENTI:
            return _errore(401, "werkzeug.exceptions.Unauthorized", "Invalid apikey")
        m = re.fullmatch(r"/json/2/([\w.]+)/(\w+)", richiesta.url.path)
        if m is None:
            return httpx.Response(404)
        modello, metodo = m.groups()
        corpo = json.loads(richiesta.content or b"{}")
        if modello == "res.users" and metodo == "context_get":
            return httpx.Response(200, json={"lang": "it_IT", "tz": False, "uid": uid})
        if modello == "res.company" and metodo == "search_read":
            return httpx.Response(200, json=[{"id": 1, "partner_id": [PARTNER_AZIENDA, "Azienda dell'istanza"]}])
        if modello == "crm.stage" and metodo == "search_read":
            return httpx.Response(200, json=[{"id": i, "name": n, "sequence": s, "is_won": v} for i, n, s, v in FASI])
        if modello not in ("res.partner", "crm.lead"):
            return _errore(404, "werkzeug.exceptions.NotFound", f"modello {modello}")
        if metodo == "fields_get":
            campi = ["name", "email", "phone", "function", "street", "city", "zip", "country_code", "website", "parent_id", "commercial_partner_id",
                     "is_company", "vat", "l10n_it_codice_fiscale", "user_ids", "write_date"] if modello == "res.partner" else \
                    ["name", "expected_revenue", "date_deadline", "stage_id", "won_status", "active", "probability", "partner_id",
                     "commercial_partner_id", "user_id", "description", "write_date", "type"]
            return httpx.Response(200, json={c: {"type": "char"} for c in campi})
        try:
            if metodo == "search_read":
                voci = _cerca(collegamento, modello, uid, corpo)
                campi = corpo.get("fields") or []
                return httpx.Response(200, json=[{"id": v["id"], **{c: v.get(c, False) for c in campi}} for v in voci])
            if metodo == "search":
                return httpx.Response(200, json=[v["id"] for v in _cerca(collegamento, modello, uid, corpo)])
        except ValueError as e:
            return _errore(500, "builtins.ValueError", str(e))
        if metodo == "create":
            nuovi = []
            for valori in corpo["vals_list"]:
                tipo = OPPORTUNITA if modello == "crm.lead" else (AZIENDE if valori.pop("is_company", False) else PERSONE)
                valori.pop("type", None)
                nuovi.append(int(scrivi(collegamento, valori, str(100 + RecordProva.objects.filter(collegamento=collegamento).count()), tipo).id_esterno))
            return httpx.Response(200, json=nuovi)
        if metodo == "write":
            for i in corpo["ids"]:
                r = RecordProva.objects.filter(collegamento=collegamento, id_esterno=str(i), tipo__in=[OPPORTUNITA] if modello == "crm.lead" else [PERSONE, AZIENDE]).first()
                if r is None:
                    return _errore(403, "odoo.exceptions.AccessError", "record non visibile")
                if modello == "crm.lead" and UTENTI[uid][1] == "suoi" and r.proprieta.get("user_id") != uid:
                    return _errore(403, "odoo.exceptions.AccessError", "Aiaiai! record super segreti")
                scrivi(collegamento, corpo["vals"], r.id_esterno, r.tipo)
            return httpx.Response(200, json=True)
        return _errore(404, "werkzeug.exceptions.NotFound", f"metodo {metodo}")
    return httpx.MockTransport(rispondi)


def simula_nuovo(c, s):
    azienda = None
    if c.aziende:
        azienda = scrivi(c, {"name": s["ditta"], "vat": "IT01234567897", "website": f"https://{s['dominio']}", "city": "Milano"},
                         str(200 + RecordProva.objects.filter(collegamento=c).count()), AZIENDE)
    persona = scrivi(c, {"name": f"{s['nome']} {s['cognome']}", "email": s["email"], "phone": s["telefono"],
                         "parent_id": int(azienda.id_esterno) if azienda else False},
                     str(200 + RecordProva.objects.filter(collegamento=c).count()), PERSONE)
    if c.opportunita:
        scrivi(c, {"name": s["titolo"], "expected_revenue": float(s["importo"]), "stage_id": FASI[s["fase"] % 3][0], "user_id": 28,
                   "partner_id": int(persona.id_esterno)}, str(200 + RecordProva.objects.filter(collegamento=c).count()), OPPORTUNITA)


def simula_modifica(c, ruolo):
    record = RecordProva.objects.filter(collegamento=c, tipo=PERSONE).first()
    if record is None:
        return False
    scrivi(c, {"function": ruolo}, record.id_esterno, PERSONE)
    trattativa = RecordProva.objects.filter(collegamento=c, tipo=OPPORTUNITA).first()
    if trattativa is not None:
        ordine = [f[0] for f in FASI]
        attuale = trattativa.proprieta.get("stage_id", 1)
        scrivi(c, {"stage_id": ordine[min(ordine.index(attuale) + 1 if attuale in ordine else 0, len(ordine) - 1)]}, trattativa.id_esterno, OPPORTUNITA)
    return True


def riga(r):
    p = r.proprieta
    if r.tipo == OPPORTUNITA:
        return p.get("name", ""), f"{p.get('expected_revenue', '')} € · fase {p.get('stage_id', 1)} · venditore {p.get('user_id', '')}"
    return p.get("name", ""), f"{p.get('vat') or ''} {p.get('email') or ''} {p.get('city') or ''}".strip()

