"""Collaudo di un modulo: installazione vergine con le dipendenze in un'istanza usa e getta, test, disinstallazione."""
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from . import modules

TIMEOUT_PASSO = 900


@dataclass
class Risultato:
    slug: str
    ok: bool
    passi: list = field(default_factory=list)          # [(nome del passo, ok)]
    dettaglio: str = ""                                # coda dell'output del passo fallito


def da_collaudare(slugs=None):
    """Gli slug in ordine di dipendenze (tutti quelli con manifest valido se `slugs` è vuoto)."""
    info = {s: i for s, i in modules.scopri().items() if i.manifest is not None}
    scelti = list(slugs) if slugs else list(info)
    mancanti = [s for s in scelti if s not in info]
    if mancanti:
        raise ValueError(f"moduli non trovati o con manifest non valido: {', '.join(mancanti)}")
    return modules.ordina(scelti, info), info


def _chiusura(slug, info):
    visti, da_vedere = [], [slug]
    while da_vedere:
        s = da_vedere.pop()
        if s not in visti:
            visti.append(s)
            da_vedere.extend(modules.dipendenze(s, info))
    return visti


def collauda(slug, info):
    """Istanza temporanea con `slug` e le sue dipendenze: migrate, installa --demo, test del modulo,
    disinstalla --elimina-dati. Ogni passo è un processo nuovo, come in produzione."""
    risultato = Risultato(slug=slug, ok=True)
    base = Path(settings.BASE_DIR)
    with tempfile.TemporaryDirectory(prefix=f"collaudo-{slug}-") as tmp:
        tmp = Path(tmp)
        addons = tmp / "addons"
        moduli = _chiusura(slug, info)
        for s in moduli:
            shutil.copytree(info[s].cartella, addons / s, ignore=shutil.ignore_patterns("__pycache__", ".adabox-origine.json"))
        env = {**os.environ, "ADDONS_DIR": str(addons), "DATABASE_URL": f"sqlite:///{tmp / 'db.sqlite3'}",
               "BACKUP_DIR": str(tmp / "backup"), "RELOAD_STRATEGY": "none", "DEBUG": "True",
               "LAVORI_SINCRONI": "True", "AI_TURNI_SINCRONI": "True", "AI_LICENZA_SVILUPPO": "True", "PRIVATE_MEDIA_ROOT": str(tmp / "private")}
        env.pop("ADDONS_FORCE", None)
        manage = [sys.executable, str(base / "manage.py")]
        passi = [("migrate", manage + ["migrate", "--noinput"], env),
                 ("installa", manage + ["modulo", "installa", slug, "--demo", "--si"], env),
                 ("migrazioni", manage + ["makemigrations", slug, "--check", "--dry-run"], env)]
        test = addons / slug / "tests"
        if test.is_dir():
            # i test girano su un DB di test proprio, con le fixture condivise del progetto (conftest.py copiato
            # alla radice dell'istanza) e ADDONS_FORCE che carica il modulo e le sue dipendenze
            shutil.copy(base / "conftest.py", addons / "conftest.py")
            passi.append(("test", [sys.executable, "-m", "pytest", str(test), "-q", "-m", "not slow",
                                   "-c", str(base / "pytest.ini"), "--rootdir", str(addons), "-p", "no:cacheprovider",
                                   "--disable-warnings",            # nel dettaglio servono i test falliti, non gli avvisi
                                   "-o", f"env=ADDONS_FORCE={','.join(reversed(moduli))}"], env))
        passi.append(("disinstalla", manage + ["modulo", "disinstalla", slug, "--elimina-dati", "--si"], env))
        for nome, comando, ambiente in passi:
            try:
                esito = subprocess.run(comando, cwd=base, env=ambiente, capture_output=True, text=True,
                                       timeout=TIMEOUT_PASSO)
                riuscito, uscita = esito.returncode == 0, esito.stdout + esito.stderr
            except subprocess.TimeoutExpired:
                riuscito, uscita = False, f"tempo scaduto ({TIMEOUT_PASSO} s)"
            risultato.passi.append((nome, riuscito))
            if not riuscito:
                risultato.ok, risultato.dettaglio = False, uscita[-3000:]
                break
    return risultato


# --- compatibilità: il modulo accanto agli altri ---

def _istanza(tmp, moduli, info):
    """Una cartella addons con i moduli dati e l'ambiente per lavorarci. Il database è suo: niente esce da lì."""
    addons = tmp / "addons"
    for s in moduli:
        shutil.copytree(info[s].cartella, addons / s, ignore=shutil.ignore_patterns("__pycache__", ".adabox-origine.json"), symlinks=True)
    env = {**os.environ, "ADDONS_DIR": str(addons), "DATABASE_URL": f"sqlite:///{tmp / 'db.sqlite3'}", "BACKUP_DIR": str(tmp / "backup"),
           "RELOAD_STRATEGY": "none", "DEBUG": "True", "LAVORI_SINCRONI": "True", "AI_TURNI_SINCRONI": "True", "AI_LICENZA_SVILUPPO": "True",
           "PRIVATE_MEDIA_ROOT": str(tmp / "privato"), "MEDIA_ROOT": str(tmp / "media")}
    env.pop("ADDONS_FORCE", None)
    return env


def _accanto(slug, altro, info):
    """Istanza vuota con il modulo e un altro (con le dipendenze di entrambi). (nome, errore o None)."""
    etichetta = altro or "tutti"
    moduli = sorted(set(_chiusura(slug, info)) | set(_chiusura(altro, info) if altro else info))
    manage = [sys.executable, str(Path(settings.BASE_DIR) / "manage.py")]
    with tempfile.TemporaryDirectory(prefix=f"compat-{slug}-") as tmp:
        tmp = Path(tmp)
        env = _istanza(tmp, moduli, info)
        for comando in (["migrate", "--noinput"], ["modulo", "installa", *(sorted({slug, altro}) if altro else moduli), "--si"], ["modulo", "sonda", slug]):
            try:
                esito = subprocess.run(manage + comando, cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=TIMEOUT_PASSO)
            except subprocess.TimeoutExpired:
                return etichetta, f"tempo scaduto in «{comando[0]}»"
            if esito.returncode != 0:
                return etichetta, f"«{' '.join(comando[:2])}»: {(esito.stdout + esito.stderr)[-1200:]}"
    return etichetta, None


def compatibilita(slug, altri=None, paralleli=4):
    """[(altro modulo, errore o None)]: il modulo accanto a ciascuno degli altri e, se non si sceglie, a tutti insieme."""
    from concurrent.futures import ThreadPoolExecutor
    info = {s: i for s, i in modules.scopri().items() if i.manifest is not None}
    if slug not in info:
        raise ValueError(f"modulo {slug} non trovato o con manifest non valido")
    voci = list(altri) if altri else [s for s in sorted(info) if s != slug] + [None]
    if mancanti := [s for s in voci if s is not None and s not in info]:
        raise ValueError(f"moduli non trovati: {', '.join(mancanti)}")
    with ThreadPoolExecutor(max_workers=paralleli) as pool:
        return list(pool.map(lambda a: _accanto(slug, a, info), voci))


def sonda(slug):
    """Dentro un'istanza di prova: apre le pagine dei menu di tutti i moduli attivi e dice se il modulo si vede da Ada.
    Restituisce gli errori. Crea un utente: da usare solo nelle istanze usa e getta."""
    from django.apps import apps
    from django.contrib.auth.models import User
    from django.test import Client
    from django.test.utils import override_settings
    from django.urls import NoReverseMatch, reverse

    from core.models import Azienda
    azienda = Azienda.objects.first() or Azienda.objects.create(nome="Prova")
    utente = User.objects.create_superuser("sonda-compatibilita", "sonda@example.com", "x")
    utente.profilo.aziende.set([azienda])
    utente.profilo.azienda_predefinita = azienda
    utente.profilo.save()
    client, errori, urls = Client(raise_request_exception=False), [], ["/"]
    client.force_login(utente)
    for s in settings.ADDONS_ATTIVI:
        for voce in modules.scopri()[s].manifest.menu:
            try:
                urls.append(reverse(voce["url_name"]))
            except NoReverseMatch:
                errori.append(f"{s}: menu verso {voce['url_name']}, che non esiste")
    with override_settings(ALLOWED_HOSTS=["*"], SECURE_SSL_REDIRECT=False):
        for url in urls:
            if (stato := client.get(url, follow=True).status_code) >= 500:
                errori.append(f"{url}: errore {stato}")
    if apps.is_installed("ai"):
        from ai.strumenti.registro import Contesto
        from ai.strumenti.viste import id_vista, viste
        from core.viste import registry
        nomi = {id_vista(v) for v in viste(Contesto(utente=utente, azienda=azienda))}
        errori += [f"Ada non vede {id_vista(v)}" for v in registry.viste_di(slug) if id_vista(v) not in nomi]
    return errori
