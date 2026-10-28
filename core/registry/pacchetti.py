"""Pacchetti dei moduli: zip con descrizione e hash dei file, firma Ed25519, controlli e caricamento in addons/."""
import base64
import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.utils import timezone

from . import manifest

DESCRIZIONE = "adabox-modulo.json"
FIRMA = "adabox-modulo.sig"
ORIGINE = ".adabox-origine.json"           # nella cartella del modulo caricato: da dove viene
FORMATO = 1
MAX_DECOMPRESSO = 100 * 1024 * 1024
MAX_FILE = 5000


class PacchettoNonValido(Exception):
    def __init__(self, errori):
        self.errori = [errori] if isinstance(errori, str) else list(errori)
        super().__init__("; ".join(self.errori))


# --- chiavi e firme ---------------------------------------------------------------

def genera_chiavi():
    """(chiave privata PEM, chiave pubblica in base64)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    privata = Ed25519PrivateKey.generate()
    pem = privata.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    return pem, pubblica_b64(privata)


def carica_privata(percorso):
    from cryptography.hazmat.primitives import serialization
    return serialization.load_pem_private_key(Path(percorso).read_bytes(), password=None)


def pubblica_b64(privata):
    from cryptography.hazmat.primitives import serialization
    grezza = privata.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(grezza).decode()


def impronta(pub_b64):
    """Impronta leggibile di una chiave pubblica (16 cifre esadecimali a gruppi di 4)."""
    h = hashlib.sha256(base64.b64decode(pub_b64)).hexdigest()[:16]
    return ":".join(h[i:i + 4] for i in range(0, 16, 4))


def firma(dati, privata):
    return base64.b64encode(privata.sign(dati))


def verifica(dati, firma_b64, fidate):
    """La chiave pubblica (base64) tra le fidate che ha firmato `dati`, o None."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        firma_grezza = base64.b64decode(firma_b64, validate=True)
    except (ValueError, TypeError):
        return None
    for pub in fidate:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(firma_grezza, dati)
            return pub
        except (InvalidSignature, ValueError):
            continue
    return None


def chiavi_fidate():
    return [c.strip() for c in settings.MODULI_CHIAVI_FIDATE if c.strip()]


# --- impacchettamento -----------------------------------------------------------------

def _escluso(rel):
    parti = PurePosixPath(rel).parts
    return any(p == "__pycache__" or p.startswith(".") for p in parti) or rel.endswith(".pyc")


def _sha256(percorso):
    h = hashlib.sha256()
    with open(percorso, "rb") as f:
        for blocco in iter(lambda: f.read(65536), b""):
            h.update(blocco)
    return h.hexdigest()


def file_del_modulo(cartella):
    cartella = Path(cartella)
    return sorted(p.relative_to(cartella).as_posix() for p in cartella.rglob("*")
                  if p.is_file() and not p.is_symlink() and not _escluso(p.relative_to(cartella).as_posix()))


def descrivi(cartella):
    """La descrizione del pacchetto: dati del manifest e SHA-256 di ogni file."""
    cartella = Path(cartella)
    m = manifest.leggi(cartella)
    return {"formato": FORMATO, "slug": m.slug, "versione": m.version, "nome": m.name, "min_core": m.min_core,
            "creato": timezone.now().isoformat(timespec="seconds"),
            "file": {rel: _sha256(cartella / rel) for rel in file_del_modulo(cartella)}}


def serializza(descrizione):
    """JSON canonico: è questo che si firma."""
    return json.dumps(descrizione, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def impacchetta(cartella, uscita, privata=None):
    """Crea <uscita>/<slug>-<versione>.zip; firmato se si passa la chiave privata."""
    cartella = Path(cartella)
    descrizione = descrivi(cartella)
    dati = serializza(descrizione)
    uscita = Path(uscita)
    uscita.mkdir(parents=True, exist_ok=True)
    destinazione = uscita / f"{descrizione['slug']}-{descrizione['versione']}.zip"
    with zipfile.ZipFile(destinazione, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in descrizione["file"]:
            z.write(cartella / rel, f"{descrizione['slug']}/{rel}")
        z.writestr(DESCRIZIONE, dati)
        if privata is not None:
            z.writestr(FIRMA, firma(dati, privata))
    return destinazione


# --- controllo e caricamento -----------------------------------------------------------

@dataclass
class Esito:
    slug: str
    versione: str
    nome: str
    firmato_da: str = ""                 # impronta della chiave, vuota se non firmato
    avvisi: list = field(default_factory=list)
    cartella: Path | None = None         # estratto in una cartella temporanea dopo i controlli


def _nome_sicuro(nome):
    """Percorso relativo, con le barre di zip, senza risalite né lettere di unità (C:)."""
    parti = PurePosixPath(nome).parts
    if not parti or nome.startswith("/") or "\\" in nome:
        return False
    return ":" not in parti[0] and ".." not in parti


def controlla(percorso_zip):
    """Tutti i controlli della spec; se passano, estrae il modulo in una cartella temporanea (Esito.cartella)."""
    percorso_zip = Path(percorso_zip)
    if percorso_zip.stat().st_size > settings.MODULI_ZIP_MAX_MB * 1024 * 1024:
        raise PacchettoNonValido(f"il pacchetto supera {settings.MODULI_ZIP_MAX_MB} MB")
    try:
        z = zipfile.ZipFile(percorso_zip)
    except zipfile.BadZipFile:
        raise PacchettoNonValido("non è un file zip valido")
    with z:
        voci = z.infolist()
        if len(voci) > MAX_FILE:
            raise PacchettoNonValido(f"troppi file nel pacchetto ({len(voci)})")
        if sum(v.file_size for v in voci) > MAX_DECOMPRESSO:
            raise PacchettoNonValido("il contenuto decompresso è troppo grande")
        errori = []
        for v in voci:
            if not _nome_sicuro(v.filename):
                errori.append(f"percorso non ammesso: {v.filename!r}")
            if stat.S_ISLNK(v.external_attr >> 16):
                errori.append(f"link simbolico non ammesso: {v.filename!r}")
        if errori:
            raise PacchettoNonValido(errori)
        nomi = {v.filename for v in voci}
        if DESCRIZIONE not in nomi:
            raise PacchettoNonValido(f"manca {DESCRIZIONE}: non è un pacchetto di modulo")
        dati = z.read(DESCRIZIONE)
        try:
            descrizione = json.loads(dati)
        except ValueError:
            raise PacchettoNonValido(f"{DESCRIZIONE} non è JSON valido")
        if descrizione.get("formato") != FORMATO:
            raise PacchettoNonValido(f"formato del pacchetto {descrizione.get('formato')!r} non supportato")
        slug = descrizione.get("slug", "")
        file_zip = {v.filename for v in voci if not v.is_dir()} - {DESCRIZIONE, FIRMA}
        radici = {n.split("/", 1)[0] for n in file_zip}
        if radici != {slug}:
            raise PacchettoNonValido(f"il pacchetto deve contenere solo la cartella {slug!r} (trovate: {sorted(radici)})")
        dichiarati = descrizione.get("file") or {}
        presenti = {n[len(slug) + 1:] for n in file_zip}
        if presenti != set(dichiarati):
            raise PacchettoNonValido("i file del pacchetto non corrispondono alla descrizione")
        for rel, atteso in dichiarati.items():
            if hashlib.sha256(z.read(f"{slug}/{rel}")).hexdigest() != atteso:
                errori.append(f"file alterato: {rel}")
        if errori:
            raise PacchettoNonValido(errori)

        avvisi, firmato_da = [], ""
        if FIRMA in nomi:
            chiave = verifica(dati, z.read(FIRMA), chiavi_fidate())
            if chiave is None:
                raise PacchettoNonValido("firma non valida o di una chiave non fidata")
            firmato_da = impronta(chiave)
        elif settings.MODULI_FIRMA_OBBLIGATORIA:
            raise PacchettoNonValido("pacchetto non firmato: su questa istanza la firma è obbligatoria")
        else:
            avvisi.append("pacchetto non firmato")

        temporanea = Path(tempfile.mkdtemp(prefix="modulo-", dir=_cartella_lavoro()))
        for v in voci:
            if v.filename.startswith(f"{slug}/") and not v.is_dir():
                destinazione = temporanea / v.filename
                destinazione.parent.mkdir(parents=True, exist_ok=True)
                destinazione.write_bytes(z.read(v))
    try:
        m = manifest.leggi(temporanea / slug)
    except manifest.ManifestNonValido as e:
        shutil.rmtree(temporanea, ignore_errors=True)
        raise PacchettoNonValido(e.errori)
    if m.version != descrizione.get("versione"):
        shutil.rmtree(temporanea, ignore_errors=True)
        raise PacchettoNonValido("la versione della descrizione non corrisponde al manifest")
    return Esito(slug=slug, versione=m.version, nome=m.name, firmato_da=firmato_da, avvisi=avvisi,
                 cartella=temporanea / slug)


def _cartella_lavoro():
    """Accanto ad addons/, così lo spostamento finale è un rename sullo stesso disco."""
    cartella = Path(settings.ADDONS_DIR).parent / ".moduli-in-arrivo"
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella


def archivia(cartella, versione):
    """Copia zip della cartella di un modulo in backup/moduli/<slug>-<versione>.zip."""
    destinazione = Path(settings.BACKUP_DIR) / "moduli"
    destinazione.mkdir(parents=True, exist_ok=True)
    base = destinazione / f"{Path(cartella).name}-{versione}-{timezone.localtime():%Y%m%d-%H%M%S}"
    return Path(shutil.make_archive(str(base), "zip", root_dir=Path(cartella).parent, base_dir=Path(cartella).name))


def carica(percorso_zip, forza=False, nome_pacchetto=""):
    """Controlla il pacchetto ed estrae il modulo in addons/ (senza installarlo). Una versione minore di quella
    presente non si carica; una uguale solo con `forza`. La cartella precedente si archivia in backup/moduli/."""
    from core.registry import modules
    esito = controlla(percorso_zip)
    temporanea = esito.cartella.parent
    try:
        destinazione = Path(settings.ADDONS_DIR) / esito.slug
        if destinazione.exists():
            try:
                attuale = manifest.leggi(destinazione).version
            except manifest.ManifestNonValido:
                attuale = None
            if attuale is not None:
                nuova, vecchia = manifest.versione_tupla(esito.versione), manifest.versione_tupla(attuale)
                if nuova < vecchia:
                    raise PacchettoNonValido(f"{esito.slug}: presente la {attuale}, il pacchetto è la {esito.versione}")
                if nuova == vecchia and not forza:
                    raise PacchettoNonValido(f"{esito.slug} {attuale} è già presente (usa --forza per sostituirlo)")
            archivia(destinazione, attuale or "sconosciuta")
            shutil.rmtree(destinazione)
        (esito.cartella / ORIGINE).write_text(json.dumps({
            "firmato_da": esito.firmato_da, "pacchetto": nome_pacchetto or Path(percorso_zip).name,
            "caricato": timezone.now().isoformat(timespec="seconds")}, ensure_ascii=False))
        shutil.move(str(esito.cartella), str(destinazione))
    finally:
        shutil.rmtree(temporanea, ignore_errors=True)
    modules.sincronizza()
    return esito


def origine(cartella):
    """Provenienza di un modulo in addons/: {"firmato_da", "pacchetto", "caricato"} o None (cartella locale)."""
    percorso = Path(cartella) / ORIGINE
    try:
        return json.loads(percorso.read_text())
    except (OSError, ValueError):
        return None
