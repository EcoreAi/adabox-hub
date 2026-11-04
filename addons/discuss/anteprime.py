"""Anteprime dei link: titolo e descrizione della pagina, letti dal lavoratore in background.

L'URL lo sceglie chi scrive il messaggio, quindi il server non deve poter essere usato per leggere la rete interna:
solo http e https sulle porte standard, solo indirizzi pubblici (controllati a ogni reindirizzamento e usati per la
connessione, così un DNS che cambia risposta non serve a niente), tempi e dimensioni limitati. Le immagini delle
pagine non si caricano: il browser di chi legge contatterebbe siti scelti da altri."""
import ipaddress
import re
import socket
from html import unescape
from urllib.parse import urljoin, urlsplit

import httpx2 as httpx
from django.conf import settings

from . import eventi, testo
from .models import Messaggio

MASSIMO_LINK = 3
MASSIMO_BYTE = 500_000
TEMPO = 4.0
REINDIRIZZAMENTI = 3
META = re.compile(r"<meta\b[^>]*>", re.I)
ATTRIBUTO = re.compile(r"""([\w:-]+)\s*=\s*("[^"]*"|'[^']*')""")
TITOLO = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


class Rifiutato(ValueError):
    pass


def _indirizzo_pubblico(host, porta):
    """Il primo indirizzo del nome, se tutti sono pubblici."""
    try:
        risposte = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except OSError as e:
        raise Rifiutato(f"nome non risolto: {host}") from e
    indirizzi = [r[4][0] for r in risposte]
    for i in indirizzi:
        ip = ipaddress.ip_address(i.split("%")[0])
        if not ip.is_global:
            raise Rifiutato(f"indirizzo non pubblico: {host}")
    if not indirizzi:
        raise Rifiutato(f"nome non risolto: {host}")
    return indirizzi[0]


def _controlla(url):
    parti = urlsplit(url)
    if parti.scheme not in ("http", "https") or not parti.hostname or parti.username or parti.password:
        raise Rifiutato("indirizzo non ammesso")
    porta = parti.port or (443 if parti.scheme == "https" else 80)
    if porta not in (80, 443):
        raise Rifiutato("porta non ammessa")
    return parti, porta


def _scarica(url, http_client=None):
    client = http_client or httpx.Client(timeout=TEMPO, follow_redirects=False, trust_env=False)
    try:
        for _ in range(REINDIRIZZAMENTI + 1):
            parti, porta = _controlla(url)
            ip = _indirizzo_pubblico(parti.hostname, porta)
            host_ip = f"[{ip}]" if ":" in ip else ip
            percorso = parti.path or "/"
            if parti.query:
                percorso += f"?{parti.query}"
            with client.stream("GET", f"{parti.scheme}://{host_ip}:{porta}{percorso}",
                               headers={"Host": parti.netloc, "User-Agent": "Mozilla/5.0 (compatible; AnteprimaLink/1.0)",
                                        "Accept": "text/html"},
                               extensions={"sni_hostname": parti.hostname}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
                    raise Rifiutato("non è una pagina")
                corpo = b""
                for pezzo in r.iter_bytes():
                    corpo += pezzo
                    if len(corpo) > MASSIMO_BYTE:
                        break
                return corpo.decode(r.encoding or "utf-8", "replace"), url
        raise Rifiutato("troppi reindirizzamenti")
    finally:
        if http_client is None:
            client.close()


def leggi_html(html):
    """(titolo, descrizione, sito) dai metadati della pagina."""
    meta = {}
    for tag in META.findall(html):
        attr = {k.lower(): v[1:-1] for k, v in ATTRIBUTO.findall(tag)}
        chiave = (attr.get("property") or attr.get("name") or "").lower()
        if chiave and "content" in attr:
            meta.setdefault(chiave, unescape(attr["content"]).strip())
    titolo = meta.get("og:title") or meta.get("twitter:title")
    if not titolo:
        m = TITOLO.search(html)
        titolo = " ".join(unescape(m.group(1)).split()) if m else ""
    descrizione = meta.get("og:description") or meta.get("description") or meta.get("twitter:description") or ""
    return titolo[:200], " ".join(descrizione.split())[:300], meta.get("og:site_name", "")[:80]


def _interno(url):
    """I link allo stesso gestionale diventano schede dei record, non anteprime."""
    host = urlsplit(url).netloc.lower()
    return bool(host) and host == urlsplit(settings.SITO_URL).netloc.lower()


def calcola(messaggio, http_client=None):
    """Lavoro in background: legge le pagine citate e aggiorna il messaggio nei browser collegati."""
    m = Messaggio.objects.filter(pk=messaggio, eliminato=False).first()
    if m is None:
        return "messaggio assente"
    trovate = []
    for url in [u for u in dict.fromkeys(testo.link_di(m.corpo)) if not _interno(u)][:MASSIMO_LINK]:
        try:
            html, finale = _scarica(url, http_client)
        except (Rifiutato, httpx.HTTPError, ValueError, UnicodeError):
            continue
        titolo, descrizione, sito = leggi_html(html)
        if titolo:
            trovate.append({"url": url, "titolo": titolo, "descrizione": descrizione,
                            "sito": sito or (urlsplit(finale).hostname or "").removeprefix("www.")})
    if trovate:
        Messaggio.objects.filter(pk=m.pk).update(anteprime=trovate)
        eventi.emetti("agg", m.canale, m=m.pk)
    return f"anteprime: {len(trovate)}"
