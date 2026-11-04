"""Testo leggero dei messaggi: escape, a capo, link, **grassetto**, *corsivo*, ~~barrato~~, `codice`, @menzioni e #canali."""
import re

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

MENZIONE = re.compile(r"(?<![\w@])@([\w.+-]{2,150})")
CANALE = re.compile(r"(?<![\w&#/])#([^\W\d][\w-]{1,79})")     # &#x27; è l'escape dell'apostrofo: non è un canale
LINK = re.compile(r"\bhttps?://[^\s<]+[^\s<.,;:!?)\]'\"]")
BLOCCO = re.compile(r"```\n?(.+?)```", re.S)
CODICE = re.compile(r"`([^`\n]+)`")
GRASSETTO = re.compile(r"\*\*(.+?)\*\*")
CORSIVO = re.compile(r"(?<![\w*])\*([^\s*](?:[^*\n]*[^\s*])?)\*(?![\w*])")
BARRATO = re.compile(r"~~(.+?)~~")


def menzionati(corpo):
    """Gli utenti attivi citati con @username."""
    nomi = {n.lower() for n in MENZIONE.findall(corpo or "")}
    if not nomi:
        return []
    return [u for u in get_user_model().objects.filter(is_active=True) if u.username.lower() in nomi]


def link_di(corpo):
    return [m.group(0) for m in LINK.finditer(corpo or "")]


def _canali(corpo):
    """I canali che esistono davvero tra quelli citati: «#abc» qualunque resta testo."""
    nomi = {n.lower() for n in CANALE.findall(corpo)}
    if not nomi:
        return set()
    from .models import Canale
    return {n.lower() for n in Canale.objects.exclude(tipo=Canale.DIRETTO).filter(archiviato=False).values_list("nome", flat=True)
            if n} & nomi


def _forma(html):
    html = BARRATO.sub(r"<del>\1</del>", GRASSETTO.sub(r"<strong>\1</strong>", html))
    return CORSIVO.sub(r"<em>\1</em>", html)


def _parte(testo, canali):
    """Testo senza link: il codice in linea resta com'è, sul resto valgono forme, menzioni e canali."""
    pezzi, inizio = [], 0
    for m in CODICE.finditer(testo):
        pezzi.append(_discorso(testo[inizio:m.start()], canali))
        pezzi.append(f"<code>{escape(m.group(1))}</code>")
        inizio = m.end()
    pezzi.append(_discorso(testo[inizio:], canali))
    return "".join(pezzi)


def _discorso(testo, canali):
    html = _forma(escape(testo))
    html = MENZIONE.sub(lambda m: f'<a class="ds-menzione" href="{reverse("discuss:con", args=[m.group(1)])}">@{m.group(1)}</a>', html)

    def canale(m):
        if m.group(1).lower() not in canali:
            return m.group(0)
        return f'<a class="ds-menzione" href="{reverse("discuss:vai", args=[m.group(1)])}">#{m.group(1)}</a>'
    return CANALE.sub(canale, html)


def _riga(corpo, canali):
    """I link si trattano a parte, così menzioni e forme non li toccano."""
    pezzi, inizio = [], 0
    for m in LINK.finditer(corpo):
        pezzi.append(_parte(corpo[inizio:m.start()], canali))
        url = escape(m.group(0))
        pezzi.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>')
        inizio = m.end()
    pezzi.append(_parte(corpo[inizio:], canali))
    return "".join(pezzi).replace("\n", "<br>")


def rendi(corpo):
    """HTML sicuro del messaggio."""
    corpo = corpo or ""
    canali = _canali(corpo)
    pezzi, inizio = [], 0
    for m in BLOCCO.finditer(corpo):
        pezzi.append(_riga(corpo[inizio:m.start()], canali))
        pezzi.append(f"<pre><code>{escape(m.group(1))}</code></pre>")
        inizio = m.end()
    pezzi.append(_riga(corpo[inizio:], canali))
    return mark_safe("".join(pezzi))


def piano(corpo):
    """Il testo senza i segni di formattazione: per le anteprime su una riga."""
    corpo = BLOCCO.sub(r"\1", corpo or "")
    corpo = CODICE.sub(r"\1", corpo)
    corpo = BARRATO.sub(r"\1", GRASSETTO.sub(r"\1", corpo))
    return " ".join(CORSIVO.sub(r"\1", corpo).split())


def evidenzia(testo, q):
    """L'estratto di un risultato di ricerca, con le parole cercate in evidenza."""
    testo = testo or ""
    parole = [p for p in (q or "").split() if ":" not in p]
    if not parole:
        return escape(testo[:200])
    prima = re.search("|".join(re.escape(p) for p in parole), testo, re.I)
    inizio = max(prima.start() - 60, 0) if prima else 0
    estratto = testo[inizio:inizio + 220]
    html = escape(estratto)
    for p in parole:
        html = re.sub(f"({re.escape(escape(p))})", r"<mark>\1</mark>", html, flags=re.I)
    return mark_safe(("…" if inizio else "") + html + ("…" if len(testo) > inizio + 220 else ""))
