"""Le librerie che un modulo chiede all'immagine: pacchetti Python e pacchetti di sistema (Debian).

I moduli arrivano dal portale in un'immagine già costruita, quindi non possono installarsi le librerie da soli: le
dichiarano in "dipendenze" del manifest e qui si controlla che ci siano, prima di installarli o aggiornarli. Se ne manca
una il modulo non si installa (meglio un rifiuto chiaro che una pagina che si rompe alla prima scansione). Per
aggiungerle si ricostruisce l'immagine: requirements-documenti.txt e l'elenco apt del Dockerfile.

    "dipendenze": {"python": ["opencv-python-headless>=4.10", "numpy"], "sistema": ["tesseract-ocr", "tesseract-ocr-ita"]}
"""
import importlib.metadata
import logging
import re
import shutil
import subprocess

log = logging.getLogger("core.moduli")

PYTHON_RE = re.compile(r"^(?P<nome>[A-Za-z0-9][A-Za-z0-9._-]*)(?:>=(?P<minima>\d+(?:\.\d+)*))?$")
SISTEMA_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
CHIAVI = {"python", "sistema"}


def valida(errori, valore):
    """Forma della voce del manifest: {"python": ["nome" o "nome>=X.Y"], "sistema": ["pacchetto-debian"]}."""
    if not isinstance(valore, dict):
        errori.append(f"dipendenze: atteso un dizionario {{python: [...], sistema: [...]}}, trovato {valore!r}")
        return
    if extra := sorted(set(valore) - CHIAVI):
        errori.append(f"dipendenze: chiavi sconosciute: {', '.join(map(str, extra))} (ammesse: python, sistema)")
    for chiave, regola, esempio in (("python", PYTHON_RE, "numpy o numpy>=2.0"), ("sistema", SISTEMA_RE, "tesseract-ocr")):
        voci = valore.get(chiave, [])
        if not isinstance(voci, list):
            errori.append(f"dipendenze: {chiave} deve essere una lista, trovato {voci!r}")
            continue
        for v in voci:
            if not (isinstance(v, str) and regola.match(v)):
                errori.append(f"dipendenze: {chiave}: {v!r} non valido (es. {esempio})")


def _tupla(versione):
    """(4, 14, 0, 94) da "4.14.0.94"; le parti non numeriche (rc1, post1, +local) si fermano alla prima cifra."""
    parti = []
    for p in versione.split("."):
        cifre = re.match(r"\d+", p)
        if not cifre:
            break
        parti.append(int(cifre.group()))
        if cifre.group() != p:
            break
    return tuple(parti)


def _python_manca(voce):
    m = PYTHON_RE.match(voce)
    try:
        installata = importlib.metadata.version(m["nome"])
    except importlib.metadata.PackageNotFoundError:
        return True
    return bool(m["minima"]) and _tupla(installata) < _tupla(m["minima"])


def _dpkg_installato(pacchetto):
    esito = subprocess.run(["dpkg-query", "-W", "-f=${Status}", pacchetto], capture_output=True, text=True)
    return esito.returncode == 0 and esito.stdout.strip().endswith(" installed")


def _sistema_manca(pacchetto):
    """Con Debian trixie molte librerie hanno preso il suffisso t64 (libglib2.0-0 → libglib2.0-0t64): vale l'una o
    l'altra."""
    return not (_dpkg_installato(pacchetto) or _dpkg_installato(pacchetto + "t64"))


def mancanti(manifest):
    """Le dipendenze del modulo che l'immagine non ha, come testo ("Python numpy>=2.0", "sistema tesseract-ocr").
    Fuori da Debian (dpkg-query assente, es. sviluppo su un Mac) i pacchetti di sistema non si possono controllare:
    si avvisa nel log e non si blocca."""
    dichiarate = getattr(manifest, "dipendenze", None) or {}
    assenti = [f"Python {v}" for v in dichiarate.get("python", []) if _python_manca(v)]
    sistema = dichiarate.get("sistema", [])
    if sistema and shutil.which("dpkg-query") is None:
        log.warning("%s: dpkg-query assente, pacchetti di sistema non controllati: %s", manifest.slug, ", ".join(sistema))
    elif sistema:
        assenti += [f"sistema {p}" for p in sistema if _sistema_manca(p)]
    return assenti


def controlla(slugs, info):
    """{slug: [mancanti]} per i moduli del piano che chiedono librerie assenti (vuoto se c'è tutto)."""
    return {s: m for s in slugs if info[s].manifest is not None and (m := mancanti(info[s].manifest))}


def messaggio(assenti):
    righe = "; ".join(f"{s}: {', '.join(m)}" for s, m in assenti.items())
    return (f"mancano nell'immagine le librerie che il modulo dichiara in «dipendenze» ({righe}). Vanno aggiunte "
            "all'immagine (requirements-documenti.txt o l'elenco apt del Dockerfile) e l'immagine va ricostruita.")
