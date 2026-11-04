"""Il lavoro del portale: pubblicare i pacchetti, calcolare che cosa spetta a un'istanza, firmarle licenza e catalogo.

Dei moduli non compresi nella licenza il catalogo porta solo la descrizione: il pacchetto si scarica solo se la licenza
lo copre, con il token dell'istanza."""
import ast
import base64
import hashlib
import shutil
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.urls import reverse
from django.utils import timezone

from core import licenza
from core.registry import pacchetti

from .models import Istanza, ModuloVendibile, Pacchetto, Richiesta


class ChiaveMancante(Exception):
    pass


def chiave_privata():
    if not settings.MODULI_CHIAVE_PRIVATA:
        raise ChiaveMancante("Imposta MODULI_CHIAVE_PRIVATA: serve a firmare licenze e cataloghi.")
    return pacchetti.carica_privata(settings.MODULI_CHIAVE_PRIVATA)


def _icona(percorso_zip, slug, m):
    """L'icona del manifest come data URI: il cliente la vede senza avere il modulo."""
    icona = m.get("icon") or ""
    if not icona.endswith(".svg") or "/" not in icona:
        return ""
    try:
        with zipfile.ZipFile(percorso_zip) as z:
            dati = z.read(f"{slug}/static/{icona}")
    except KeyError:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(dati).decode() if len(dati) <= 20000 else ""


def pubblica(percorso_zip, nome_file=""):
    """Controlla un pacchetto firmato e lo mette in vendita; la stessa versione si sostituisce. Restituisce il Pacchetto."""
    percorso_zip = Path(percorso_zip)
    esito = pacchetti.controlla(percorso_zip)
    shutil.rmtree(esito.cartella.parent, ignore_errors=True)
    if not esito.firmato_da:
        raise pacchetti.PacchettoNonValido("sul portale vanno solo pacchetti firmati: le istanze rifiuterebbero gli altri")
    with zipfile.ZipFile(percorso_zip) as z:
        m = ast.literal_eval(z.read(f"{esito.slug}/__manifest__.py").decode("utf-8"))
    modulo, _ = ModuloVendibile.objects.update_or_create(slug=esito.slug, defaults={
        "nome": m.get("nav_label") or m.get("name", esito.slug), "riassunto": (m.get("summary") or "")[:300], "categoria": m.get("category", ""),
        "application": bool(m.get("application")), "icona": _icona(percorso_zip, esito.slug, m)})
    nome = nome_file or percorso_zip.name
    p = Pacchetto.objects.filter(modulo=modulo, versione=esito.versione).first() or Pacchetto(modulo=modulo, versione=esito.versione)
    if p.pk and p.file:
        p.file.delete(save=False)
    p.min_core, p.dipendenze, p.nome_file = m.get("min_core", ""), m.get("depends", []), nome
    p.sha256 = hashlib.sha256(percorso_zip.read_bytes()).hexdigest()
    p.dimensione, p.pubblicato = percorso_zip.stat().st_size, True
    with open(percorso_zip, "rb") as f:
        p.file.save(nome, File(f), save=False)
    p.save()
    return p


def moduli_di(istanza):
    """Gli slug che spettano all'istanza: piano, moduli in più e, a cascata, le dipendenze dei loro pacchetti."""
    da_vedere = set(istanza.piano.moduli.values_list("slug", flat=True)) | set(istanza.moduli_extra.values_list("slug", flat=True))
    visti = set()
    while da_vedere:
        slug = da_vedere.pop()
        visti.add(slug)
        modulo = ModuloVendibile.objects.filter(slug=slug).first()
        ultimo = modulo.ultimo() if modulo else None
        if ultimo:
            da_vedere |= set(ultimo.dipendenze) - visti
    return visti


def licenza_di(istanza):
    utenti = istanza.utenti if istanza.utenti is not None else istanza.piano.utenti
    return licenza.firma({"cliente": istanza.cliente, "istanza": str(istanza.codice), "piano": istanza.piano.nome, "utenti": utenti,
                          "moduli": sorted(moduli_di(istanza)), "scadenza": istanza.scadenza.isoformat(), "grazia_giorni": istanza.grazia_giorni,
                          "emessa": timezone.now().isoformat(timespec="seconds")}, chiave_privata())


def catalogo_di(istanza, base_url):
    """Il catalogo di questa istanza: i moduli licenziati con il loro pacchetto, tutti gli altri solo descritti."""
    spettanti = moduli_di(istanza)
    voci, disponibili = [], []
    for m in ModuloVendibile.objects.all():
        descrizione = {"slug": m.slug, "nome": m.nome, "riassunto": m.riassunto, "categoria": m.categoria, "application": m.application, "icona": m.icona}
        ultimo = m.ultimo()
        if m.slug in spettanti and ultimo:
            voci.append({**descrizione, "versione": ultimo.versione, "min_core": ultimo.min_core, "dipendenze": ultimo.dipendenze, "file": ultimo.nome_file,
                         "url": base_url + reverse("rivendita:api_pacchetto", args=[m.slug, ultimo.versione]), "sha256": ultimo.sha256})
        elif m.slug not in spettanti and m.in_catalogo and m.application and ultimo:
            disponibili.append(descrizione)
    dati = {"formato": 1, "istanza": str(istanza.codice), "creato": timezone.now().isoformat(timespec="seconds"), "moduli": voci, "disponibili": disponibili}
    return dati, pacchetti.firma(pacchetti.serializza(dati), chiave_privata()).decode()


def ricevi_richieste(istanza, voci):
    """Le richieste arrivate dall'istanza: una per modulo finché è aperta. Restituisce gli id locali ricevuti."""
    ricevute = []
    for v in voci or []:
        slug = str(v.get("slug", ""))[:31]
        if not slug:
            continue
        if not Richiesta.objects.filter(istanza=istanza, slug=slug, stato=Richiesta.NUOVA).exists():
            Richiesta.objects.create(istanza=istanza, slug=slug, nome=str(v.get("nome") or slug)[:120], nota=str(v.get("nota") or "")[:2000],
                                     utente=str(v.get("utente") or "")[:150], id_remoto=v.get("id") if isinstance(v.get("id"), int) else None)
        if isinstance(v.get("id"), int):
            ricevute.append(v["id"])
    return ricevute


def rifiutate(istanza):
    """I moduli la cui ultima richiesta è stata rifiutata: l'istanza lo mostra all'amministratore."""
    aperte = set(Richiesta.objects.filter(istanza=istanza, stato=Richiesta.NUOVA).values_list("slug", flat=True))
    return sorted(set(Richiesta.objects.filter(istanza=istanza, stato=Richiesta.RIFIUTATA).values_list("slug", flat=True)) - aperte)


def istanze_attive():
    return Istanza.objects.filter(attiva=True)
