"""Strumenti dell'assistente AI per trovare e chiedere agenti AI dalla chat (chiave "ai" del manifest).

L'assistente fa da guida: chiede il reparto, quanti record al giorno e per quanto tempo, legge il negozio e propone
l'agente; la richiesta parte solo quando l'utente conferma la proposta, e come dalla procedura «Assumi» adabox si
prepara da solo (cosa può fare: le scelte proposte, cambiabili poi da I miei agenti). Il contratto lo prepara
Agentlia e lo conferma una persona (pagina di Agate, il garante); poi adabox si collega da solo (vedi
`fabbrica.aggiorna`).

Solo chi gestisce AWF (il permesso delle sue pagine) vede e usa questi strumenti. Non arrivano mai agli agenti: sono
in `operazioni.ESCLUSI`. Con il modulo agate attivo, la conferma di `richiedi_squadra` passa dalla guardia di Agate
come `adabox.richiedi_squadra`."""
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone

from ai.strumenti import ErroreStrumento, Strumento, registra

from . import assunzione, fabbrica, operazioni, squadre
from .models import Collegamento, RichiestaAgenti

PERMESSO = "awf.change_collegamento"


def _controlla(contesto):
    if not contesto.utente.has_perm(PERMESSO):
        raise PermissionDenied


def _catalogo(reparto=""):
    try:
        return fabbrica.catalogo(reparto)
    except fabbrica.ErroreFabbrica as e:
        raise ErroreStrumento(f"Il negozio degli agenti non risponde: {e}. Riprova tra poco o apri "
                              "Agenti AI → Negozio.")


def catalogo_agenti(contesto, reparto=""):
    _controlla(contesto)
    elenco = _catalogo(reparto)
    tutte = operazioni.viste()
    risposta = {"squadre": [squadre.compatta(s, tutte) for s in elenco], "pagina": reverse("awf:negozio"),
                "come_funziona": " ".join(f"{n}. {p}" for n, p in enumerate(squadre.PASSI, 1))}
    if not elenco:
        risposta["nota"] = ("Nessun agente per questo reparto: prova senza reparto per vedere tutto il negozio."
                            if reparto else "Il negozio degli agenti per adabox è vuoto.")
    return risposta


def _valida(team, settimane, note):
    if not isinstance(team, str) or not team.strip():
        raise ErroreStrumento("«team» è lo slug di una squadra: leggilo con catalogo_agenti.")
    s = next((x for x in _catalogo() if x["slug"] == team.strip()), None)
    if s is None:
        raise ErroreStrumento(f"La squadra «{team}» non è nel negozio: leggilo con catalogo_agenti.")
    try:
        settimane = int(settimane)
    except (TypeError, ValueError):
        raise ErroreStrumento("«settimane» è un numero intero da 1 a 52.")
    if not 1 <= settimane <= 52:
        raise ErroreStrumento("«settimane» va da 1 a 52.")
    note = (note or "").strip() if isinstance(note, str) else ""
    if len(note) > 1000:
        raise ErroreStrumento("«note»: al massimo 1000 caratteri.")
    return s, settimane, note


def _settimane(n):
    return f"{n} settiman{'a' if n == 1 else 'e'}"


def anteprima_richiedi(contesto, team="", settimane=None, note=""):
    _controlla(contesto)
    s, settimane, note = _valida(team, settimane, note)
    d = squadre.descrivi(s)
    stima = squadre.stima(s["prezzo"], settimane)
    ricarico = squadre.decimale(s["prezzo"].get("llm_markup"))
    consumo = (f"a consumo, con ricarico del {squadre.numero((ricarico - 1) * 100)}%" if ricarico and ricarico > 1
               else "a consumo")
    credito = squadre.decimale(s["prezzo"].get("prepaid_credit_eur"))
    dettagli = [{"campo": "Agente", "dopo": d["nome_e_reparto"]},
                {"campo": "Ruoli", "dopo": ", ".join(m["nome"] for m in d["membri"]) or "—"},
                {"campo": "Durata", "dopo": _settimane(settimane)},
                {"campo": "Prezzo", "dopo": d["prezzo_testo"]},
                {"campo": "Costo fisso stimato", "dopo": f"{squadre.euro(stima)} €" if stima is not None else "—"},
                {"campo": "Consumo AI", "dopo": consumo + (f"; credito iniziale {squadre.euro(credito)} €"
                                                           if credito else "")},
                {"campo": "Prova", "dopo": f"{d['giorni_prova']} giorni di periodo di prova (gli agenti leggono, le "
                                           "modifiche si registrano senza eseguirle)" if d["giorni_prova"] else "—"},
                {"campo": "Cosa può fare", "dopo": "; ".join(d["operazioni_parole"]) or "—"}]
    if note:
        dettagli.append({"campo": "Note per Agentlia", "dopo": note})
    dettagli.append({"campo": "Poi", "dopo": " ".join(f"{n}. {p}" for n, p in enumerate(squadre.PASSI, 1))})
    return {"titolo": f"Chiedi ad Agentlia «{d['nome']}» per {_settimane(settimane)}",
            "dettagli": dettagli, "rischio": "scrittura", "url": reverse("awf:scheda", args=[s["slug"]]),
            "riepilogo": "Invia la richiesta ad Agentlia e prepara adabox (cosa può fare: letture e modifiche sì, "
                         "operazioni irreversibili con il tuo ok; si cambia da I miei agenti). Niente è attivo finché "
                         "una persona non conferma il contratto.",
            "impronta": {"team": s["slug"], "versione": s["versione"]}}


def richiedi_squadra(contesto, team="", settimane=None, note=""):
    _controlla(contesto)
    s, settimane, note = _valida(team, settimane, note)
    try:
        r = assunzione.invia(s["slug"], s["versione"], settimane, note, contesto.utente, contesto.azienda)
    except fabbrica.ErroreFabbrica as e:
        raise ErroreStrumento(f"Richiesta non inviata: {e}.")
    passi = " ".join(f"{n}. {p}" for n, p in enumerate(squadre.PASSI, 1))
    return {"esito": f"Richiesta inviata ad Agentlia: «{squadre.nome_pulito(r.team_nome)}» per {_settimane(settimane)}. "
                     f"Prossimi passi: {passi} Il contratto si segue in Agenti AI → Richieste (menu del profilo).",
            "url": reverse("awf:richieste")}


def stato_richieste_agenti(contesto):
    _controlla(contesto)
    errori = fabbrica.aggiorna_aperte(piu_vecchie_di=60)
    c = Collegamento.attuale()
    voci = [{"squadra": squadre.nome_pulito(r.team_nome) or r.team_slug, "settimane": r.settimane, "stato": r.get_stato_display(),
             "messaggio": r.messaggio, "creata": timezone.localtime(r.creata).strftime("%Y-%m-%d %H:%M"),
             **({"approva_in_agate": r.approve_url} if r.stato == RichiestaAgenti.DA_APPROVARE and r.approve_url
                else {}),
             "prossimo_passo": squadre.prossimo_passo(r, c)} for r in RichiestaAgenti.objects.all()[:20]]
    risposta = {"richieste": voci, "pagina": reverse("awf:richieste")}
    if not voci:
        risposta["nota"] = "Nessuna richiesta di agenti finora: il negozio si legge con catalogo_agenti."
    if errori:
        risposta["errori"] = errori
    return risposta


GUIDA = ("Prima di proporre una squadra chiedi all'utente il reparto, quanti record al giorno circa (lead, ticket, "
         "ordini...) e per quante settimane gli servono gli agenti.")
registra(Strumento(
    "catalogo_agenti", "Il negozio degli agenti AI in affitto di Agentic Workforce (Agentlia) che lavorano in adabox: "
                       "per reparto, cosa fanno, i ruoli, cosa possono fare, il prezzo e i giorni del periodo di "
                       f"prova. Usalo quando l'utente cerca agenti AI per un reparto. {GUIDA} Poi spiega l'agente "
                       "adatto in parole semplici; la scheda completa è in Agenti AI → Negozio.",
    {"type": "object", "properties": {
        "reparto": {"type": "string", "description": "facoltativo, es. crm, vendite, acquisti, helpdesk"}},
     "required": []}, catalogo_agenti, permesso=PERMESSO))
registra(Strumento(
    "richiedi_squadra", "Chiede ad Agentlia un agente (una squadra) del negozio (team = slug letto con "
                        f"catalogo_agenti) per un numero di settimane (1-52). {GUIDA} Metti nelle note il reparto e i "
                        "volumi. Spiega che il contratto lo prepara Agentlia e lo conferma una persona "
                        "dell'azienda (in Agenti AI → Richieste); poi adabox si collega da solo. Chi vuole scegliere "
                        "le cose che l'agente può fare usa «Assumi» in Agenti AI → Negozio. Non invia nulla: prepara una proposta che l'utente "
                        "conferma con un bottone.",
    {"type": "object", "properties": {
        "team": {"type": "string", "description": "slug della squadra, da catalogo_agenti"},
        "settimane": {"type": "integer", "description": "1-52"},
        "note": {"type": "string", "description": "per Agentlia: reparto, volumi (es. circa 10 opportunità al "
                                                  "giorno), esigenze; al massimo 1000 caratteri"}},
     "required": ["team", "settimane"]}, richiedi_squadra, rischio="scrittura", concorrente=False,
    anteprima=anteprima_richiedi, permesso=PERMESSO, timeout=60))
registra(Strumento(
    "stato_richieste_agenti", "Le richieste di agenti AI fatte da adabox ad Agentlia: stato (inviata, contratto da "
                              "approvare in Agate, collegata, rifiutata, ritirata), messaggio di Agentlia e prossimo "
                              "passo.",
    {"type": "object", "properties": {}, "required": []}, stato_richieste_agenti, concorrente=False,
    permesso=PERMESSO, timeout=60))
