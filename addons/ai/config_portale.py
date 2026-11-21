"""I provider «forniti con il piano» arrivano dal portale di chi vende l'istanza: fornitori, modelli, prezzi e chiave
si cambiano là una volta sola e ogni istanza si allinea da sé, ogni ora.

La risposta è firmata con le chiavi fidate dei moduli (come licenza e catalogo) e vale solo per questa istanza; la
chiave API viaggia cifrata con una chiave derivata dal token dell'istanza e qui si salva cifrata come tutte le altre.
Che cosa fa l'allineamento:
- crea o aggiorna i provider del portale (riconosciuti dal codice) e i loro modelli, segnati «forniti con il piano»;
- spegne, senza eliminarli, i provider e i modelli che il portale non manda più (i consumi restano leggibili);
- non tocca i provider aggiunti a mano, nemmeno quelli che il Global Admin ha segnato «forniti con il piano»;
- dà una riserva ai profili rimasti senza un modello utilizzabile: il modello «Veloce» del portale in fondo alla catena.
Con la chiave del cliente (formula «propria») il portale non manda provider: quelli ricevuti prima si spengono."""
import base64
import hashlib
import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction

from core import cifratura
from core.registry import pacchetti

from . import catalogo
from .models import AnelloCatena, Modello, Profilo, Provider

log = logging.getLogger("ai.limiti")
TIMEOUT = 30
TIPI = {t for t, _ in Provider.TIPI} - {Provider.FINTO}


class ConfigNonValida(ValueError):
    pass


def configurato():
    return bool(settings.LICENZA_PORTALE_URL and settings.LICENZA_TOKEN)


def _chiama():
    richiesta = urllib.request.Request(
        f"{settings.LICENZA_PORTALE_URL.rstrip('/')}/config-ai/", data=b"{}", method="POST",
        headers={"Authorization": f"Bearer {settings.LICENZA_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
        return json.loads(risposta.read())


def _decifra(testo):
    """La chiave API cifrata dal portale per questa istanza (rivendita.servizi._cifra_per)."""
    if not testo:
        return ""
    impronta = hashlib.sha256(settings.LICENZA_TOKEN.encode()).hexdigest()
    chiave = base64.urlsafe_b64encode(hashlib.sha256(f"adabox-config-ai:{impronta}".encode()).digest())
    try:
        return Fernet(chiave).decrypt(str(testo).encode()).decode()
    except (InvalidToken, ValueError) as e:
        raise ConfigNonValida("la chiave di un provider non è cifrata per questa istanza") from e


def verifica(dati):
    """La configurazione dentro la risposta del portale, se la firma è di una chiave fidata; altrimenti ConfigNonValida."""
    try:
        config, segno = dati["config"], dati["firma"]
    except (KeyError, TypeError) as e:
        raise ConfigNonValida("risposta non leggibile") from e
    if not isinstance(config, dict) or not isinstance(config.get("provider"), list):
        raise ConfigNonValida("risposta non leggibile")
    if pacchetti.verifica(pacchetti.serializza(config), segno, pacchetti.chiavi_fidate()) is None:
        raise ConfigNonValida("firma non valida o di una chiave non fidata")
    return config


def _prezzo(valore, facoltativo=False):
    if valore is None and facoltativo:
        return None
    try:
        prezzo = Decimal(str(valore))
    except InvalidOperation as e:
        raise ConfigNonValida("prezzo non leggibile") from e
    if not prezzo.is_finite() or prezzo < 0:
        raise ConfigNonValida("prezzo non valido")
    return prezzo


def _nome_libero(nome, provider):
    """Il nome del provider è unico: se un provider del cliente lo usa già, quello del piano prende «(piano)»."""
    altri = Provider.objects.exclude(pk=provider.pk)
    candidato, n = nome[:80], 1
    while altri.filter(nome=candidato).exists():
        n += 1
        candidato = f"{nome[:68]} (piano{'' if n == 2 else f' {n - 1}'})"
    return candidato


@transaction.atomic
def applica(config):
    """Allinea i provider arrivati dal portale. Restituisce (provider aggiornati, modelli aggiornati, provider spenti)."""
    visti, quanti_modelli = [], 0
    for voce in config["provider"]:
        if not isinstance(voce, dict) or not isinstance(voce.get("codice"), str) or not voce["codice"] or voce.get("tipo") not in TIPI:
            raise ConfigNonValida("provider non leggibile")
        provider = Provider.objects.filter(portale=voce["codice"][:40]).first() or Provider(portale=voce["codice"][:40])
        chiave = _decifra(voce.get("chiave"))
        provider.nome = _nome_libero(str(voce.get("nome") or voce["codice"]), provider)
        provider.tipo, provider.base_url, provider.gestito, provider.attivo = voce["tipo"], str(voce.get("base_url") or ""), True, True
        try:
            uguale = cifratura.decifra(provider.chiave_cifrata) == chiave
        except cifratura.SegretoIlleggibile:
            uguale = False
        if not uguale:
            provider.chiave_cifrata = cifratura.cifra(chiave)
        provider.save()
        visti.append(provider.pk)
        presenti = []
        for m in voce.get("modelli") if isinstance(voce.get("modelli"), list) else []:
            if not isinstance(m, dict) or not isinstance(m.get("id_api"), str) or not m["id_api"]:
                raise ConfigNonValida("modello non leggibile")
            modello = Modello.objects.filter(provider=provider, id_api=m["id_api"][:120]).first() or Modello(provider=provider, id_api=m["id_api"][:120])
            modello.etichetta = str(m.get("etichetta") or m["id_api"])[:80]
            for campo, predefinito in (("contesto", 200000), ("max_output", 8192)):
                valore = m.get(campo)
                setattr(modello, campo, valore if isinstance(valore, int) and not isinstance(valore, bool) and 0 < valore < 2_000_000_000 else predefinito)
            modello.prezzo_input, modello.prezzo_output = _prezzo(m.get("prezzo_input")), _prezzo(m.get("prezzo_output"))
            modello.prezzo_cache_scrittura = _prezzo(m.get("prezzo_cache_scrittura"), facoltativo=True)
            modello.prezzo_cache_lettura = _prezzo(m.get("prezzo_cache_lettura"), facoltativo=True)
            for campo in ("strumenti", "visione", "ragionamento", "residenza_ue"):
                setattr(modello, campo, m.get(campo) is True)
            livello = m.get("livello_chat")
            modello.livello_chat = livello if livello in (Modello.VELOCE, Modello.AVANZATO) else ""
            modello.attivo = True
            modello.save()                               # con un livello: sceglibile, e unico per quel livello
            presenti.append(modello.pk)
        quanti_modelli += len(presenti)
        Modello.objects.filter(provider=provider).exclude(pk__in=presenti).update(attivo=False, livello_chat="")
    spenti = Provider.objects.exclude(portale="").exclude(pk__in=visti).filter(attivo=True).update(attivo=False)
    _riserva_ai_profili(visti)
    return len(visti), quanti_modelli, spenti


def _riserva_ai_profili(provider_visti):
    """Un profilo senza nessun modello utilizzabile (es. quelli iniziali, su un provider senza chiave) riceve in fondo
    alla catena il modello «Veloce» arrivato dal portale: titoli, riassunti e pianificate funzionano da subito."""
    veloce = Modello.objects.filter(provider__in=provider_visti, livello_chat=Modello.VELOCE, attivo=True).first()
    if veloce is None:
        return
    for profilo in Profilo.objects.filter(attivo=True):
        try:
            catalogo.catena(profilo, profilo.azienda)
        except catalogo.NessunModello:
            ultimo = max(profilo.catena.values_list("ordine", flat=True), default=0)
            AnelloCatena.objects.create(profilo=profilo, modello=veloce, ordine=ultimo + 1)


def sincronizza():
    """Voce `cron` del manifest: l'esito in una riga, o None se non c'è un portale."""
    if not configurato():
        return None
    try:
        provider, modelli, spenti = applica(verifica(_chiama()))
    except (urllib.error.URLError, OSError, ValueError) as e:       # si riprova al prossimo giro: resta tutto com'è
        log.warning("provider AI del piano non allineati al portale: %s", e)
        return f"non allineati: {e}"
    return f"provider del piano: {provider}, modelli: {modelli}" + (f", spenti: {spenti}" if spenti else "")


sincronizza.senza_transazione = True      # una chiamata di rete: la transazione è solo in applica()
