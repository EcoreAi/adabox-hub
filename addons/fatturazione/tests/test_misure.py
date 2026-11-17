"""Le misure aziendali della Fatturazione: definizioni fisse, uguali per l'assistente e la dashboard."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission, User

from contatti.models import Contatto
from core import misure
from core.dashboard import numero
from core.models import PermessoCampo, Ruolo
from core.viste.interroga import richiesta_di
from fatturazione import dashboard
from fatturazione.models import Scadenza

from .test_fatturazione import OGGI, _fattura, scena  # noqa: F401  (fixture)


@pytest.fixture
def capo(db):
    return User.objects.create_superuser("capo", "capo@example.com", "x")


def _req(utente):
    return richiesta_di(utente)


def test_fatturato_imponibile_meno_note_credito(scena, capo):
    azienda, cliente, monitor, corso = scena
    _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")                 # 1.000
    _fattura(azienda, cliente, [(monitor, "2.5")], stato="emessa")               # 500
    _fattura(azienda, cliente, [(monitor, "1.5")])                               # bozza: non conta
    _fattura(azienda, cliente, [(monitor, "1")], stato="emessa", tipo="TD04")    # nota di credito: −200
    r = misure.calcola("fatturazione.fatturato", _req(capo), periodo="anno")
    assert r["valore"] == 1300
    assert "note di credito" in r["definizione"]


def test_fatturato_senza_dati_vale_zero(scena, capo):
    r = misure.calcola("fatturazione.fatturato", _req(capo), periodo="mese", per="cliente")
    assert r["valore"] == 0
    assert r["gruppi"] == []


def test_cliente_con_sola_nota_credito(scena, capo):
    azienda, cliente, monitor, corso = scena
    _fattura(azienda, cliente, [(monitor, "1")], stato="emessa", tipo="TD04")
    r = misure.calcola("fatturazione.fatturato", _req(capo), periodo="anno", per="cliente")
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("Rossi Srl", -200)]


def test_primi_5_clienti(scena, capo):
    azienda, _, monitor, corso = scena
    for i in range(1, 8):
        c = Contatto.objects.create(azienda=azienda, nome=f"Cliente {i}", cliente=True)
        _fattura(azienda, c, [(monitor, str(i))], stato="emessa")
    r = misure.calcola("fatturazione.fatturato", _req(capo), periodo="anno", per="cliente", primi=5)
    assert [g["gruppo"] for g in r["gruppi"]] == ["Cliente 7", "Cliente 6", "Cliente 5", "Cliente 4", "Cliente 3"]
    assert r["valore"] == 200 * sum(range(1, 8))


def test_dashboard_uguale_alla_misura(scena, capo):
    azienda, cliente, monitor, corso = scena
    _fattura(azienda, cliente, [(monitor, "3")], stato="emessa")
    _fattura(azienda, cliente, [(monitor, "1")], stato="emessa", tipo="TD04")
    valore = misure.calcola("fatturazione.fatturato", _req(capo), periodo="mese")["valore"]
    assert valore == 400
    assert dashboard.kpi(_req(capo))["kpi"][0]["valore"] == f"{numero(valore)} €"


def test_dashboard_campo_nascosto_non_disponibile(scena):
    azienda, cliente, monitor, corso = scena
    ruolo = Ruolo.objects.create(nome="Contabile", livello_base="lavoro")
    u = User.objects.create_user("anna", "anna@example.com", "x")
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.ruolo = ruolo
    u.profilo.save()
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="fatturazione",
                                                      codename__in=["view_fattura", "view_scadenza", "view_incasso"]))
    PermessoCampo.objects.create(vista="fatturazione.fatture", campo="imponibile", ruolo=ruolo, livello="nascosto")
    _fattura(azienda, cliente, [(monitor, "3")], stato="emessa")
    kpi = dashboard.kpi(_req(User.objects.get(pk=u.pk)))
    assert kpi["kpi"][0]["valore"] == "non disponibile"


def test_scaduto_solo_passate(scena, capo):
    azienda, cliente, monitor, corso = scena
    f = _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")
    Scadenza.objects.filter(fattura=f).delete()
    Scadenza.objects.create(fattura=f, data=OGGI - datetime.timedelta(days=1), importo=Decimal("300"))
    Scadenza.objects.create(fattura=f, data=OGGI + datetime.timedelta(days=1), importo=Decimal("700"))
    assert misure.calcola("fatturazione.scaduto", _req(capo))["valore"] == 300
    assert misure.calcola("fatturazione.da_incassare", _req(capo))["valore"] == 1000
