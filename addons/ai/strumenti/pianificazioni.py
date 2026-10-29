"""Strumenti per le attività pianificate dell'assistente: crearle dalla chat (con conferma) ed elencarle."""
import datetime

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .registro import ErroreStrumento, Strumento, registra

NOMI_GIORNI = {"lun": 0, "mar": 1, "mer": 2, "gio": 3, "ven": 4, "sab": 5, "dom": 6}
RIEPILOGO_MATTINO = {
    "nome": "Riepilogo del mattino",
    "istruzioni": "Prepara il mio riepilogo della giornata: attività scadute e di oggi, appuntamenti di oggi, "
                  "scadenze dei prossimi 3 giorni e, se ci sono le app, ticket urgenti e opportunità in chiusura. "
                  "Elenchi brevi, con i link ai record; in fondo le 3 cose da fare per prime.",
    "quando": "giorni", "alle": "08:00", "giorni": [0, 1, 2, 3, 4],
}


def _giorni(valore):
    """[0..6] da una lista di numeri o di nomi (lun, martedì...)."""
    if valore in (None, "", []):
        return []
    elementi = valore if isinstance(valore, list) else str(valore).replace(";", ",").split(",")
    giorni = set()
    for e in elementi:
        testo = str(e).strip().lower()
        if testo.isdigit() and 0 <= int(testo) <= 6:
            giorni.add(int(testo))
        elif testo[:3] in NOMI_GIORNI:
            giorni.add(NOMI_GIORNI[testo[:3]])
        else:
            raise ErroreStrumento(f"Giorno «{e}» non valido: usa 0-6 (0 = lunedì) o il nome del giorno.")
    return sorted(giorni)


def _intero(valore, nome, minimo, massimo):
    if valore in (None, ""):
        return None
    try:
        n = int(valore)
    except (TypeError, ValueError):
        raise ErroreStrumento(f"«{nome}» è un numero intero.")
    if not minimo <= n <= massimo:
        raise ErroreStrumento(f"«{nome}» va da {minimo} a {massimo}.")
    return n


def costruisci(contesto, nome="", istruzioni="", quando="giorni", alle="", giorni=None, giorno_mese=None,
               ogni_ore=None, minuti_prima=None, in_discuss=True, per_email=False, app=None, preset=""):
    """La pianificazione (non salvata) dagli argomenti dello strumento, validati."""
    from core.registry import modules

    from ..models import Pianificata
    from ..pianificate import calcola_prossima
    if preset:
        if preset != "riepilogo_mattino":
            raise ErroreStrumento("«preset» ammesso: riepilogo_mattino.")
        base = RIEPILOGO_MATTINO
        nome, istruzioni, alle = nome or base["nome"], istruzioni or base["istruzioni"], alle or base["alle"]
        if not giorni:
            quando, giorni = base["quando"], base["giorni"]
    if not (nome or "").strip() or not (istruzioni or "").strip():
        raise ErroreStrumento("Servono un nome breve e le istruzioni (cosa deve fare l'assistente).")
    if quando not in dict(Pianificata.RICORRENZE):
        raise ErroreStrumento(f"«quando» è uno tra: {', '.join(dict(Pianificata.RICORRENZE))}.")
    ora = None
    if alle:
        try:
            ora = datetime.time.fromisoformat(alle)
        except ValueError:
            raise ErroreStrumento("«alle» è un'ora HH:MM.")
    ambito = getattr(contesto.conversazione, "ambito", "") if app is None else (app or "")
    if ambito and ambito not in {a["slug"] for a in modules.app_visibili(contesto.utente)}:
        raise ErroreStrumento(f"App «{ambito}» inesistente o non accessibile.")
    if quando == Pianificata.EVENTI and "calendario" not in settings.ADDONS_ATTIVI:
        raise ErroreStrumento("«Prima degli eventi» richiede l'app calendario.")
    elenco = _giorni(giorni)
    if quando == Pianificata.GIORNI and not elenco:
        elenco = list(range(7))
    p = Pianificata(utente=contesto.utente, azienda=contesto.azienda, nome=nome.strip()[:120],
                    istruzioni=istruzioni.strip(), ambito=ambito, ricorrenza=quando, alle=ora,
                    giorni=",".join(map(str, elenco)), giorno_mese=_intero(giorno_mese, "giorno_mese", 1, 28),
                    ogni_ore=_intero(ogni_ore, "ogni_ore", 1, 168),
                    minuti_prima=_intero(minuti_prima, "minuti_prima", 5, 1440),
                    in_discuss=bool(in_discuss), per_email=bool(per_email))
    p.prossima = calcola_prossima(p)
    return p


def _consegna(p):
    voci = ["nella sua chat"]
    if p.in_discuss and "discuss" in settings.ADDONS_ATTIVI:
        voci.append("in Discuss")
    if p.per_email:
        voci.append("per email" if p.utente.email else "per email (manca l'indirizzo nel profilo)")
    return ", ".join(voci)


def anteprima_crea(contesto, **argomenti):
    p = costruisci(contesto, **argomenti)
    dettagli = [{"campo": "Nome", "dopo": p.nome}, {"campo": "Istruzioni", "dopo": p.istruzioni},
                {"campo": "Quando", "dopo": p.frequenza()}]
    if p.ricorrenza != p.EVENTI:
        dettagli.append({"campo": "Prima esecuzione", "dopo": f"{timezone.localtime(p.prossima):%d/%m/%Y %H:%M}"})
    dettagli += [{"campo": "Risultato", "dopo": _consegna(p)}, {"campo": "App", "dopo": p.ambito or "tutte"}]
    return {"titolo": f"Pianifica «{p.nome}» {p.frequenza()}", "dettagli": dettagli}


def crea_pianificata(contesto, **argomenti):
    p = costruisci(contesto, **argomenti)
    p.save()
    return {"esito": f"Attività pianificata «{p.nome}» creata: {p.frequenza()}.",
            "url": reverse("ai:pianificate_dettaglio", args=[p.pk])}


def elenco_pianificate(contesto):
    from ..models import Pianificata
    voci = Pianificata.objects.filter(utente=contesto.utente).order_by("nome")
    if not voci:
        return "Nessuna attività pianificata."
    return [{"id": p.pk, "nome": p.nome, "quando": p.frequenza(), "attiva": p.attiva,
             "prossima": timezone.localtime(p.prossima).strftime("%Y-%m-%d %H:%M") if p.prossima else None,
             "ultimo_esito": p.esito, "url": reverse("ai:pianificate_dettaglio", args=[p.pk])} for p in voci]


registra(Strumento(
    "crea_pianificata", "Crea un'attività che l'assistente esegue da solo a intervalli regolari o prima degli eventi del "
                        "calendario, con i permessi dell'utente (es. «ogni lunedì alle 8 mandami gli ordini aperti»). "
                        "Il risultato arriva nella sua chat e, se scelto, in Discuss o per email. Con "
                        "preset=riepilogo_mattino prepara il riepilogo della giornata (lun-ven alle 8). Non crea "
                        "nulla: prepara una proposta che l'utente conferma con un bottone.",
    {"type": "object", "properties": {
        "nome": {"type": "string", "description": "nome breve, es. Ordini aperti del lunedì"},
        "istruzioni": {"type": "string", "description": "cosa fare a ogni esecuzione, come la chiederebbe l'utente"},
        "quando": {"type": "string", "enum": ["giorni", "mese", "ore", "eventi"],
                   "description": "giorni = nei giorni della settimana indicati; mese = un giorno del mese; "
                                  "ore = ogni N ore; eventi = prima di ogni evento del calendario"},
        "alle": {"type": "string", "description": "HH:MM (per giorni e mese; default 08:00)"},
        "giorni": {"type": "array", "items": {"type": "integer"}, "description": "0 = lunedì … 6 = domenica"},
        "giorno_mese": {"type": "integer", "description": "1-28"},
        "ogni_ore": {"type": "integer", "description": "1-168"},
        "minuti_prima": {"type": "integer", "description": "per eventi: quanti minuti prima (default 30)"},
        "in_discuss": {"type": "boolean", "description": "anche come messaggio in Discuss (default sì)"},
        "per_email": {"type": "boolean", "description": "anche per email (default no)"},
        "app": {"type": "string", "description": "limita a un'app (slug); default quella della chat"},
        "preset": {"type": "string", "enum": ["riepilogo_mattino"]}},
     "required": []}, crea_pianificata, rischio="scrittura", concorrente=False, anteprima=anteprima_crea,
    permesso="ai.add_pianificata"))
registra(Strumento(
    "elenco_pianificate", "Le attività pianificate dell'utente, con la frequenza, la prossima esecuzione e l'ultimo "
                          "esito.", {"type": "object", "properties": {}, "required": []}, elenco_pianificate,
    permesso="ai.view_pianificata"))
