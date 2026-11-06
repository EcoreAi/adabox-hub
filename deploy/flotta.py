#!/usr/bin/env python3
"""Le istanze dei clienti ospitate su questo server: una per cliente, ciascuna con i suoi container, il suo database e i
suoi segreti. Si crea, si aggiorna, si salva, si ferma e si elimina da qui. Solo libreria standard: gira sul server.

    deploy/flotta.py immagine --versione 1.4.0
    deploy/flotta.py crea rossi --cliente "Rossi Srl" --dominio hub.rossi.it --email admin@rossi.it --piano Base --versione 1.4.0
    deploy/flotta.py elenco
    deploy/flotta.py aggiorna --tutte --versione 1.5.0 --prima prova
    deploy/flotta.py backup --tutte
    deploy/flotta.py ferma rossi | avvia rossi | elimina rossi --conferma rossi

I segreti stanno in <radice>/<istanza>/.env, leggibile solo dal proprietario. Il proxy HTTPS non si tocca da qui: per
ogni istanza si scrive un frammento di configurazione da includere a mano."""
import argparse
import base64
import datetime
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "deploy" / "compose.istanza.yml"
SERVIZI_AI = REPO / "deploy" / "compose.servizi-adabox.yml"
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
DOMINIO_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
VERSIONE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")
PORTA_INIZIALE = 8200
ATTESA_SALUTE = 300
BACKUP_DA_TENERE = 14


class Errore(RuntimeError):
    """Un problema da spiegare a chi ha lanciato il comando."""


def radice():
    return Path(os.environ.get("FLOTTA_RADICE", Path.home() / "adabox-istanze"))


def scrivi(testo=""):
    print(testo, flush=True)


def esegui(comando, entrata=None, uscita=None, ambiente=None, controlla=True):
    """Un comando senza shell. Restituisce lo stdout come testo, o lo scrive in `uscita`."""
    env = {**os.environ, **(ambiente or {})}
    if uscita is not None:
        with open(uscita, "wb") as f:
            esito = subprocess.run(comando, stdout=f, stderr=subprocess.PIPE, env=env, check=False)
        testo = ""
    else:
        esito = subprocess.run(comando, stdin=open(entrata, "rb") if entrata else None, capture_output=True, env=env, check=False)
        testo = esito.stdout.decode(errors="replace")
    if controlla and esito.returncode != 0:
        dettaglio = (testo + esito.stderr.decode(errors="replace"))[-1500:]
        raise Errore(f"comando fallito: {' '.join(comando[:6])}…\n{dettaglio}")
    return testo


# --- i dati di un'istanza ---

def cartella(slug):
    return radice() / slug


def leggi(slug):
    percorso = cartella(slug) / "istanza.json"
    if not percorso.is_file():
        raise Errore(f"istanza «{slug}» inesistente")
    return json.loads(percorso.read_text())


def salva(dati):
    percorso = cartella(dati["slug"]) / "istanza.json"
    temporaneo = percorso.with_suffix(".tmp")
    temporaneo.write_text(json.dumps(dati, indent=2, ensure_ascii=False))
    temporaneo.replace(percorso)


def tutte():
    if not radice().is_dir():
        return []
    return [p.parent.name for p in sorted(radice().glob("*/istanza.json"))]


def porta_libera():
    usate = {leggi(s)["porta"] for s in tutte()}
    for porta in range(PORTA_INIZIALE, PORTA_INIZIALE + 1000):
        if porta in usate:
            continue
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", porta))
            except OSError:
                continue
        return porta
    raise Errore("nessuna porta libera")


def compose(dati, *argomenti, **kwargs):
    comando = ["docker", "compose", "-p", f"adabox_{dati['slug']}", "-f", str(COMPOSE)]
    if dati.get("servizi_ai"):
        comando += ["-f", str(SERVIZI_AI)]
    return esegui(comando + list(argomenti), ambiente={"ENV_ISTANZA": str(cartella(dati["slug"]) / ".env"), "VERSIONE": dati["versione"],
                                                       "PORTA": str(dati["porta"])}, **kwargs)


def in_salute(dati, attesa=ATTESA_SALUTE):
    """Passa dal nginx dell'istanza, come farebbe il proxy. True se risponde entro l'attesa."""
    richiesta = urllib.request.Request(f"http://127.0.0.1:{dati['porta']}/salute/", headers={"Host": dati["dominio"]})
    limite = time.monotonic() + attesa
    while True:
        try:
            with urllib.request.urlopen(richiesta, timeout=5) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() >= limite:
            return False
        time.sleep(3)


# --- creazione ---

def env_istanza(dati, token, chiave_pubblica, url_portale):
    https = not dati.get("http")
    schema = "https" if https else "http"
    password_db = secrets.token_urlsafe(24)
    voci = {
        "SECRET_KEY": secrets.token_urlsafe(50), "CHIAVE_CIFRATURA": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(), "DEBUG": "False",
        "ALLOWED_HOSTS": f"{dati['dominio']},localhost", "CSRF_TRUSTED_ORIGINS": f"{schema}://{dati['dominio']}", "SITO_URL": f"{schema}://{dati['dominio']}",
        "POSTGRES_PASSWORD": password_db, "DATABASE_URL": f"postgres://adabox:{password_db}@db:5432/adabox",
        "SESSION_COOKIE_NAME": f"adabox_{dati['slug']}_sessione", "CSRF_COOKIE_NAME": f"adabox_{dati['slug']}_csrf",
        "SESSION_COOKIE_SECURE": str(https), "CSRF_COOKIE_SECURE": str(https),
        "LICENZA_OBBLIGATORIA": "True", "LICENZA_PORTALE_URL": url_portale, "LICENZA_TOKEN": token,
        "MODULI_CHIAVI_FIDATE": chiave_pubblica, "MODULI_FIRMA_OBBLIGATORIA": "True"}
    return "".join(f"{k}={v}\n" for k, v in voci.items())


def _portale(portale, *argomenti):
    """Il comando di gestione delle istanze, eseguito dentro il container del portale. Restituisce il JSON che stampa."""
    testo = esegui(["docker", "exec", portale, "python", "manage.py", "rivendita_istanza", *argomenti])
    for riga in reversed(testo.splitlines()):
        if riga.startswith("{"):
            return json.loads(riga)
    raise Errore("il portale non ha risposto come previsto")


def frammento_proxy(dati):
    return f"{dati['dominio']} {{\n    reverse_proxy 127.0.0.1:{dati['porta']} {{\n        header_up X-Forwarded-Proto https\n    }}\n}}\n"


def crea(a):
    slug = a.slug
    if not SLUG_RE.match(slug):
        raise Errore("nome dell'istanza non valido: minuscole, cifre e trattini, da 2 a 31 caratteri")
    if not DOMINIO_RE.match(a.dominio):
        raise Errore("dominio non valido")
    if not VERSIONE_RE.match(a.versione):
        raise Errore("versione non valida")
    if cartella(slug).exists():
        raise Errore(f"esiste già {cartella(slug)}: non la sovrascrivo")
    esegui(["docker", "image", "inspect", f"adabox_hub_cliente:{a.versione}"], controlla=True)
    dati = {"slug": slug, "cliente": a.cliente, "dominio": a.dominio, "email": a.email, "versione": a.versione, "porta": porta_libera(),
            "servizi_ai": a.servizi_ai, "http": a.http, "portale": a.portale, "codice_portale": "", "creata": datetime.datetime.now().isoformat(timespec="seconds"), "storia": []}
    url = f"{'http' if a.http else 'https'}://{a.dominio}/"
    argomenti = ["crea", "--cliente", a.cliente, "--email", a.email, "--piano", a.piano, "--url", url, "--scadenza", a.scadenza]
    if a.moduli:
        argomenti += ["--moduli", *a.moduli]
    risposta = _portale(a.portale, *argomenti)
    dati["codice_portale"] = risposta["codice"]
    cartella(slug).mkdir(parents=True, mode=0o700)
    (cartella(slug) / "backup").mkdir(mode=0o700)
    percorso_env = cartella(slug) / ".env"
    percorso_env.touch(mode=0o600)
    percorso_env.write_text(env_istanza(dati, risposta["token"], risposta["chiave_pubblica"], a.url_portale))
    salva(dati)
    scrivi(f"Avvio di {slug} sulla porta {dati['porta']}…")
    compose(dati, "up", "-d")
    if not in_salute(dati):
        raise Errore(f"{slug} non risponde dopo {ATTESA_SALUTE} secondi. Log: flotta log {slug}. Per ripartire da zero: flotta elimina {slug} --conferma {slug}")
    scrivi("Scarico i moduli dal portale…")
    # in web e non nel worker: quando i moduli cambiano il worker esce per ripartire, e il comando morirebbe con lui
    compose(dati, "exec", "-T", "web", "python", "manage.py", "licenza", "sincronizza")
    testo = compose(dati, "exec", "-T", "web", "python", "manage.py", "primo_admin", "--email", a.email, "--azienda", a.cliente)
    password = next((r.split("=", 1)[1] for r in testo.splitlines() if r.startswith("PASSWORD=")), "")
    (cartella(slug) / "proxy.caddy").write_text(frammento_proxy(dati))
    scrivi(f"\nIstanza {slug} pronta: {url}")
    scrivi(f"Admin: {a.email}")
    if password:
        scrivi(f"Password iniziale, mostrata solo ora: {password}")
    scrivi(f"Proxy: includi {cartella(slug) / 'proxy.caddy'} nella configurazione di Caddy, dopo aver puntato il DNS.")


# --- salvataggi e aggiornamenti ---

def backup(dati, motivo="manuale"):
    """Database e file dell'istanza in <istanza>/backup. Restituisce il prefisso dei file."""
    prefisso = cartella(dati["slug"]) / "backup" / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{motivo}"
    compose(dati, "exec", "-T", "db", "pg_dump", "-U", "adabox", "-Fc", "adabox", uscita=f"{prefisso}.dump")
    compose(dati, "exec", "-T", "web", "tar", "czf", "-", "-C", "/app", "media", "private", "addons", uscita=f"{prefisso}.file.tgz")
    for f in (Path(f"{prefisso}.dump"), Path(f"{prefisso}.file.tgz")):
        f.chmod(0o600)
    if Path(f"{prefisso}.dump").stat().st_size == 0:
        raise Errore(f"backup vuoto per {dati['slug']}: mi fermo")
    dump = sorted((cartella(dati["slug"]) / "backup").glob("*.dump"))
    for vecchio in dump[:-BACKUP_DA_TENERE]:
        vecchio.unlink()
        Path(str(vecchio).removesuffix(".dump") + ".file.tgz").unlink(missing_ok=True)
    return prefisso


def ripristina(dati, prefisso):
    """Il database e i moduli di prima. Si ferma l'applicazione: nessuno deve scrivere mentre si ricarica."""
    compose(dati, "stop", "web", "worker", "stream")
    # pg_restore può uscire con avvisi innocui: a dire se è andata è il controllo di salute che segue
    compose(dati, "exec", "-T", "db", "pg_restore", "-U", "adabox", "-d", "adabox", "--clean", "--if-exists", "--no-owner", entrata=f"{prefisso}.dump", controlla=False)
    compose(dati, "up", "-d", controlla=False)


def aggiorna_una(slug, versione):
    """(True) se è andata; (False) se non si è ripresa e si è tornati indietro."""
    dati = leggi(slug)
    if dati["versione"] == versione:
        scrivi(f"{slug}: già alla {versione}")
        return True
    precedente = dati["versione"]
    scrivi(f"{slug}: salvataggio…")
    prefisso = backup(dati, f"prima-di-{versione}")
    dati["versione"] = versione
    scrivi(f"{slug}: passo dalla {precedente} alla {versione}…")
    try:
        compose(dati, "up", "-d", "--remove-orphans")     # se un container non parte esce con errore: si torna indietro
        partita = in_salute(dati)
    except Errore as e:
        scrivi(f"{slug}: avvio non riuscito: {str(e)[-300:]}")
        partita = False
    if partita:
        dati["storia"].append({"da": precedente, "a": versione, "il": datetime.datetime.now().isoformat(timespec="seconds"), "esito": "ok"})
        salva(dati)
        scrivi(f"{slug}: OK")
        return True
    scrivi(f"{slug}: non risponde, torno alla {precedente}")
    dati["versione"] = precedente
    ripristina(dati, prefisso)
    ripresa = in_salute(dati)
    dati["storia"].append({"da": precedente, "a": versione, "il": datetime.datetime.now().isoformat(timespec="seconds"), "esito": "ripristinata" if ripresa else "ferma"})
    salva(dati)
    scrivi(f"{slug}: {'ripristinata' if ripresa else 'NON SI È RIPRESA: intervieni a mano, backup ' + str(prefisso)}")
    return False


def aggiorna(a):
    if not VERSIONE_RE.match(a.versione):
        raise Errore("versione non valida")
    esegui(["docker", "image", "inspect", f"adabox_hub_cliente:{a.versione}"])
    scelte = tutte() if a.tutte else a.slugs
    if not scelte:
        raise Errore("indica le istanze oppure --tutte")
    for s in scelte:
        leggi(s)
    if a.prima:
        if a.prima not in scelte:
            raise Errore(f"--prima {a.prima}: non è tra le istanze da aggiornare")
        scelte = [a.prima, *[s for s in scelte if s != a.prima]]
    fatte = []
    for s in scelte:
        if not aggiorna_una(s, a.versione):
            mancano = scelte[len(fatte) + 1:]
            raise Errore(f"mi fermo su {s}. Aggiornate: {', '.join(fatte) or 'nessuna'}. Non toccate: {', '.join(mancano) or 'nessuna'}")
        fatte.append(s)
    scrivi(f"Aggiornate: {', '.join(fatte)}")


# --- gli altri comandi ---

def immagine(a):
    if not VERSIONE_RE.match(a.versione):
        raise Errore("versione non valida")
    scrivi(f"Costruisco adabox_hub_cliente:{a.versione}…")
    esegui(["docker", "build", "-f", str(REPO / "deploy" / "Dockerfile.cliente"), "-t", f"adabox_hub_cliente:{a.versione}", str(REPO)])
    scrivi("Fatto.")


def elenco(_):
    voci = tutte()
    if not voci:
        scrivi("Nessuna istanza.")
    for s in voci:
        d = leggi(s)
        scrivi(f"{s:<20} {d['cliente']:<28} {d['versione']:<12} porta {d['porta']:<6} {'ok' if in_salute(d, attesa=0) else 'NON RISPONDE':<13} {d['dominio']}")


def fai_backup(a):
    scelte = tutte() if a.tutte else a.slugs
    if not scelte:
        raise Errore("indica le istanze oppure --tutte")
    errori = []
    for s in scelte:
        try:
            scrivi(f"{s}: {backup(leggi(s))}")
        except Errore as e:
            errori.append(f"{s}: {e}")
    if errori:
        raise Errore("\n".join(errori))


def ferma(a):
    compose(leggi(a.slug), "stop")
    scrivi(f"{a.slug} ferma: i dati restano.")


def avvia(a):
    compose(leggi(a.slug), "up", "-d")
    scrivi(f"{a.slug} avviata.")


def log_istanza(a):
    scrivi(compose(leggi(a.slug), "logs", "--tail", "100", a.servizio) if a.servizio else compose(leggi(a.slug), "logs", "--tail", "100"))


def elimina(a):
    """Container e dati via: serve scrivere il nome due volte. Salvo --senza-backup resta un ultimo salvataggio su disco."""
    if a.conferma != a.slug:
        raise Errore(f"per eliminare scrivi --conferma {a.slug}")
    dati = leggi(a.slug)
    if not a.senza_backup:
        try:
            scrivi(f"Ultimo salvataggio: {backup(dati, 'prima-di-eliminare')}")
        except Errore as e:
            raise Errore(f"salvataggio non riuscito, non elimino. Se l'istanza non è mai partita aggiungi --senza-backup.\n{e}") from e
    compose(dati, "down", "-v", "--remove-orphans")
    if dati.get("codice_portale") and dati.get("portale"):
        _portale(dati["portale"], "revoca", "--codice", dati["codice_portale"])
    (cartella(a.slug) / ".env").unlink(missing_ok=True)
    (cartella(a.slug) / "istanza.json").rename(cartella(a.slug) / "istanza.eliminata.json")
    scrivi(f"{a.slug} eliminata. I salvataggi restano in {cartella(a.slug) / 'backup'}: toglili quando non servono più.")


def parser():
    p = argparse.ArgumentParser(description="Le istanze dei clienti su questo server")
    sub = p.add_subparsers(dest="comando", required=True)
    s = sub.add_parser("immagine", help="costruisce l'immagine di una versione")
    s.add_argument("--versione", required=True)
    s.set_defaults(funzione=immagine)
    s = sub.add_parser("crea", help="crea un'istanza: portale, segreti, container, moduli, primo admin")
    s.add_argument("slug")
    s.add_argument("--cliente", required=True)
    s.add_argument("--dominio", required=True)
    s.add_argument("--email", required=True, help="email dell'admin del cliente")
    s.add_argument("--piano", required=True, help="nome del piano sul portale")
    s.add_argument("--moduli", nargs="*", default=[], help="moduli oltre al piano")
    s.add_argument("--versione", required=True)
    s.add_argument("--scadenza", default=(datetime.date.today() + datetime.timedelta(days=365)).isoformat(), help="AAAA-MM-GG, default un anno")
    s.add_argument("--portale", default=os.environ.get("FLOTTA_PORTALE", "adabox_hub_web"), help="container del portale")
    s.add_argument("--url-portale", default=os.environ.get("FLOTTA_URL_PORTALE", ""), help="indirizzo con cui le istanze raggiungono il portale, es. https://portale.ichnobyte.it/rivendita/api")
    s.add_argument("--servizi-ai", action="store_true", help="collega ai servizi AI condivisi di questo server")
    s.add_argument("--http", action="store_true", help="solo per prove senza HTTPS")
    s.set_defaults(funzione=crea)
    sub.add_parser("elenco", help="le istanze e il loro stato").set_defaults(funzione=elenco)
    s = sub.add_parser("aggiorna", help="salva, aggiorna, controlla; se non si riprende torna indietro e si ferma")
    s.add_argument("slugs", nargs="*")
    s.add_argument("--tutte", action="store_true")
    s.add_argument("--versione", required=True)
    s.add_argument("--prima", help="l'istanza da aggiornare per prima, per esempio la vostra di prova")
    s.set_defaults(funzione=aggiorna)
    s = sub.add_parser("backup", help="salva database e file")
    s.add_argument("slugs", nargs="*")
    s.add_argument("--tutte", action="store_true")
    s.set_defaults(funzione=fai_backup)
    for nome, funzione in (("ferma", ferma), ("avvia", avvia)):
        s = sub.add_parser(nome)
        s.add_argument("slug")
        s.set_defaults(funzione=funzione)
    s = sub.add_parser("log")
    s.add_argument("slug")
    s.add_argument("servizio", nargs="?")
    s.set_defaults(funzione=log_istanza)
    s = sub.add_parser("elimina", help="toglie container e dati, tenendo un ultimo salvataggio")
    s.add_argument("slug")
    s.add_argument("--conferma", required=True, help="di nuovo il nome dell'istanza")
    s.add_argument("--senza-backup", action="store_true")
    s.set_defaults(funzione=elimina)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    if a.comando == "crea" and not a.url_portale:
        raise SystemExit("serve --url-portale, o FLOTTA_URL_PORTALE")
    try:
        a.funzione(a)
    except Errore as e:
        raise SystemExit(f"ERRORE: {e}") from e


if __name__ == "__main__":
    sys.exit(main())
