"""Chiamate verso indirizzi decisi dagli utenti: mai verso la rete interna (SSRF). Si risolve il nome, si rifiuta se un
indirizzo non è pubblico e ci si collega proprio a quell'indirizzo, così il DNS non può cambiare tra controllo e chiamata."""
import ipaddress
import socket
from urllib.parse import urlsplit

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
