"""Il lavoro del portale: pubblicare i pacchetti, calcolare che cosa spetta a un'istanza, firmarle licenza e catalogo.

Dei moduli non compresi nella licenza il catalogo porta solo la descrizione: il pacchetto si scarica solo se la licenza
lo copre, con il token dell'istanza."""
import ast
import base64
import datetime
import hashlib
import shutil
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.urls import reverse
from django.utils import timezone

from core import licenza
from core.registry import pacchetti

from .models import AI_CONSUMO, AI_INCLUSA, AI_PROPRIA, ConsumoAI, FunzioneVendibile, Istanza, ModuloVendibile, Pacchetto, Richiesta, Suite
from .schede import SCHEDE


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
    su_misura = m.get("su_misura") is True
    # un modulo su misura non compare mai agli altri, nemmeno per un attimo; poi lo decide il portale
    modulo, _ = ModuloVendibile.objects.update_or_create(slug=esito.slug, create_defaults={
        "su_misura": su_misura, "in_catalogo": not su_misura, "nome": m.get("nav_label") or m.get("name", esito.slug),
        "riassunto": (m.get("summary") or "")[:300], "categoria": m.get("category", "")[:60], "application": bool(m.get("application")),
        "icona": _icona(percorso_zip, esito.slug, m)}, defaults={
        "nome": m.get("nav_label") or m.get("name", esito.slug), "riassunto": (m.get("summary") or "")[:300], "categoria": m.get("category", ""),
        "application": bool(m.get("application")), "icona": _icona(percorso_zip, esito.slug, m)})
    applica_scheda(modulo)
    allinea_funzioni(modulo, m.get("funzioni") or [])
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


def applica_scheda(modulo):
    """La scheda di partenza, solo se sul portale non ne è stata scritta una."""
    descrizione, funzioni = SCHEDE.get(modulo.slug, ("", []))
    if descrizione and not modulo.descrizione:
        modulo.descrizione, modulo.funzioni = descrizione, "\n".join(funzioni)
        modulo.save(update_fields=["descrizione", "funzioni"])


def allinea_funzioni(modulo, voci):
    """Le funzioni attivabili del modulo come nel manifest del pacchetto: quelle tolte spariscono anche dai piani."""
    chiavi = []
    for ordine, v in enumerate(voci):
        if isinstance(v, dict) and isinstance(v.get("chiave"), str) and v["chiave"]:
            FunzioneVendibile.objects.update_or_create(modulo=modulo, chiave=v["chiave"], defaults={
                "nome": str(v.get("label") or v["chiave"])[:120], "spiegazione": str(v.get("help") or "")[:300], "ordine": ordine})
            chiavi.append(v["chiave"])
    modulo.funzioni_attivabili.exclude(chiave__in=chiavi).delete()


def funzioni_di(istanza, moduli):
    """{slug: [chiavi]} per la licenza: dei moduli che il piano ha «a funzioni scelte», quelle del piano più quelle in più
    dell'istanza. Gli altri moduli non compaiono, e sull'istanza hanno tutte le funzioni."""
    ristretti = set(istanza.piano.moduli_a_funzioni.values_list("slug", flat=True)) & set(moduli)
    risultato = {slug: set() for slug in ristretti}
    for qs in (istanza.piano.funzioni, istanza.funzioni_extra):
        for slug, chiave in qs.filter(modulo__slug__in=ristretti).values_list("modulo__slug", "chiave"):
            risultato[slug].add(chiave)
    return {slug: sorted(chiavi) for slug, chiavi in sorted(risultato.items())}


def moduli_di(istanza):
    """Gli slug che spettano all'istanza: piano, suite, moduli in più e, a cascata, le dipendenze dei loro pacchetti."""
    da_vedere = (set(istanza.piano.moduli.filter(su_misura=False).values_list("slug", flat=True)) | set(istanza.moduli_extra.values_list("slug", flat=True))
                 | set(ModuloVendibile.objects.filter(suite__istanze=istanza, su_misura=False).values_list("slug", flat=True)))
    visti = set()
    while da_vedere:
        slug = da_vedere.pop()
        visti.add(slug)
        modulo = ModuloVendibile.objects.filter(slug=slug).first()
        ultimo = modulo.ultimo() if modulo else None
        if ultimo:
            da_vedere |= set(ultimo.dipendenze) - visti
    return visti


def suite_di(istanza):
    """Le suite comprate, come vanno in licenza: le loro app (solo quelle che sono app) e il tetto di persone."""
    return [{"slug": su.slug, "nome": su.nome, "utenti": su.utenti,
             "moduli": sorted(su.moduli.filter(application=True, su_misura=False).values_list("slug", flat=True))}
            for su in istanza.suite.order_by("ordine", "nome")]


def comuni_di(istanza):
    """Le app del piano base: sull'istanza sono comuni a tutti i dipartimenti."""
    return sorted(istanza.piano.moduli.filter(application=True, su_misura=False).values_list("slug", flat=True))


def licenza_di(istanza):
    utenti = istanza.utenti if istanza.utenti is not None else istanza.piano.utenti
    dati = {"cliente": istanza.cliente, "istanza": str(istanza.codice), "piano": istanza.piano.nome, "utenti": utenti,
            "moduli": sorted(moduli_di(istanza)), "scadenza": istanza.scadenza.isoformat(), "grazia_giorni": istanza.grazia_giorni,
            "emessa": timezone.now().isoformat(timespec="seconds")}
    suite = suite_di(istanza)
    if suite:                                          # senza suite la licenza resta com'era: le istanze vecchie la leggono uguale
        dati.update(suite=suite, comuni=comuni_di(istanza))
    if funzioni := funzioni_di(istanza, dati["moduli"]):   # come sopra: senza restrizioni la chiave non c'è
        dati["funzioni"] = funzioni
    if ai := ai_di(istanza):                               # come sopra: con la chiave del cliente la chiave non c'è
        dati["ai"] = ai
    return licenza.firma(dati, chiave_privata())


def ai_di(istanza):
    """I termini dell'assistente per la licenza (li legge ai.licenza sull'istanza): la formula e le quote in dollari.
    Con la chiave del cliente niente: non c'è nulla da far rispettare. Il ricarico resta sul portale."""
    termini = istanza.termini_ai()
    if termini["formula"] == AI_PROPRIA:
        return None
    quota_utente = termini["quota_utente"] if termini["formula"] == AI_INCLUSA else Decimal(0)
    return {"formula": termini["formula"], "quota_utente": str(quota_utente), "quota_istanza": str(termini["quota_istanza"])}


def cambio():
    """Euro per un dollaro: i costi dei modelli sono in dollari, gli importi al cliente in euro."""
    from core import parametri
    return parametri.leggi("rivendita.cambio_usd_eur") or Decimal(1)


def quota_ai(istanza, termini):
    """La quota del mese in dollari con cui confrontare il consumo: quella dell'istanza o, con «inclusa» e senza quella,
    la somma delle quote per utente. 0 = senza quota."""
    if termini["quota_istanza"] or termini["formula"] != AI_INCLUSA:
        return termini["quota_istanza"]
    return termini["quota_utente"] * istanza.posti()


def importo_ai(costo_fornito, termini):
    """Che cosa si fattura per l'assistente, in euro: solo con «a consumo», il costo sul piano più il ricarico."""
    if termini["formula"] != AI_CONSUMO:
        return Decimal(0)
    return (costo_fornito * cambio() * (1 + termini["ricarico"] / 100)).quantize(Decimal("0.01"))


def _decimale(valore):
    try:
        numero = Decimal(str(valore))
    except InvalidOperation:
        return None
    return numero if numero.is_finite() and 0 <= numero < Decimal("1e6") else None


def _intero(valore):
    return valore if isinstance(valore, int) and not isinstance(valore, bool) and 0 <= valore < 2_000_000_000 else None


def ricevi_consumi_ai(istanza, voci, oggi=None):
    """I riepiloghi mensili mandati dall'istanza: una riga per mese, sostituita a ogni invio. Valgono solo il mese in
    corso e quello precedente: i mesi chiusi non si riscrivono. Restituisce i mesi registrati (AAAA-MM)."""
    questo = (oggi or timezone.localdate()).replace(day=1)
    ammessi = {f"{m:%Y-%m}": m for m in (questo, (questo - datetime.timedelta(days=1)).replace(day=1))}
    termini = istanza.termini_ai()
    registrati = []
    for v in voci or []:
        mese = ammessi.get(v.get("mese")) if isinstance(v, dict) and isinstance(v.get("mese"), str) else None
        costo, fornito = (_decimale(v.get(c)) for c in ("costo", "costo_fornito")) if mese else (None, None)
        turni, utenti = (_intero(v.get(c)) for c in ("turni", "utenti")) if mese else (None, None)
        if None in (mese, costo, fornito, turni, utenti) or fornito > costo:
            continue
        ConsumoAI.objects.update_or_create(istanza=istanza, mese=mese, defaults={
            "costo": costo, "costo_fornito": fornito, "turni": turni, "utenti": utenti, "formula": termini["formula"],
            "quota": quota_ai(istanza, termini), "importo": importo_ai(fornito, termini)})
        registrati.append(v["mese"])
    return registrati


def catalogo_di(istanza, base_url):
    """Il catalogo di questa istanza: i moduli licenziati con il loro pacchetto, tutti gli altri solo descritti."""
    spettanti = moduli_di(istanza)
    voci, disponibili = [], []
    for m in ModuloVendibile.objects.all():
        descrizione = {"slug": m.slug, "nome": m.nome, "riassunto": m.riassunto, "categoria": m.categoria, "application": m.application, "icona": m.icona,
                       "descrizione": m.descrizione, "funzioni": [r.strip() for r in m.funzioni.splitlines() if r.strip()],
                       "url_demo": m.url_demo or settings.RIVENDITA_URL_DEMO}
        ultimo = m.ultimo()
        if m.slug in spettanti and ultimo:
            voci.append({**descrizione, "versione": ultimo.versione, "min_core": ultimo.min_core, "dipendenze": ultimo.dipendenze, "file": ultimo.nome_file,
                         "url": base_url + reverse("rivendita:api_pacchetto", args=[m.slug, ultimo.versione]), "sha256": ultimo.sha256})
        elif m.slug not in spettanti and m.in_catalogo and not m.su_misura and m.application and ultimo:
            disponibili.append(descrizione)
    comprate = set(istanza.suite.values_list("pk", flat=True))
    suite = [{"slug": su.slug, "nome": su.nome, "descrizione": su.descrizione, "utenti": su.utenti, "comprata": su.pk in comprate,
              "moduli": [{"slug": m.slug, "nome": m.nome} for m in su.moduli.filter(application=True, su_misura=False).order_by("nome")]}
             for su in Suite.objects.prefetch_related("moduli") if su.in_catalogo or su.pk in comprate]
    dati = {"formato": 1, "istanza": str(istanza.codice), "creato": timezone.now().isoformat(timespec="seconds"), "moduli": voci, "disponibili": disponibili,
            "suite": suite}
    return dati, pacchetti.firma(pacchetti.serializza(dati), chiave_privata()).decode()


def ricevi_richieste(istanza, voci):
    """Le richieste arrivate dall'istanza: una per modulo finché è aperta. Restituisce gli id locali ricevuti."""
    ricevute = []
    for v in voci or []:
        slug = str(v.get("slug", ""))[:31]
        if not slug:
            continue
        if v.get("tipo") == Richiesta.SUITE:
            suite = Suite.objects.filter(slug=slug).first()
            if suite is not None and (suite.in_catalogo or istanza.suite.filter(pk=suite.pk).exists()) \
                    and not Richiesta.objects.filter(istanza=istanza, slug=slug, tipo=Richiesta.SUITE, stato=Richiesta.NUOVA).exists():
                Richiesta.objects.create(istanza=istanza, slug=slug, nome=suite.nome, nota=str(v.get("nota") or "")[:2000], tipo=Richiesta.SUITE,
                                         utente=str(v.get("utente") or "")[:150], id_remoto=v.get("id") if isinstance(v.get("id"), int) else None)
            if isinstance(v.get("id"), int):
                ricevute.append(v["id"])
            continue
        if ModuloVendibile.objects.filter(slug=slug, su_misura=True).exists():
            continue                                   # un modulo su misura non si chiede: non è in nessun catalogo
        tipo = Richiesta.DEMO if v.get("tipo") == Richiesta.DEMO else Richiesta.INSTALLAZIONE
        if not Richiesta.objects.filter(istanza=istanza, slug=slug, tipo=tipo, stato=Richiesta.NUOVA).exists():
            Richiesta.objects.create(istanza=istanza, slug=slug, nome=str(v.get("nome") or slug)[:120], nota=str(v.get("nota") or "")[:2000],
                                                 utente=str(v.get("utente") or "")[:150], id_remoto=v.get("id") if isinstance(v.get("id"), int) else None, tipo=tipo)
        if isinstance(v.get("id"), int):
            ricevute.append(v["id"])
    return ricevute


def rifiutate(istanza, tipo=Richiesta.INSTALLAZIONE):
    """I moduli (o le suite) la cui ultima richiesta è stata rifiutata: l'istanza lo mostra all'amministratore."""
    installazioni = Richiesta.objects.filter(istanza=istanza, tipo=tipo)
    aperte = set(installazioni.filter(stato=Richiesta.NUOVA).values_list("slug", flat=True))
    return sorted(set(installazioni.filter(stato=Richiesta.RIFIUTATA).values_list("slug", flat=True)) - aperte)


def istanze_attive():
    return Istanza.objects.filter(attiva=True)
