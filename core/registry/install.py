"""Installa, aggiorna e disinstalla moduli: backup, file di stato, sottoprocesso, ricarica."""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings

from core import backup
from core.models import Modulo

from . import bootstrap, modules, reload
from .manifest import ManifestNonValido

log = logging.getLogger("core.moduli")


class ErroreInstallazione(Exception): ...
class GiaInstallato(ErroreInstallazione): ...
class NonInstallato(ErroreInstallazione): ...
class NienteDaAggiornare(ErroreInstallazione): ...
class DipendentiInstallati(ErroreInstallazione): ...
class ApplicaFallita(ErroreInstallazione): ...


def scrivi_stato(slugs):
    """Scrittura atomica: file temporaneo e rename."""
    percorso = Path(settings.ADDONS_DIR) / "installed.json"
    tmp = percorso.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": bootstrap.SCHEMA, "installed": list(slugs)}, indent=2) + "\n")
    os.replace(tmp, percorso)


def _applica(operazione, slugs, **opzioni):
    """Esegue `manage.py modulo_applica <operazione> <slugs>` in un processo nuovo, che legge
    il file di stato aggiornato e quindi ha i moduli in INSTALLED_APPS. Log in logs/moduli.log."""
    cmd = [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "modulo_applica", operazione, *slugs]
    if opzioni.get("demo"):
        cmd.append("--demo")
    if opzioni.get("elimina_dati"):
        cmd.append("--elimina-dati")
    env = {**os.environ, "ADDONS_DIR": str(settings.ADDONS_DIR)}
    esito = subprocess.run(cmd, cwd=settings.BASE_DIR, env=env, capture_output=True, text=True)
    log.info("%s %s:\n%s%s", operazione, " ".join(slugs), esito.stdout, esito.stderr)
    if esito.returncode != 0:
        raise ApplicaFallita((esito.stderr or esito.stdout)[-4000:])


def _chiusura(slugs, info):
    """Gli slug dati più, ricorsivamente, le loro dipendenze."""
    visti, da_vedere = [], list(slugs)
    while da_vedere:
        s = da_vedere.pop()
        if s in visti:
            continue
        if s not in info:
            raise ManifestNonValido([f"modulo {s!r} non trovato in {settings.ADDONS_DIR}"])
        if info[s].manifest is None:
            raise ManifestNonValido([f"{s}: {info[s].errore}"])
        visti.append(s)
        da_vedere.extend(modules.dipendenze(s, info))
    return visti


def _segna_errore(slugs, info, errore):
    for s in slugs:
        m = info[s].manifest if s in info else None
        Modulo.objects.update_or_create(slug=s, defaults={
            "nome": m.name if m else s, "stato": Modulo.ERRORE, "ultimo_errore": errore})


def _ricarica(riavvia):
    if not riavvia:
        return False
    try:
        return reload.richiedi()
    except reload.RicaricaNonDisponibile as e:
        log.warning("%s", e)
        return False


def installa(slugs, demo=False, riavvia=False, conferma=None):
    """Installa gli slug e le dipendenze mancanti. `conferma(extra)` decide se installare anche
    le dipendenze non richieste. Restituisce gli slug installati ([] se non confermato)."""
    info = modules.scopri()
    attuali = modules.installati()
    richiesti = [s for s in slugs if s not in attuali]
    if not richiesti:
        raise GiaInstallato(f"già installati: {', '.join(slugs)}")
    piano = [s for s in modules.ordina(_chiusura(richiesti, info), info) if s not in attuali]
    extra = [s for s in piano if s not in richiesti]
    if extra and conferma and not conferma(extra):
        return []
    backup.esegui("pre-installa-" + "-".join(piano))
    scrivi_stato(modules.ordina(attuali + piano, info))
    try:
        _applica("installa", piano, demo=demo)
    except ApplicaFallita as e:
        scrivi_stato(attuali)
        _segna_errore(piano, info, str(e))
        raise
    log.info("installati: %s", ", ".join(piano))
    _ricarica(riavvia)
    return piano


def aggiorna(slugs=None, tutti=False, riavvia=False):
    """Aggiorna i moduli da_aggiornare (o in errore ma installati) tra gli slug dati, o tutti."""
    righe = {r.slug: r for r in modules.sincronizza()}
    attuali = modules.installati()
    candidati = attuali if tutti else list(slugs or [])
    for s in candidati:
        if s not in attuali:
            raise NonInstallato(f"{s} non è installato")
    piano = [s for s in candidati if s in righe and (
        righe[s].stato == Modulo.DA_AGGIORNARE or righe[s].stato == Modulo.ERRORE)]
    if not piano:
        raise NienteDaAggiornare("nessun modulo da aggiornare")
    info = modules.scopri()
    piano = modules.ordina(piano, info)
    backup.esegui("pre-aggiorna-" + "-".join(piano))
    try:
        _applica("aggiorna", piano)
    except ApplicaFallita as e:
        _segna_errore(piano, info, str(e))
        raise
    log.info("aggiornati: %s", ", ".join(piano))
    _ricarica(riavvia)
    return piano


def disinstalla(slug, elimina_dati=False, riavvia=False):
    """Rifiuta se altri moduli installati dipendono da `slug`. Lo stato si riscrive DOPO il
    sottoprocesso: per `migrate <slug> zero` il modulo deve essere ancora in INSTALLED_APPS."""
    attuali = modules.installati()
    if slug not in attuali:
        raise NonInstallato(f"{slug} non è installato")
    info = modules.scopri()
    dipendenti = [s for s in attuali if s != slug and slug in modules.dipendenze(s, info)]
    if dipendenti:
        raise DipendentiInstallati(f"{slug} è richiesto da: {', '.join(dipendenti)}")
    backup.esegui(f"pre-disinstalla-{slug}")
    try:
        _applica("disinstalla", [slug], elimina_dati=elimina_dati)
    except ApplicaFallita as e:
        _segna_errore([slug], info, str(e))
        raise
    scrivi_stato([s for s in attuali if s != slug])
    log.info("disinstallato: %s%s", slug, " (dati eliminati)" if elimina_dati else "")
    _ricarica(riavvia)
    return [slug]
