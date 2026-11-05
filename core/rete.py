"""Chiamate verso indirizzi decisi dagli utenti: mai verso la rete interna (SSRF). Si risolve il nome, si rifiuta se un
indirizzo non è pubblico e ci si collega proprio a quell'indirizzo, così il DNS non può cambiare tra controllo e chiamata."""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx2 as httpx


class Rifiutato(ValueError):
    pass


def indirizzo_pubblico(host, porta):
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


def controlla(url, solo_https=False):
    """(parti dell'URL, porta) se la forma è ammessa. Non tocca la rete."""
    try:
        parti = urlsplit(url)
        porta = parti.port or (443 if parti.scheme == "https" else 80)
    except ValueError as e:
        raise Rifiutato("indirizzo non ammesso") from e
    schemi = ("https",) if solo_https else ("http", "https")
    if parti.scheme not in schemi or not parti.hostname or parti.username or parti.password:
        raise Rifiutato("serve un indirizzo https" if solo_https else "indirizzo non ammesso")
    if porta not in (80, 443):
        raise Rifiutato("porta non ammessa")
    return parti, porta


def post_sicuro(url, corpo, intestazioni, tempo=10, http_client=None):
    """POST senza seguire reindirizzamenti, solo verso https pubblici. Restituisce lo stato HTTP."""
    parti, porta = controlla(url, solo_https=True)
    ip = indirizzo_pubblico(parti.hostname, porta)
    host_ip = f"[{ip}]" if ":" in ip else ip
    percorso = (parti.path or "/") + (f"?{parti.query}" if parti.query else "")
    client = http_client or httpx.Client(timeout=tempo, follow_redirects=False, trust_env=False)
    try:
        return client.post(f"https://{host_ip}:{porta}{percorso}", content=corpo,
                           headers={**intestazioni, "Host": parti.netloc},
                           extensions={"sni_hostname": parti.hostname}).status_code
    finally:
        if http_client is None:
            client.close()


def scarica(url, tipi=("text/html", "text/plain"), massimo=2_000_000, tempo=10, reindirizzamenti=3, http_client=None):
    """(testo, url finale) di una pagina pubblica. Ogni reindirizzamento si ricontrolla, e ci si collega all'indirizzo
    controllato. Rifiutato se non è pubblico, se il tipo non è ammesso; oltre `massimo` byte si taglia."""
    client = http_client or httpx.Client(timeout=tempo, follow_redirects=False, trust_env=False)
    try:
        for _ in range(reindirizzamenti + 1):
            parti, porta = controlla(url)
            ip = indirizzo_pubblico(parti.hostname, porta)
            host_ip = f"[{ip}]" if ":" in ip else ip
            percorso = (parti.path or "/") + (f"?{parti.query}" if parti.query else "")
            with client.stream("GET", f"{parti.scheme}://{host_ip}:{porta}{percorso}", extensions={"sni_hostname": parti.hostname},
                               headers={"Host": parti.netloc, "User-Agent": "Mozilla/5.0 (compatible; AdaboxHub/1.0)", "Accept": "text/html,text/plain"}) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                tipo = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if r.status_code != 200 or tipo not in tipi:
                    raise Rifiutato(f"risposta {r.status_code}, tipo {tipo or 'sconosciuto'}")
                corpo = b""
                for pezzo in r.iter_bytes():
                    corpo += pezzo
                    if len(corpo) > massimo:
                        break
                return corpo.decode(r.encoding or "utf-8", "replace"), url
        raise Rifiutato("troppi reindirizzamenti")
    finally:
        if http_client is None:
            client.close()


def _indirizzo_interno_ammesso(host, porta):
    """Per i sistemi nella rete del cliente, scelti da un amministratore: rete privata e loopback sì; mai gli indirizzi
    link-local (169.254.x, dove stanno i metadati dei cloud), multicast e non specificati."""
    try:
        risposte = socket.getaddrinfo(host, porta, type=socket.SOCK_STREAM)
    except OSError as e:
        raise Rifiutato(f"nome non risolto: {host}") from e
    indirizzi = [r[4][0] for r in risposte]
    for i in indirizzi:
        ip = ipaddress.ip_address(i.split("%")[0])
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise Rifiutato(f"indirizzo non ammesso: {host}")
    if not indirizzi:
        raise Rifiutato(f"nome non risolto: {host}")
    return indirizzi[0]


def post_con_risposta(url, corpo, intestazioni, interna=False, tempo=30, massimo=2_000_000, http_client=None):
    """(stato, intestazioni, corpo) di un POST. Senza `interna`: solo https verso indirizzi pubblici. Con `interna`
    (decisa da un amministratore): anche http e rete privata, mai i metadati dei cloud. Niente reindirizzamenti."""
    if interna:
        try:
            parti = urlsplit(url)
            porta = parti.port or (443 if parti.scheme == "https" else 80)
        except ValueError as e:
            raise Rifiutato("indirizzo non ammesso") from e
        if parti.scheme not in ("http", "https") or not parti.hostname or parti.username or parti.password:
            raise Rifiutato("indirizzo non ammesso")
        ip = _indirizzo_interno_ammesso(parti.hostname, porta)
    else:
        parti, porta = controlla(url, solo_https=True)
        ip = indirizzo_pubblico(parti.hostname, porta)
    host_ip = f"[{ip}]" if ":" in ip else ip
    percorso = (parti.path or "/") + (f"?{parti.query}" if parti.query else "")
    client = http_client or httpx.Client(timeout=tempo, follow_redirects=False, trust_env=False)
    try:
        with client.stream("POST", f"{parti.scheme}://{host_ip}:{porta}{percorso}", content=corpo,
                           headers={**intestazioni, "Host": parti.netloc}, extensions={"sni_hostname": parti.hostname}) as r:
            dati = b""
            for pezzo in r.iter_bytes():
                dati += pezzo
                if len(dati) > massimo:
                    raise Rifiutato("risposta troppo grande")
            return r.status_code, dict(r.headers), dati
    finally:
        if http_client is None:
            client.close()
