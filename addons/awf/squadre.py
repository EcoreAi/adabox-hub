"""Le squadre del catalogo dette alle persone (vetrina, operazioni in parole, prezzo, stima del costo) e «cosa può
fare»: le operazioni ammesse a partire da quelle che una squadra chiede, con la scelta della persona per ciascuna
(Sì, Con il tuo ok, Mai).

Nel catalogo le operazioni sono `{"tool": "awf.modifica_record", "view": "crm.opportunita", "effect": "write",
"line": "..."}`: lo strumento senza il prefisso `awf.` (quello con cui Agate importa il server MCP del modulo) e la
vista sono una voce di «Operazioni ammesse»."""
import math
import re
from decimal import Decimal, InvalidOperation

from . import operazioni
from .models import Collegamento, OperazioneAmmessa, RichiestaAgenti

PREFISSO = "awf."
VERBI = {"crea_record": "Creare", "modifica_record": "Modificare", "elimina_record": "Eliminare",
         "esegui_bottone": "Eseguire azioni", "esegui_azione": "Eseguire azioni",
         "pianifica_attivita": "Pianificare attività"}
EFFETTI = {"read": "Leggere", "write": "Modificare", "irreversible": "Operazioni irreversibili"}
REPARTI = {"crm": "CRM", "vendite": "Vendite", "acquisti": "Acquisti", "magazzino": "Magazzino",
           "helpdesk": "Assistenza clienti", "assistenza": "Assistenza clienti", "amministrazione": "Amministrazione",
           "contabilita": "Contabilità", "progetti": "Progetti", "personale": "Personale", "marketing": "Marketing"}
AMMESSA, DA_AMMETTERE, NON_DISPONIBILE = "ammessa", "da_ammettere", "non_disponibile"
SI, OK, MAI = RichiestaAgenti.SI, RichiestaAgenti.OK, RichiestaAgenti.MAI
GRAVITA = {"read": 0, "write": 1, "irreversible": 2}
PASSI = ["adabox si prepara da solo con quello che è stato scelto in «Cosa può fare» (se il Controllo AI non è ancora "
         "collegato serve un passaggio, una volta sola).",
         "Agentlia prepara il contratto: agenti, tetti di spesa e giorni di prova.",
         "Una persona dell'azienda conferma il contratto in adabox con la sua password (Agenti AI → Richieste); se è "
         "quello già confermato, parte da solo a suo nome.",
         "adabox si collega da solo e gli agenti iniziano con il periodo di prova: leggono, e le modifiche si "
         "registrano senza eseguirle."]


def decimale(valore):
    if valore in (None, "") or isinstance(valore, bool):
        return None
    try:
        d = Decimal(str(valore))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def numero(d):
    """1.50 → «1,5»; 150 → «150»."""
    testo = f"{d:.2f}".rstrip("0").rstrip(".")
    return testo.replace(".", ",")


def euro(d):
    """150 → «150»; 12.5 → «12,50»."""
    return f"{d:.0f}" if d == d.to_integral_value() else f"{d:.2f}".replace(".", ",")


SUFFISSO_RE = re.compile(r"\s*\(adabox(-hub)?\)\s*$", re.IGNORECASE)


def nome_pulito(nome):
    """«Lead e CRM (adabox-hub)» → «Lead e CRM»: dentro adabox il nome del gestionale non serve."""
    return SUFFISSO_RE.sub("", nome or "").strip()


def reparto_se_serve(nome, reparto_nome):
    """Il reparto da mostrare accanto al nome, o "" se il nome lo dice già («Lead e CRM» e «CRM»)."""
    return "" if reparto_nome and reparto_nome.lower() in (nome or "").lower() else reparto_nome


def nome_reparto(reparto):
    return REPARTI.get(reparto) or (reparto[:1].upper() + reparto[1:] if reparto else "Altro")


def nome_strumento(tool):
    return tool[len(PREFISSO):] if tool.startswith(PREFISSO) else tool


def _etichetta(vista):
    testo = str(vista.verbose_name_plural or vista.verbose_name)
    return testo[:1].upper() + testo[1:]


def in_parole(op, tutte=None):
    """«Modificare: Opportunità — Cambia priorità e probabilità», con il nome della vista di adabox."""
    tutte = operazioni.viste() if tutte is None else tutte
    nome = nome_strumento(op["tool"])
    verbo = "Leggere" if op["effect"] == "read" else VERBI.get(nome) or EFFETTI.get(op["effect"], "Usare")
    vista = op.get("view") or ""
    dove = _etichetta(tutte[vista]) if vista in tutte else f"{vista} (app non installata)" if vista else \
        "le viste concesse"
    testo = f"{verbo}: {dove}" + (" (irreversibile)" if op["effect"] == "irreversible" else "")
    return f"{testo} — {op['line']}" if op.get("line") else testo


def prezzo(p):
    """«150 € ogni 7 giorni + consumo AI (ricarico 40%) · credito iniziale 30 €»."""
    parti = []
    periodo, giorni = decimale(p.get("period_eur")), decimale(p.get("period_days"))
    if periodo and giorni:
        parti.append(f"{euro(periodo)} € ogni {numero(giorni)} giorni")
    compito = decimale(p.get("task_eur"))
    if compito:
        parti.append(f"{euro(compito)} € a compito")
    ricarico = decimale(p.get("llm_markup"))
    if ricarico is not None:
        percento = (ricarico - 1) * 100
        parti.append(f"consumo AI (ricarico {numero(percento)}%)" if percento > 0 else "consumo AI al costo")
    testo = " + ".join(parti) or "prezzo da concordare con Agentlia"
    credito = decimale(p.get("prepaid_credit_eur"))
    return f"{testo} · credito iniziale {euro(credito)} €" if credito else testo


def settimanale(p):
    """Il prezzo fisso di una settimana (period_eur × 7 / period_days), per la vetrina. None se non c'è."""
    periodo, giorni = decimale(p.get("period_eur")), decimale(p.get("period_days"))
    if not periodo or not giorni or giorni <= 0:
        return None
    return (periodo * 7 / giorni).quantize(Decimal("0.01"))


def stima(p, settimane):
    """Il costo fisso stimato: prezzo del periodo × periodi necessari a coprire le settimane. None se non c'è."""
    periodo, giorni = decimale(p.get("period_eur")), decimale(p.get("period_days"))
    if not periodo or not giorni or giorni <= 0:
        return None
    return periodo * math.ceil(Decimal(settimane * 7) / giorni)


def descrivi(squadra, tutte=None):
    """La squadra pronta per le pagine: reparto, operazioni in parole, prezzo e la vetrina (quella della fabbrica,
    completata con descrizione e ruoli quando manca qualcosa)."""
    tutte = operazioni.viste() if tutte is None else tutte
    v = squadra.get("vetrina") or {}
    frasi = [f.strip() for f in squadra["descrizione"].replace("\n", " ").split(". ") if f.strip()]
    vantaggi = v.get("vantaggi") or [f"{m['nome']}: {m['descrizione']}" if m["descrizione"] else m["nome"]
                                     for m in squadra["membri"]]
    settimana = settimanale(squadra["prezzo"])
    nome = nome_pulito(squadra["nome"]) or squadra["slug"]
    reparto = nome_reparto(squadra["reparto"])
    extra = reparto_se_serve(nome, reparto)
    return {**squadra, "nome": nome, "reparto_nome": reparto, "reparto_extra": extra,
            "nome_e_reparto": f"{nome} ({extra})" if extra else nome, "prezzo_testo": prezzo(squadra["prezzo"]),
            "operazioni_parole": list(dict.fromkeys(in_parole(o, tutte) for o in squadra["operazioni"])),
            "icona": v.get("icona", ""), "slogan": v.get("slogan") or (frasi[0].rstrip(".") if frasi else ""),
            "vantaggi": vantaggi, "giornata": v.get("giornata") or [], "mai": v.get("mai") or [],
            "domande": v.get("domande") or [], "settimana": euro(settimana) if settimana is not None else ""}


def per_reparto(squadre):
    """[(nome del reparto, [squadre descritte])], in ordine di reparto."""
    tutte = operazioni.viste()
    gruppi = {}
    for s in squadre:
        gruppi.setdefault(s["reparto"], []).append(descrivi(s, tutte))
    return [(nome_reparto(r), gruppi[r]) for r in sorted(gruppi, key=nome_reparto)]


def compatta(squadra, tutte=None):
    """La squadra per l'assistente AI: poche chiavi, in parole."""
    from django.urls import reverse
    d = descrivi(squadra, tutte)
    return {"slug": d["slug"], "nome": d["nome"], "reparto": d["reparto"], "in_breve": d["slogan"],
            "cosa_fa": d["descrizione"], "per_te": d["vantaggi"][:5],
            "ruoli": [{"nome": m["nome"], "cosa_fa": m["descrizione"]} for m in d["membri"]],
            "cosa_puo_fare": d["operazioni_parole"], "non_fara_mai": d["mai"], "prezzo": d["prezzo_testo"],
            "giorni_di_prova": d["giorni_prova"], "scheda": reverse("awf:scheda", args=[d["slug"]])}


def prossimo_passo(r, collegamento=None):
    """Cosa succede ora, in una frase, per la persona."""
    collegamento = collegamento or Collegamento.attuale()
    tecnico = "un passaggio tecnico, una volta sola (in Agenti AI → Richieste)"
    if r.stato == RichiestaAgenti.INVIATA:
        if not collegamento.mcp_impronta:
            return f"Agentlia sta preparando il contratto. Intanto serve {tecnico}."
        return ("Agentlia sta preparando il contratto: quando è pronto lo vedi qui. Finché è così puoi ritirare la "
                "richiesta.")
    if r.stato == RichiestaAgenti.DA_APPROVARE:
        if not collegamento.mcp_impronta:
            return f"Il contratto è pronto: prima serve {tecnico}, poi lo confermi."
        if r.decisione == RichiestaAgenti.APPROVATA:
            return "Contratto confermato: stiamo collegando l'agente."
        if r.decisione == RichiestaAgenti.IN_CONFERMA:
            return ("Abbiamo mandato un'email di conferma ai responsabili: il contratto parte appena "
                    "confermano.")
        if r.decisione == RichiestaAgenti.DA_CONFERMARE:
            return "Il contratto proposto è diverso da quello che hai confermato: rivedilo e confermalo."
        if r.decisione == RichiestaAgenti.RIFIUTATA_QUI:
            return "Contratto rifiutato in adabox."
        return "Il contratto è pronto: confermalo e gli agenti iniziano."
    if r.stato == RichiestaAgenti.COLLEGATA and r.collegata_il:
        if not collegamento.mcp_impronta:
            return f"Contratto confermato: manca solo {tecnico}."
        return "Contratto attivo: trovi gli agenti in Agenti AI → I miei agenti."
    return r.messaggio or r.get_stato_display()


def nome_persona(u):
    return (u.get_full_name() or u.get_username()) if u is not None else ""


def riga_persone(reparto="", responsabile=None, persone=()):
    """La riga per Agentlia su per chi lavorano gli agenti: reparto, responsabile, persone (solo i nomi)."""
    parti = [f"reparto {reparto}" if reparto else "",
             f"responsabile {nome_persona(responsabile)}" if responsabile is not None else "",
             ("passa il lavoro a " + ", ".join(nome_persona(p) for p in persone)) if persone else ""]
    parti = [p for p in parti if p]
    return f"Lavora per: {'; '.join(parti)}."[:290] if parti else ""


# ---------- cosa può fare: operazioni ammesse dalla squadra, con la scelta della persona ----------

def _app(vista):
    """Il nome dell'app di una vista che qui non c'è (es. «crm.opportunita» → «CRM»), per dirlo alla persona."""
    from core.registry.modules import scopri
    slug = vista.split(".", 1)[0]
    info = scopri().get(slug)
    return info.manifest.name if info is not None and info.manifest is not None else slug


def righe_operazioni(ops):
    """Per ogni operazione che la squadra chiede: in parole, (strumento, vista), l'effetto (il più grave fra quello
    del catalogo e quello dello strumento qui), se è già ammessa, da ammettere o non disponibile qui (strumento non
    ammissibile, vista di un'app non installata) e la scelta proposta: letture sì, modifiche sì, irreversibili con
    il tuo ok."""
    esponibili, tutte = operazioni.esponibili(), operazioni.viste()
    presenti = {(o.strumento, o.vista): o.attiva for o in OperazioneAmmessa.objects.all()}
    righe, viste = [], set()
    for op in ops or []:
        if not isinstance(op, dict) or not isinstance(op.get("tool"), str):
            continue
        strumento, vista = nome_strumento(op["tool"]), op.get("view") or ""
        if (strumento, vista) in viste:
            continue
        viste.add((strumento, vista))
        s = esponibili.get(strumento)
        effetto = op.get("effect") if op.get("effect") in GRAVITA else "irreversible"
        if s is not None and GRAVITA.get(operazioni.EFFETTO.get(s.rischio), 2) > GRAVITA[effetto]:
            effetto = operazioni.EFFETTO.get(s.rischio, "irreversible")
        mancante = bool(vista) and vista not in tutte
        if s is None or (vista and (not operazioni.ha_vista(s) or mancante)):
            stato = NON_DISPONIBILE
        else:
            stato = AMMESSA if presenti.get((strumento, vista)) else DA_AMMETTERE
        righe.append({"parole": in_parole({**op, "effect": effetto}, tutte), "strumento": strumento, "vista": vista,
                      "chiave": f"{strumento}|{vista}", "effetto": effetto, "lettura": effetto == "read",
                      "stato": stato, "esiste": (strumento, vista) in presenti,
                      "attiva": bool(presenti.get((strumento, vista))),
                      "app_mancante": _app(vista) if mancante else "",
                      "proposta": OK if effetto == "irreversible" else SI})
    return righe


def stato_operazioni(richiesta):
    return righe_operazioni(richiesta.operazioni)


def scelte(righe, dati=None):
    """Le scelte per ogni riga: quelle date (se valide), altrimenti la proposta. Le letture sono sempre «Sì»: senza,
    l'agente non può lavorare."""
    dati = dati or {}
    return {x["chiave"]: SI if x["lettura"] else dati[x["chiave"]] if dati.get(x["chiave"]) in (SI, OK, MAI)
            else x["proposta"] for x in righe}


def scelte_attuali(righe):
    """Le scelte ricavate dall'elenco delle operazioni ammesse (per le richieste fatte senza la procedura guidata)."""
    return scelte(righe, {x["chiave"]: (x["proposta"] if x["attiva"] else MAI) for x in righe})


def applica(righe, scelte_fatte, utente=None):
    """«Sì» e «Con il tuo ok» ammettono l'operazione (creata o riaccesa), «Mai» la spegne; poi riallinea i permessi
    degli agenti. Le operazioni non disponibili qui restano fuori. Restituisce (ammesse ora, spente ora)."""
    voluto = scelte(righe, scelte_fatte)
    nuove, spente = [], []
    for x in righe:
        if x["stato"] == NON_DISPONIBILE:
            continue
        if voluto[x["chiave"]] == MAI:
            if x["attiva"]:
                OperazioneAmmessa.objects.filter(strumento=x["strumento"], vista=x["vista"]).update(attiva=False)
                spente.append(x)
        elif not x["attiva"]:
            if x["esiste"]:
                OperazioneAmmessa.objects.filter(strumento=x["strumento"], vista=x["vista"]).update(attiva=True)
            else:
                OperazioneAmmessa.objects.create(strumento=x["strumento"], vista=x["vista"], creato_da=utente)
            nuove.append(x)
    operazioni.allinea_gruppo()
    return nuove, spente


def ammetti(richiesta, utente=None):
    """Ammette le operazioni della richiesta secondo le sue scelte (senza scelte: quelle proposte, cioè tutte).
    Restituisce le righe di `stato_operazioni` com'erano prima, per dire cosa è cambiato."""
    righe = stato_operazioni(richiesta)
    applica(righe, richiesta.scelte, utente)
    return righe


def viste_lette(ops):
    """I nomi delle viste di adabox che la squadra vede (quelle su cui ha almeno un'operazione)."""
    tutte = operazioni.viste()
    return list(dict.fromkeys(_etichetta(tutte[o["view"]]) for o in ops or []
                              if isinstance(o, dict) and o.get("view") in tutte))


def app_mancanti(righe):
    return list(dict.fromkeys(x["app_mancante"] for x in righe if x["app_mancante"]))
