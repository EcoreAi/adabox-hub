"""Il kit per i moduli: il modulo generato è buono da subito, il controllo riconosce gli errori tipici."""
import pytest
from django.core.management import CommandError, call_command

from core.registry import collaudo, controlli, manifest, nuovo


@pytest.fixture
def generato(addons_tmp, db):
    return nuovo.crea("bolle", nome="Bolle", modello="Bolla")


def _regole(cartella, livello=controlli.ERRORE):
    return {r.regola for r in controlli.controlla(cartella) if r.livello == livello}


def _scrivi(cartella, nome, testo):
    (cartella / nome).parent.mkdir(parents=True, exist_ok=True)
    (cartella / nome).write_text(testo)


def test_il_modulo_generato_e_su_misura_salvo_richiesta(generato, addons_tmp, db):
    assert manifest.leggi(generato).su_misura is True
    assert manifest.leggi(nuovo.crea("catalogo", su_misura=False)).su_misura is False


def test_il_modulo_generato_e_valido_e_senza_rilievi(generato):
    m = manifest.leggi(generato)
    assert m.slug == "bolle" and m.menu[0]["url_name"] == "bolle:bolle_lista"
    assert list((generato / "migrations").glob("0001_*.py"))
    assert controlli.controlla(generato) == []


@pytest.mark.parametrize("slug", ["Bolle", "core", "2bolle", "a-b", "x"])
def test_nomi_non_validi(addons_tmp, db, slug):
    with pytest.raises(nuovo.NomeNonValido):
        nuovo.crea(slug)


def test_modello_non_valido(addons_tmp, db):
    with pytest.raises(nuovo.NomeNonValido):
        nuovo.crea("bolle", modello="bolla; import os")


def test_non_sovrascrive_mai(generato):
    prima = (generato / "models.py").read_text()
    with pytest.raises(nuovo.NomeNonValido):
        nuovo.crea("bolle")
    assert (generato / "models.py").read_text() == prima


def test_vista_senza_azienda_e_un_errore(generato):
    t = (generato / "views.py").read_text()
    _scrivi(generato, "views.py", t.replace('    company_field = "azienda"', "    #").replace("                   # senza, i dati", "# "))
    assert "azienda" in _regole(generato)


def test_pagina_di_amministrazione_dichiarata(generato):
    t = (generato / "views.py").read_text().replace('company_field = "azienda"', "tra_aziende = True  #")
    _scrivi(generato, "views.py", t)
    assert "azienda" not in _regole(generato)


def test_il_vecchio_ripiego_su_tutte_le_aziende_e_un_errore(generato):
    t = (generato / "views.py").read_text() + '''
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        azienda_id = request.azienda.pk
        return qs.filter(azienda_id=azienda_id) if azienda_id is not None else qs
'''
    _scrivi(generato, "views.py", t)
    assert "azienda" in _regole(generato)


def test_import_non_dichiarato(generato, addons_tmp):
    addons_tmp.crea("vicino")
    _scrivi(generato, "logica.py", "from vicino.models import Qualcosa\n")
    assert "dipendenze" in _regole(generato)


def test_import_dichiarato_o_protetto_va_bene(addons_tmp, db):
    con = nuovo.crea("con_dip", depends=["contatti"])
    _scrivi(con, "logica.py", "from contatti.models import Contatto\n")
    assert "dipendenze" not in _regole(con)
    senza = nuovo.crea("protetto")
    _scrivi(senza, "logica.py", "from django.apps import apps\n\n\ndef f():\n    if apps.is_installed('contatti'):\n        from contatti.models import Contatto\n        return Contatto\n")
    assert "dipendenze" not in _regole(senza) | _regole(senza, controlli.AVVISO)


def test_eval_e_un_errore(generato):
    _scrivi(generato, "logica.py", "def f(x):\n    return eval(x)\n")
    assert "sicurezza" in _regole(generato)


def test_modello_senza_migrazione_e_un_errore(generato):
    for f in (generato / "migrations").glob("0*.py"):
        f.unlink()
    assert "migrazioni" in _regole(generato)


def test_avvisi_su_segreti_lettura_diretta_pagine_e_rete(generato):
    t = (generato / "models.py").read_text().replace('    note = models', '    api_key = models.CharField("chiave", max_length=50)\n    note = models')
    _scrivi(generato, "models.py", t)
    _scrivi(generato, "pagine.py", '''import httpx2 as httpx
from django.shortcuts import get_object_or_404
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt

from .models import Bolla


@csrf_exempt
def apri(request, pk):
    voce = get_object_or_404(Bolla, pk=pk)
    httpx.get(voce.nome)
    return mark_safe(voce.note)
''')
    _scrivi(generato, "urls.py", 'from django.urls import path\n\nfrom . import pagine\n\nurlpatterns = [path("x/", pagine.apri)]\n')
    _scrivi(generato, "templates/bolle/x.html", "{{ testo|safe }}")
    avvisi = [str(r) for r in controlli.controlla(generato) if r.livello == controlli.AVVISO]
    for atteso in ("api_key", "legge Bolla", "non ha fatto l'accesso", "senza CSRF", "mark_safe", "indirizzo variabile", "senza escape"):
        assert any(atteso in a for a in avvisi), atteso


def test_sintassi_rotta_non_blocca_il_controllo(generato):
    _scrivi(generato, "logica.py", "def f(:\n")
    assert "sintassi" in _regole(generato)


def test_comandi(generato, capsys):
    call_command("modulo", "controlla", "bolle")
    assert "Errori: 0, avvisi: 0" in capsys.readouterr().out
    _scrivi(generato, "logica.py", "eval('1')\n")
    with pytest.raises(CommandError):
        call_command("modulo", "controlla", "bolle")
    with pytest.raises(CommandError):
        call_command("modulo", "controlla")
    with pytest.raises(CommandError):
        call_command("modulo", "nuovo", "core")


def test_la_sonda_rifiuta_un_istanza_vera(db, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="usa e getta"):
        call_command("modulo", "sonda", "todo")


def test_compatibilita_rifiuta_moduli_inesistenti(addons_tmp):
    with pytest.raises(ValueError):
        collaudo.compatibilita("inesistente")


@pytest.mark.slow
def test_il_modulo_generato_passa_collaudo_e_compatibilita(addons_tmp, db):
    nuovo.crea("bolle", nome="Bolle", modello="Bolla")
    addons_tmp.crea("vicino")
    ordine, info = collaudo.da_collaudare(["bolle"])
    r = collaudo.collauda("bolle", info)
    assert r.ok, r.dettaglio
    assert [p for p, _ in r.passi] == ["migrate", "installa", "migrazioni", "test", "disinstalla"]
    assert collaudo.compatibilita("bolle", ["vicino"]) == [("vicino", None)]


def test_senza_descrizione_per_ada_un_modulo_su_misura_ha_un_avviso(generato):
    t = (generato / "views.py").read_text()
    _scrivi(generato, "views.py", "\n".join(r for r in t.splitlines() if "ai_descrizione" not in r) + "\n")
    assert "ada" in _regole(generato, controlli.AVVISO)
