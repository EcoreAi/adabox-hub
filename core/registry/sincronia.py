"""L'istanza del cliente chiede al portale che cosa le spetta. Comunica lei, con il suo token: per installare un modulo a
un cliente basta aggiornarne la licenza sul portale, senza entrare nel suo server.

A ogni giro: riferisce versioni e richieste, riceve licenza e catalogo firmati per questa istanza, poi li applica.
Scarica e installa i moduli coperti, aggiorna quelli nuovi, disinstalla i revocati lasciando i dati e toglie dal disco
il codice che la licenza non copre. Una licenza scaduta non toglie nulla: lì basta la sola lettura. Se il portale non
risponde resta tutto com'è."""
import hashlib
import json
import logging
import shutil
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from core import licenza
from core.models import LicenzaIstanza, RichiestaModulo

from . import bootstrap, install, manifest, modules, pacchetti

log = logging.getLogger("core.moduli")
TIMEOUT = 30


class PortaleNonValido(Exception):
    """Portale irraggiungibile o risposta non valida: non si applica niente."""


def configurata():
    return bool(settings.LICENZA_PORTALE_URL and settings.LICENZA_TOKEN)


def _intestazioni():
    return {"Authorization": f"Bearer {settings.LICENZA_TOKEN}", "Content-Type": "application/json"}


def _chiama(percorso, dati=None, limite=5 * 1024 * 1024):
    """Byte della risposta del portale. `percorso` relativo all'URL del portale o assoluto (i pacchetti del catalogo)."""
    url = percorso if percorso.startswith(("http://", "https://")) else f"{settings.LICENZA_PORTALE_URL.rstrip('/')}/{percorso}"
    corpo = json.dumps(dati).encode() if dati is not None else None
    richiesta = urllib.request.Request(url, data=corpo, headers=_intestazioni(), method="POST" if corpo else "GET")
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
            contenuto = risposta.read(limite + 1)
    except urllib.error.HTTPError as e:
        raise PortaleNonValido(f"il portale ha risposto {e.code} a {percorso}")
    except (urllib.error.URLError, OSError) as e:
        raise PortaleNonValido(f"portale non raggiungibile: {e}")
    if len(contenuto) > limite:
        raise PortaleNonValido(f"{percorso}: risposta troppo grande")
    return contenuto


def _rapporto():
    versioni = {r["slug"]: r["versione_installata"] for r in
                modules.Modulo.objects.filter(slug__in=modules.installati()).values("slug", "versione_installata")}
    return {"moduli": versioni, "utenti_attivi": licenza.utenti_attivi(),
            "richieste": [{"id": r.pk, "slug": r.slug, "tipo": r.tipo, "nome": r.nome, "nota": r.nota, "utente": str(r.utente or "")}
                          for r in RichiestaModulo.objects.filter(stato=RichiestaModulo.INVIATA, consegnata=False)]}


def _verifica(risposta):
    """(testo della licenza, catalogo) da una risposta del portale: tutto firmato, e il catalogo è di questa licenza."""
    try:
        testo = json.dumps({"licenza": risposta["licenza"], "firma": risposta["firma"]})
        catalogo, firma_catalogo = risposta["catalogo"], risposta["firma_catalogo"]
    except (KeyError, TypeError):
        raise PortaleNonValido("risposta del portale incompleta")
    stato = licenza.leggi(testo)
    if not stato.valida:
        raise PortaleNonValido(stato.motivo)
    if pacchetti.verifica(pacchetti.serializza(catalogo), firma_catalogo, pacchetti.chiavi_fidate()) is None:
        raise PortaleNonValido("catalogo senza una firma valida di una chiave fidata")
    if catalogo.get("istanza") != stato.istanza:
        raise PortaleNonValido("il catalogo è di un'altra istanza")
    return testo, catalogo


def _aggiorna_richieste(stato, risposta):
    RichiestaModulo.objects.filter(stato=RichiestaModulo.INVIATA, slug__in=stato.moduli).update(stato=RichiestaModulo.EVASA)
    RichiestaModulo.objects.filter(stato=RichiestaModulo.INVIATA, slug__in=risposta.get("rifiutate") or []).update(stato=RichiestaModulo.RIFIUTATA)
    RichiestaModulo.objects.filter(pk__in=risposta.get("ricevute") or []).update(consegnata=True)


def _scarica(voce):
    """Porta in addons/ il pacchetto di una voce del catalogo: hash del catalogo, poi tutti i controlli del caricamento."""
    dati = _chiama(voce["url"], limite=settings.MODULI_ZIP_MAX_MB * 1024 * 1024)
    if hashlib.sha256(dati).hexdigest() != voce["sha256"]:
        raise pacchetti.PacchettoNonValido(f"{voce['slug']}: il file scaricato non corrisponde al catalogo")
    with tempfile.NamedTemporaryFile(suffix=".zip") as temporaneo:
        temporaneo.write(dati)
        temporaneo.flush()
        return pacchetti.carica(temporaneo.name, nome_pacchetto=voce.get("file", ""))


def _versione_su_disco(slug):
    cartella = Path(settings.ADDONS_DIR) / slug
    try:
        return manifest.leggi(cartella).version if cartella.exists() else None
    except manifest.ManifestNonValido:
        return None


def _togli_dal_disco(slug):
    """Il codice di un modulo non coperto se ne va; niente copia in backup/, se no resterebbe sul server."""
    cartella = Path(settings.ADDONS_DIR) / slug
    if bootstrap.SLUG_RE.match(slug) and (cartella / "__manifest__.py").is_file() and not cartella.is_symlink():
        shutil.rmtree(cartella)
        return True
    return False


def applica(stato, catalogo):
    """Allinea i moduli alla licenza. Un modulo che fallisce non ferma gli altri: {"fatti": [...], "errori": [...]}."""
    fatti, errori = [], []
    for voce in catalogo.get("moduli", []):
        presente = _versione_su_disco(voce["slug"])
        if presente and manifest.versione_tupla(presente) >= manifest.versione_tupla(voce["versione"]):
            continue
        if not manifest.core_compatibile(voce.get("min_core", "0")):
            errori.append(f"{voce['slug']}: richiede un kernel più recente ({voce.get('min_core')})")
            continue
        try:
            _scarica(voce)
            fatti.append(f"scaricato {voce['slug']} {voce['versione']}")
        except (PortaleNonValido, pacchetti.PacchettoNonValido) as e:
            errori.append(f"{voce['slug']}: {e}")
    modules.sincronizza()
    info = modules.scopri()

    # prima i revocati, dai dipendenti in giù: i dati restano e tornano se il modulo viene ricomprato
    revocati = [s for s in modules.installati() if s not in stato.moduli]
    for slug in reversed(modules.ordina(revocati, info) if all(s in info for s in revocati) else revocati):
        try:
            install.disinstalla(slug, riavvia=False)
            fatti.append(f"disinstallato {slug}")
        except install.ErroreInstallazione as e:
            errori.append(f"{slug}: {e}")
    for slug in sorted(set(info) - stato.moduli - set(modules.installati())):
        if _togli_dal_disco(slug):
            fatti.append(f"tolto dal disco {slug}")

    info = modules.scopri()
    mancanti = [s for s in sorted(stato.moduli) if s in info and s not in modules.installati()]
    if mancanti:
        try:
            fatti += [f"installato {s}" for s in install.installa(mancanti, riavvia=False)]
        except (install.ErroreInstallazione, manifest.ManifestNonValido) as e:
            errori.append(f"installazione di {', '.join(mancanti)}: {e}")
    try:
        fatti += [f"aggiornato {s}" for s in install.aggiorna(tutti=True, riavvia=False)]
    except install.NienteDaAggiornare:
        pass
    except install.ErroreInstallazione as e:
        errori.append(f"aggiornamento: {e}")
    if fatti:
        modules.sincronizza()
        install.ricarica()
    return {"fatti": fatti, "errori": errori}


def esegui():
    """Un giro completo (voce `cron` del kernel e bottone della pagina Moduli). None se l'istanza non ha un portale."""
    if not configurata():
        return None
    riga = LicenzaIstanza.objects.first() or LicenzaIstanza()
    try:
        risposta = json.loads(_chiama("sincronizza/", _rapporto()))
        testo, catalogo = _verifica(risposta)
        stato = licenza.salva(testo, catalogo)
    except (PortaleNonValido, ValueError) as e:
        riga.ultimo_errore = str(e)
        riga.save()
        log.warning("sincronizzazione col portale: %s", e)
        return {"fatti": [], "errori": [str(e)]}
    _aggiorna_richieste(stato, risposta)
    esito = {"fatti": [], "errori": []}
    if settings.LICENZA_APPLICA_AUTOMATICA and licenza.obbligatoria() and not stato.scaduta:
        esito = applica(stato, catalogo)
    LicenzaIstanza.objects.update(ultima_sincronia=timezone.now(), ultimo_errore="; ".join(esito["errori"])[:2000], ultimo_esito=esito["fatti"][:200])
    if esito["fatti"] or esito["errori"]:
        log.info("sincronizzazione col portale: %s", esito)
    return esito


esegui.senza_transazione = True      # backup e installazioni girano in altri processi: non devono attendere questo


def invia_richieste():
    """Consegna subito al portale le richieste dell'Admin; se non risponde, riparte col prossimo giro."""
    if not configurata():
        return 0
    try:
        risposta = json.loads(_chiama("sincronizza/", _rapporto()))
    except (PortaleNonValido, ValueError) as e:
        log.warning("richieste al portale: %s", e)
        return 0
    return RichiestaModulo.objects.filter(pk__in=risposta.get("ricevute") or []).update(consegnata=True)
