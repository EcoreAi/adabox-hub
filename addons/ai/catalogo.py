"""Catalogo dei modelli: quale profilo vale per un compito, la catena dei modelli utilizzabili, i dati iniziali."""
from decimal import Decimal

from .models import AnelloCatena, Modello, Profilo, Provider


class NessunModello(LookupError):
    pass


def profilo_per(compito, azienda=None, app=""):
    """Il profilo più specifico: azienda e app, poi app, poi azienda, poi generale; senza, quello della chat."""
    azienda_id = getattr(azienda, "pk", None)
    candidati = [p for p in Profilo.objects.filter(attivo=True, compito=compito)
                 if (not p.azienda_id or p.azienda_id == azienda_id) and (not p.app or p.app == app)]
    if not candidati:
        if compito != "chat":
            return profilo_per("chat", azienda, app)
        raise NessunModello("Nessun profilo attivo per la chat: configura l'assistente.")
    return max(candidati, key=lambda p: (bool(p.azienda_id) and bool(p.app), bool(p.app), bool(p.azienda_id)))


def catena(profilo, azienda=None):
    """[(modello, chiave)] utilizzabili, in ordine: provider attivo e chiave presente (se serve)."""
    risultato = []
    for anello in AnelloCatena.objects.filter(profilo=profilo, modello__attivo=True,
                                              modello__provider__attivo=True).select_related("modello__provider"):
        provider = anello.modello.provider
        chiave = provider.chiave_per(azienda)
        if provider.tipo == Provider.ANTHROPIC and not chiave:
            continue
        risultato.append((anello.modello, chiave))
    if not risultato:
        raise NessunModello(f"Nessun modello utilizzabile per «{profilo}»: manca la chiave API o sono tutti spenti.")
    return risultato


# Prezzi e limiti dal riferimento ufficiale Anthropic (ottobre 2026); si modificano dal catalogo.
MODELLI_INIZIALI = [
    ("claude-haiku-5-5", "Claude Haiku 5.5", "0.10", "0.50", "0.125", "0.01"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "2.00", "10.00", "2.50", "0.20"),
    ("claude-opus-5-5", "Claude Opus 5.5", "4.00", "20.00", "5.00", "0.20"),
]


def crea_iniziali():
    """Provider Anthropic (senza chiave), i tre modelli Claude 5.5, Ollama spento e i profili di partenza.
    Non tocca niente se il catalogo ha già dei provider."""
    if Provider.objects.exists():
        return False
    anthropic = Provider.objects.create(nome="Anthropic", tipo=Provider.ANTHROPIC)
    modelli = {}
    for id_api, etichetta, pin, pout, pcs, pcl in MODELLI_INIZIALI:
        modelli[id_api] = Modello.objects.create(
            provider=anthropic, id_api=id_api, etichetta=etichetta, contesto=1_000_000, max_output=128_000,
            prezzo_input=Decimal(pin), prezzo_output=Decimal(pout), prezzo_cache_scrittura=Decimal(pcs),
            prezzo_cache_lettura=Decimal(pcl), visione=True, ragionamento=True)
    ollama = Provider.objects.create(nome="Ollama locale", tipo=Provider.OPENAI_COMPAT,
                                     base_url="http://ollama:11434/v1", locale=True, attivo=False)
    Modello.objects.create(provider=ollama, id_api="qwen3:4b", etichetta="Qwen3 4B (locale)", contesto=32768,
                           max_output=4096, prezzo_input=0, prezzo_output=0)
    for nome, compito, effort, catena_ids in [
            ("Chat", "chat", "low", ["claude-haiku-5-5", "claude-sonnet-5-5"]),
            ("Titoli", "titoli", "low", ["claude-haiku-5-5"]),
            ("Riassunti", "riassunti", "low", ["claude-haiku-5-5"]),
            ("Attività pianificate", "pianificate", "low", ["claude-haiku-5-5"]),
            ("Classificazione", "classificazione", "low", ["claude-haiku-5-5"])]:
        profilo = Profilo.objects.create(nome=nome, compito=compito, effort=effort,
                                         max_token=16000 if compito in ("chat", "pianificate") else 1024)
        for i, id_api in enumerate(catena_ids, start=1):
            AnelloCatena.objects.create(profilo=profilo, modello=modelli[id_api], ordine=i)
    return True
