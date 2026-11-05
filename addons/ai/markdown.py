"""Markdown delle risposte in HTML sicuro: prima si fa l'escape di tutto, poi si aggiungono solo i tag ammessi
(paragrafi, titoli, elenchi, tabelle, codice, grassetto, corsivo, link http/https e link interni /...)."""
import re
from html import unescape

from django.utils.html import escape
from django.utils.safestring import mark_safe

LINGUA = re.compile(r"[a-z0-9+#_-]{1,20}")
CODICE_MASSIMO = 20_000
CODICE = re.compile(r"`([^`\n]+)`")
GRASSETTO = re.compile(r"\*\*(.+?)\*\*")
CORSIVO = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])|(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)")
LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+|/(?!/)[^\s)]*)\)")
URL = re.compile(r"(?<![\"'=>])\bhttps?://[^\s<]+[^\s<.,;:!?)\]'\"]")
SEPARATORE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def _in_linea(testo):
    """Su testo già passato da escape."""
    segnaposti = []

    def proteggi(html):
        segnaposti.append(html)
        return f"\x00{len(segnaposti) - 1}\x00"

    testo = CODICE.sub(lambda m: proteggi(f"<code>{m.group(1)}</code>"), testo)
    testo = LINK.sub(lambda m: proteggi(f'<a href="{m.group(2)}" target="_blank" rel="noopener noreferrer">'
                                        f'{m.group(1)}</a>'), testo)
    testo = URL.sub(lambda m: proteggi(f'<a href="{m.group(0)}" target="_blank" rel="noopener noreferrer">'
                                       f'{m.group(0)}</a>'), testo)
    testo = GRASSETTO.sub(r"<strong>\1</strong>", testo)
    testo = CORSIVO.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", testo)
    return re.sub(r"\x00(\d+)\x00", lambda m: segnaposti[int(m.group(1))], testo)


def _blocco_codice(testo_con_escape, lingua):
    """Il codice è già passato da escape; Pygments riceve il testo originale e fa da sé l'escape di tutto ciò che scrive.
    Lingua sconosciuta, troppo codice o Pygments assente: testo semplice."""
    lingua = lingua if LINGUA.fullmatch(lingua) else ""
    attributo = f' data-lingua="{lingua}"' if lingua else ""
    if lingua and len(testo_con_escape) <= CODICE_MASSIMO:
        try:
            from pygments import highlight
            from pygments.formatters import HtmlFormatter
            from pygments.lexers import get_lexer_by_name
            colorato = highlight(unescape(testo_con_escape), get_lexer_by_name(lingua), HtmlFormatter(nowrap=True))
            return f"<pre{attributo}><code>{colorato.rstrip()}</code></pre>"
        except Exception:                               # ImportError, ClassNotFound: il codice si legge lo stesso
            pass
    return f"<pre{attributo}><code>{testo_con_escape}</code></pre>"


def _celle(riga):
    return [c.strip() for c in riga.strip().strip("|").split("|")]


def rendi(testo):
    righe = escape(testo or "").replace("\r\n", "\n").split("\n")
    html, i = [], 0
    paragrafo = []

    def chiudi_paragrafo():
        if paragrafo:
            html.append("<p>" + "<br>".join(_in_linea(r) for r in paragrafo) + "</p>")
            paragrafo.clear()

    while i < len(righe):
        riga = righe[i]
        if riga.strip().startswith("```"):
            chiudi_paragrafo()
            lingua = riga.strip()[3:].strip().lower()
            codice, i = [], i + 1
            while i < len(righe) and not righe[i].strip().startswith("```"):
                codice.append(righe[i])
                i += 1
            html.append(_blocco_codice("\n".join(codice), lingua))
            i += 1
            continue
        titolo = re.match(r"^(#{1,4})\s+(.*)$", riga)
        if titolo:
            chiudi_paragrafo()
            livello = min(len(titolo.group(1)) + 2, 6)
            html.append(f"<h{livello}>{_in_linea(titolo.group(2))}</h{livello}>")
            i += 1
            continue
        if riga.strip().startswith("|") and i + 1 < len(righe) and SEPARATORE.match(righe[i + 1].strip()):
            chiudi_paragrafo()
            testa = _celle(riga)
            corpo, i = [], i + 2
            while i < len(righe) and righe[i].strip().startswith("|"):
                corpo.append(_celle(righe[i]))
                i += 1
            html.append('<div class="ai-tabella"><table><thead><tr>'
                        + "".join(f"<th>{_in_linea(c)}</th>" for c in testa) + "</tr></thead><tbody>"
                        + "".join("<tr>" + "".join(f"<td>{_in_linea(c)}</td>" for c in r) + "</tr>" for r in corpo)
                        + "</tbody></table></div>")
            continue
        elenco = re.match(r"^\s*([-*]|\d+[.)])\s+(.*)$", riga)
        if elenco:
            chiudi_paragrafo()
            numerato = elenco.group(1)[0].isdigit()
            voci = []
            while i < len(righe) and (m := re.match(r"^\s*([-*]|\d+[.)])\s+(.*)$", righe[i])) \
                    and m.group(1)[0].isdigit() == numerato:
                voci.append(f"<li>{_in_linea(m.group(2))}</li>")
                i += 1
            tag = "ol" if numerato else "ul"
            html.append(f"<{tag}>{''.join(voci)}</{tag}>")
            continue
        if not riga.strip():
            chiudi_paragrafo()
        else:
            paragrafo.append(riga)
        i += 1
    chiudi_paragrafo()
    return mark_safe("".join(html))
