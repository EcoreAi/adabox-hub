"""Testo leggero dei messaggi: escape, a capo, link, **grassetto** e @menzioni."""
import re

from django.contrib.auth import get_user_model
from django.utils.html import escape
from django.utils.safestring import mark_safe

MENZIONE = re.compile(r"(?<![\w@])@([\w.+-]{2,150})")
LINK = re.compile(r"\bhttps?://[^\s<]+[^\s<.,;:!?)\]'\"]")
GRASSETTO = re.compile(r"\*\*(.+?)\*\*")


def menzionati(corpo):
    """Gli utenti attivi citati con @username."""
    nomi = {n.lower() for n in MENZIONE.findall(corpo or "")}
    if not nomi:
        return []
    return [u for u in get_user_model().objects.filter(is_active=True) if u.username.lower() in nomi]


def _parte(testo):
    html = GRASSETTO.sub(r"<strong>\1</strong>", escape(testo))
    return MENZIONE.sub(r'<span class="ds-menzione">@\1</span>', html)


def rendi(corpo):
    """HTML sicuro del messaggio: i link si trattano a parte, così menzioni e grassetto non li toccano."""
    corpo, pezzi, inizio = corpo or "", [], 0
    for m in LINK.finditer(corpo):
        pezzi.append(_parte(corpo[inizio:m.start()]))
        url = escape(m.group(0))
        pezzi.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{url}</a>')
        inizio = m.end()
    pezzi.append(_parte(corpo[inizio:]))
    return mark_safe("".join(pezzi).replace("\n", "<br>"))
