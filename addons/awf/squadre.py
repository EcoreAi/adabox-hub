"""Le squadre del catalogo dette alle persone (operazioni in parole, prezzo, stima del costo) e le operazioni ammesse
con un clic a partire da quelle che una squadra chiede.

Nel catalogo le operazioni sono `{"tool": "awf.modifica_record", "view": "crm.opportunita", "effect": "write",
"line": "..."}`: lo strumento senza il prefisso `awf.` (quello con cui Agate importa il server MCP del modulo) e la
vista sono una voce di «Operazioni ammesse»."""
import math
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
PASSI = ["Subito, in Agenti → Richieste: ammetti le operazioni della squadra e collega adabox in Agate (Agate accetta "
         "il contratto solo se gli strumenti della squadra sono già attivi).",
         "Agentlia prepara il contratto con la squadra, i tetti di spesa e i giorni di prova.",
         "Una persona dell'azienda lo approva nella console di Agate.",
         "adabox si collega da solo alla fabbrica e gli agenti iniziano, prima in osservazione."]


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


def stima(p, settimane):
    """Il costo fisso stimato: prezzo del periodo × periodi necessari a coprire le settimane. None se non c'è."""
    periodo, giorni = decimale(p.get("period_eur")), decimale(p.get("period_days"))
    if not periodo or not giorni or giorni <= 0:
        return None
    return periodo * math.ceil(Decimal(settimane * 7) / giorni)


def descrivi(squadra, tutte=None):
    """La squadra pronta per le pagine: reparto, operazioni in parole, prezzo."""
    tutte = operazioni.viste() if tutte is None else tutte
    return {**squadra, "reparto_nome": nome_reparto(squadra["reparto"]), "prezzo_testo": prezzo(squadra["prezzo"]),
            "operazioni_parole": list(dict.fromkeys(in_parole(o, tutte) for o in squadra["operazioni"]))}


def per_reparto(squadre):
    """[(nome del reparto, [squadre descritte])], in ordine di reparto."""
    tutte = operazioni.viste()
    gruppi = {}
    for s in squadre:
        gruppi.setdefault(s["reparto"], []).append(descrivi(s, tutte))
    return [(nome_reparto(r), gruppi[r]) for r in sorted(gruppi, key=nome_reparto)]


def compatta(squadra, tutte=None):
    """La squadra per l'assistente AI: poche chiavi, in parole."""
    d = descrivi(squadra, tutte)
    return {"slug": d["slug"], "nome": d["nome"], "reparto": d["reparto"], "cosa_fa": d["descrizione"],
            "ruoli": [{"nome": m["nome"], "cosa_fa": m["descrizione"]} for m in d["membri"]],
            "operazioni": d["operazioni_parole"], "prezzo": d["prezzo_testo"], "giorni_di_prova": d["giorni_prova"]}


def prossimo_passo(r, collegamento=None):
    """Cosa succede ora, in una frase, per la persona."""
    if r.stato == RichiestaAgenti.INVIATA:
        collegamento = collegamento or Collegamento.attuale()
        if not collegamento.mcp_impronta:
            return ("Prepara adabox per la squadra (i due passi qui sotto): Agate accetta il contratto solo se gli "
                    "strumenti della squadra sono già attivi. Intanto Agentlia prepara il contratto.")
        return "Agentlia sta preparando il contratto; finché è così la richiesta si può ritirare da Agenti → Richieste."
    if r.stato == RichiestaAgenti.DA_APPROVARE:
        return "Una persona dell'azienda deve approvare il contratto nella console di Agate."
    if r.stato == RichiestaAgenti.COLLEGATA and r.collegata_il:
        collegamento = collegamento or Collegamento.attuale()
        if not collegamento.mcp_impronta:
            return ("adabox è collegato: in Agenti → Richieste ammetti le operazioni della squadra e collega adabox "
                    "in Agate (indirizzo e bearer del server MCP, da copiare subito).")
        return "Collegata: gli agenti lavorano attraverso Agate; lo stato è in Agenti → Stato e collegamento."
    return r.messaggio or r.get_stato_display()


# ---------- operazioni ammesse dalla squadra ----------

def stato_operazioni(richiesta):
    """Per ogni operazione che la squadra chiede: in parole, (strumento, vista) e se è già ammessa, da ammettere o
    non disponibile qui (strumento non ammissibile, vista inesistente)."""
    esponibili, tutte = operazioni.esponibili(), operazioni.viste()
    presenti = {(o.strumento, o.vista): o.attiva for o in OperazioneAmmessa.objects.all()}
    righe, viste = [], set()
    for op in richiesta.operazioni or []:
        if not isinstance(op, dict) or not isinstance(op.get("tool"), str):
            continue
        strumento, vista = nome_strumento(op["tool"]), op.get("view") or ""
        if (strumento, vista) in viste:
            continue
        viste.add((strumento, vista))
        s = esponibili.get(strumento)
        if s is None or (vista and (not operazioni.ha_vista(s) or vista not in tutte)):
            stato = NON_DISPONIBILE
        else:
            stato = AMMESSA if presenti.get((strumento, vista)) else DA_AMMETTERE
        righe.append({"parole": in_parole({"effect": "irreversible", **op}, tutte), "strumento": strumento,
                      "vista": vista, "stato": stato, "esiste": (strumento, vista) in presenti})
    return righe


def ammetti(richiesta, utente=None):
    """Un clic: crea le voci che la squadra chiede (e riaccende quelle spente), poi riallinea il gruppo degli agenti.
    Restituisce le righe di `stato_operazioni` com'erano prima, per dire cosa è cambiato."""
    righe = stato_operazioni(richiesta)
    da_fare = [x for x in righe if x["stato"] == DA_AMMETTERE]
    OperazioneAmmessa.objects.bulk_create([OperazioneAmmessa(strumento=x["strumento"], vista=x["vista"],
                                                             creato_da=utente) for x in da_fare if not x["esiste"]])
    for x in da_fare:
        if x["esiste"]:
            OperazioneAmmessa.objects.filter(strumento=x["strumento"], vista=x["vista"]).update(attiva=True)
    operazioni.allinea_gruppo()
    return righe
