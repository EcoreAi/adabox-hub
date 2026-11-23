"""Modelli delle email: i moduli dichiarano i testi nel manifest (`email`), l'azienda li personalizza senza codice.

I segnaposto {{ campo }} si sostituiscono in un solo passaggio con un'espressione regolare, mai con il motore dei
template: un testo scritto da un utente non può eseguire nulla, e un valore che contiene {{ x }} resta com'è.
La versione HTML è il testo già riempito, con l'escape di tutto: nessun valore può portare markup nella mail."""
import re
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import escape

from .models import Azienda, ModelloEmail
from .registry import modules

SEGNAPOSTO = re.compile(r"\{\{\s*(\w+)\s*\}\}")
URL = re.compile(r"https?://[^\s<>\"']+")
CAMPI_SEMPRE = {"azienda": ["Nome dell'azienda", "La tua azienda"], "marchio": ["Nome dell'applicazione", "adabox"],
                "sito": ["Indirizzo dell'applicazione", "https://hub.example.it"]}


def definizioni():
    """{codice: voce del manifest con "modulo" e i campi sempre disponibili} per i moduli attivi."""
    return {v["codice"]: {**v, "modulo": slug, "campi": {**CAMPI_SEMPRE, **v.get("campi", {})}}
            for slug, m in modules.manifests_attivi().items() for v in m.email}


def personalizzato(codice, azienda):
    return ModelloEmail.objects.filter(azienda=azienda, codice=codice).first()


def testo_di(codice, azienda):
    """(oggetto, corpo): quelli dell'azienda se li ha scritti, altrimenti quelli del modulo."""
    proprio = personalizzato(codice, azienda)
    if proprio is not None:
        return proprio.oggetto, proprio.corpo
    voce = definizioni()[codice]
    return voce["oggetto"], voce["corpo"]


def segnaposto_in(testo):
    return set(SEGNAPOSTO.findall(testo or ""))


def errori(oggetto, corpo, campi, obbligatori=()):
    """I problemi del testo, in parole: campo sconosciuto (un refuso partirebbe vuoto) o campo necessario tolto."""
    trovati = segnaposto_in(oggetto) | segnaposto_in(corpo)
    problemi = []
    if not (oggetto or "").strip():
        problemi.append("Scrivi l'oggetto dell'email.")
    if not (corpo or "").strip():
        problemi.append("Scrivi il testo dell'email.")
    for nome in sorted(trovati - set(campi)):
        problemi.append(f"Il campo {{{{ {nome} }}}} non esiste: controlla come l'hai scritto.")
    for nome in obbligatori:
        if nome not in segnaposto_in(corpo):
            problemi.append(f"Il testo deve contenere {{{{ {nome} }}}}: senza, chi riceve l'email non può proseguire.")
    return problemi


def riempi(testo, valori):
    return SEGNAPOSTO.sub(lambda m: "" if valori.get(m.group(1)) is None else str(valori[m.group(1)]), testo)


def _marchio(azienda):
    """Il nome del prodotto del tema dell'azienda (theme.marchio), o quello dell'istanza."""
    import theme
    return theme.marchio(azienda if isinstance(azienda, Azienda) else None)


def _html(corpo, azienda):
    def collega(m):
        return f'<a href="{m.group(0)}" style="color:#2563eb">{m.group(0)}</a>'
    paragrafi = [URL.sub(collega, escape(p)).replace("\n", "<br>") for p in re.split(r"\n\s*\n", corpo.strip())]
    return render_to_string("core/email/modello.html", {"paragrafi": paragrafi, "azienda": azienda,
                                                        "marchio": _marchio(azienda)})


def componi(oggetto, corpo, valori, azienda):
    """(oggetto, testo, html) già riempiti. L'oggetto è su una riga sola: un valore non può aggiungere intestazioni."""
    tutti = {"azienda": str(azienda), "marchio": _marchio(azienda), "sito": settings.SITO_URL, **valori}
    testo = riempi(corpo, tutti)
    return " ".join(riempi(oggetto, tutti).split()), testo, _html(testo, azienda)


def mittente(azienda):
    """Il mittente delle email spedite per conto dell'azienda ("Zen Park <offerte@zenpark.it>"), o None per quello
    dell'istanza (DEFAULT_FROM_EMAIL). Con il solo nome: quel nome sull'indirizzo dell'istanza."""
    nome = (getattr(azienda, "email_mittente_nome", "") or "").strip()
    indirizzo = (getattr(azienda, "email_mittente", "") or "").strip()
    if not (nome or indirizzo):
        return None
    if not indirizzo:
        indirizzo = parseaddr(settings.DEFAULT_FROM_EMAIL)[1] or settings.DEFAULT_FROM_EMAIL
    return formataddr((nome, indirizzo)) if nome else indirizzo


def messaggio_da(oggetto, corpo, valori, azienda, to, connection=None, from_email=None, **altri):
    """L'email già riempita, dal mittente dell'azienda (o da `from_email`, se il chiamante ne vuole un altro)."""
    titolo, testo, html = componi(oggetto, corpo, valori, azienda)
    email = EmailMultiAlternatives(titolo, testo, from_email or mittente(azienda), to, connection=connection, **altri)
    email.attach_alternative(html, "text/html")
    return email


def messaggio(codice, azienda, valori, to, connection=None, **altri):
    """L'email pronta da spedire (si possono aggiungere allegati) con il testo in vigore per l'azienda."""
    oggetto, corpo = testo_di(codice, azienda)
    return messaggio_da(oggetto, corpo, valori, azienda, to, connection, **altri)
