"""Un modulo nuovo, già funzionante: menu, lista, form, permessi, API, accesso da Ada e test. Si parte da qui e si
aggiunge la logica del cliente. Il risultato rispetta le regole di `modulo controlla` e passa `modulo collauda`."""
import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings

from .bootstrap import SLUG_RE
from .manifest import RISERVATI

CLASSE_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
ICONA = ('<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48" fill="none" stroke="#1e3a8a" '
         'stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="7" width="30" height="34" rx="5"/>'
         '<path d="M16 17h16M16 24h16M16 31h10"/></svg>\n')


class NomeNonValido(ValueError):
    pass


def _file(slug, nome, modello, depends, su_misura=True):
    vn = nome.lower()
    return {
        "__init__.py": "",
        "__manifest__.py": f'''{{
    "name": {nome!r},
    "summary": "",
    "version": "1.0.0",
    "author": "",
    "category": "Personalizzati",
    "depends": {depends!r},
    "min_core": "1.0",
    "application": True,{chr(10) + '    "su_misura": True,' if su_misura else ''}
    "icon": "{slug}/icon.svg",
    "menu": [
        {{"label": {nome!r}, "url_name": "{slug}:{slug}_lista", "permission": "{slug}.view_{modello.lower()}"}},
    ],
    "groups": {{
        "{nome} / Utente": ["{slug}.view_{modello.lower()}", "{slug}.add_{modello.lower()}", "{slug}.change_{modello.lower()}"],
        "{nome} / Responsabile": ["{slug}.*"],
    }},
}}
''',
        "apps.py": f'''from django.apps import AppConfig


class {modello}Config(AppConfig):
    name = "{slug}"
    verbose_name = {nome!r}
    default_auto_field = "django.db.models.BigAutoField"
''',
        "models.py": f'''"""I dati del modulo. AziendaMixin li separa per azienda: quasi tutti i modelli devono averlo."""
from django.db import models

from core.mixins import AziendaMixin


class {modello}(AziendaMixin):
    nome = models.CharField("nome", max_length=120)
    note = models.TextField("note", blank=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = {vn!r}
        verbose_name_plural = {vn!r}
        ordering = ["-pk"]

    def __str__(self):
        return self.nome
''',
        "views.py": f'''"""La vista: da qui nascono pagine, permessi, API, webhook e l'accesso di Ada. Vedi docs/guida-moduli.md."""
from core.viste import ModelView, register

from .models import {modello}


@register
class {modello}View(ModelView):
    model = {modello}
    slug = "{slug}"
    list_display = ["nome", "creato"]
    search_fields = ["nome", "note"]
    form_layout = [({nome!r}, ["nome", "note"])]
    readonly_fields = ["creato"]
    company_field = "azienda"                   # senza, i dati di un'azienda si vedrebbero dalle altre
    api = True
    # Scrivi che cosa contiene e come la chiamano gli utenti: tra molti moduli Ada sceglie la vista da qui.
    ai_descrizione = {nome!r}
''',
        "migrations/__init__.py": "",
        "tests/__init__.py": "",
        f"tests/test_{slug}.py": f'''"""Le garanzie di base del modulo: restano valide anche quando aggiungi la tua logica."""
import pytest
from django.contrib.auth.models import Permission, User

from core.models import Azienda
from {slug}.models import {modello}

pytestmark = pytest.mark.django_db
URL = "/{slug}/{slug}/"


def _utente(azienda, *permessi):
    u = User.objects.create_user("prova", "prova@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="{slug}", codename__in=permessi))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def aziende():
    return Azienda.objects.first(), Azienda.objects.create(nome="Altra azienda")


def test_si_crea_e_si_apre(client, aziende):
    client.force_login(_utente(aziende[0], "view_{modello.lower()}", "add_{modello.lower()}"))
    assert client.post(URL + "nuovo/", {{"nome": "Primo"}}).status_code == 302
    voce = {modello}.objects.get()
    assert voce.azienda == aziende[0]
    assert client.get(f"{{URL}}{{voce.pk}}/").status_code == 200


def test_un_altra_azienda_non_vede_i_dati(client, aziende):
    mia, altra = aziende
    {modello}.objects.create(azienda=mia, nome="MIO")
    estraneo = {modello}.objects.create(azienda=altra, nome="ESTRANEO")
    client.force_login(_utente(mia, "view_{modello.lower()}"))
    pagina = client.get(URL).content.decode()
    assert "MIO" in pagina and "ESTRANEO" not in pagina
    assert client.get(f"{{URL}}{{estraneo.pk}}/").status_code == 404


def test_senza_permesso_non_si_entra(client, aziende):
    client.force_login(_utente(aziende[0]))
    assert client.get(URL).status_code == 403
''',
        f"static/{slug}/icon.svg": ICONA,
    }


def crea(slug, nome="", modello="", depends=(), su_misura=True):
    """Scrive il modulo in ADDONS_DIR e genera la migrazione. Non lo installa e non sovrascrive mai nulla."""
    if not SLUG_RE.match(slug) or slug in RISERVATI:
        raise NomeNonValido(f"«{slug}» non è un nome valido: minuscole, cifre e trattino basso, non una parola riservata")
    modello = modello or "".join(p.capitalize() for p in slug.split("_"))
    if not CLASSE_RE.match(modello):
        raise NomeNonValido(f"«{modello}» non è un nome di modello valido: per esempio Bolla")
    cartella = Path(settings.ADDONS_DIR) / slug
    if cartella.exists():
        raise NomeNonValido(f"{cartella} esiste già: non la sovrascrivo")
    nome = nome or slug.replace("_", " ").capitalize()
    for relativo, contenuto in _file(slug, nome, modello, list(depends), su_misura).items():
        destinazione = cartella / relativo
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        destinazione.write_text(contenuto, encoding="utf-8")
    forzati = ",".join([*depends, slug])
    esito = subprocess.run([sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "makemigrations", slug, "--name", "iniziale"],
                           cwd=settings.BASE_DIR, env={**os.environ, "ADDONS_DIR": str(settings.ADDONS_DIR), "ADDONS_FORCE": forzati}, capture_output=True, text=True, timeout=120)
    if esito.returncode != 0:
        raise NomeNonValido(f"Migrazione non generata:\n{(esito.stdout + esito.stderr)[-1500:]}")
    return cartella
