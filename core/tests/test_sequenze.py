import datetime
import threading

import pytest
from django.contrib.auth.models import Permission, User
from django.db import connection
from django.utils import timezone

from core import sequenze
from core.models import Azienda, Sequenza
from core.registry import modules
from core.registry.manifest import Manifest
from core.viste import registry

VOCI = [{"codice": "alfa.ordine", "formato": "ORD/{anno}/{numero:04d}", "azzera": "anno"},
        {"codice": "alfa.ticket", "formato": "T{mese:02d}-{numero}"}]


@pytest.fixture(autouse=True)
def finti(monkeypatch):
    m = Manifest(slug="alfa", percorso=None, name="Alfa", version="1.0.0", min_core="1.0", sequences=VOCI)
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {"alfa": m})


@pytest.fixture
def prima(db):
    return Azienda.objects.get(pk=1)


def test_formato_e_progressione(prima):
    anno = timezone.localdate().year
    assert sequenze.prossimo("alfa.ordine", prima) == f"ORD/{anno}/0001"
    assert sequenze.prossimo("alfa.ordine", prima) == f"ORD/{anno}/0002"
    assert sequenze.prossimo("alfa.ticket", prima) == f"T{timezone.localdate().month:02d}-1"


def test_per_azienda_e_globale(prima):
    zeta = Azienda.objects.create(nome="Zeta")
    sequenze.prossimo("alfa.ticket", prima)
    assert sequenze.prossimo("alfa.ticket", zeta).endswith("-1")
    assert sequenze.prossimo("alfa.ticket").endswith("-1")             # globale, distinta


def test_azzeramento_annuale(prima, monkeypatch):
    sequenze.prossimo("alfa.ordine", prima)
    sequenze.prossimo("alfa.ordine", prima)
    monkeypatch.setattr(timezone, "localdate", lambda: datetime.date(2099, 1, 2))
    assert sequenze.prossimo("alfa.ordine", prima) == "ORD/2099/0001"


def test_non_dichiarata(prima):
    with pytest.raises(KeyError):
        sequenze.prossimo("beta.x", prima)


def test_crea_e_nuova_azienda(prima):
    sequenze.crea(VOCI)
    assert Sequenza.objects.filter(azienda=prima).count() == 2
    nuova = Azienda.objects.create(nome="Nuova")                       # signal
    assert set(Sequenza.objects.filter(azienda=nuova).values_list("codice", flat=True)) == {"alfa.ordine", "alfa.ticket"}


def test_crea_non_azzera_il_numero(prima):
    sequenze.crea(VOCI)
    sequenze.prossimo("alfa.ticket", prima)
    sequenze.crea([{**VOCI[1], "formato": "TK-{numero}"}])
    assert sequenze.prossimo("alfa.ticket", prima) == "TK-2"


@pytest.mark.django_db
def test_sequence_field_della_vista(client, monkeypatch, prima):
    monkeypatch.setattr(registry.per_modello(Azienda), "sequence_field", ("codice_fiscale", "alfa.ticket"))
    u = User.objects.create_user("seq", "s@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(codename__in=["add_azienda", "view_azienda"]))
    client.force_login(u)
    client.post("/core/aziende/nuovo/", {"nome": "Numerata", "attiva": "on"})
    client.post("/core/aziende/nuovo/", {"nome": "Scelta", "codice_fiscale": "MIO", "attiva": "on"})
    assert Azienda.objects.get(nome="Numerata").codice_fiscale.endswith("-1")   # globale: Azienda non ha company_field
    assert Azienda.objects.get(nome="Scelta").codice_fiscale == "MIO"          # valore dato: non sovrascritto


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_concorrenza_senza_doppioni():
    azienda = Azienda.objects.create(nome="Concorrenza")   # i test transazionali svuotano le tabelle
    numeri, barriera = [], threading.Barrier(10)

    def prendi():
        try:
            barriera.wait()
            for _ in range(5):
                numeri.append(sequenze.prossimo("alfa.ticket", azienda))
        finally:
            connection.close()
    fili = [threading.Thread(target=prendi) for _ in range(10)]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    assert sorted(int(n.split("-")[1]) for n in numeri) == list(range(1, 51))
