import datetime

import pytest
from django.contrib.auth.models import Permission, User

from core import misure
from core.models import Azienda
from core.registry.manifest import ManifestNonValido
from core.registry import manifest
from core.viste.interroga import ErroreInterrogazione, richiesta_di
from todo.models import Attivita, Tag

OGGI = datetime.date(2026, 11, 17)


@pytest.fixture
def registro(monkeypatch):
    """Un registro vuoto per il test: le misure delle app non c'entrano."""
    monkeypatch.setattr(misure, "_registro", {})
    monkeypatch.setattr(misure, "carica", lambda: None)
    return misure._registro


@pytest.fixture
def capo(db):
    return User.objects.create_superuser("capo", "capo@example.com", "x")


def _attivita(titolo, stato, scadenza):
    return Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=titolo, stato=stato, scadenza=scadenza)


def _netto(registro):
    """aperte − fatte, per scadenza: due componenti di segno opposto sulla stessa vista."""
    return misure.registra(misure.Misura(
        nome="prova.netto", etichetta="Netto", definizione="aperte meno fatte", unita="",
        raggruppamenti={"stato": "stato", "mese": "scadenza:mese"}, periodo_su="scadenza",
        componenti=(misure.Componente("todo.attivita", "count", {"stato": "aperta"}),
                    misure.Componente("todo.attivita", "count", {"stato": "fatta"}, segno=-1))))


def test_somma_componenti_con_segno(registro, capo):
    _netto(registro)
    for i in range(5):
        _attivita(f"a{i}", "aperta", OGGI)
    for i in range(2):
        _attivita(f"f{i}", "fatta", OGGI)
    r = misure.calcola("prova.netto", richiesta_di(capo), dal=OGGI.replace(day=1), al=OGGI)
    assert r["valore"] == 3
    assert r["definizione"] == "aperte meno fatte"


def test_periodo_anno_e_scorso():
    p = misure.risolvi_periodo("anno", oggi=OGGI)
    assert (p.dal, p.al, p.relativo) == (datetime.date(2026, 1, 1), datetime.date(2026, 12, 31), True)
    s = misure.risolvi_periodo("anno_scorso", oggi=OGGI)
    assert (s.dal, s.al) == (datetime.date(2025, 1, 1), datetime.date(2025, 12, 31))
    f = misure.risolvi_periodo(dal=datetime.date(2026, 3, 1), al=datetime.date(2026, 6, 30))
    assert f.relativo is False
    assert misure.risolvi_periodo("domani", oggi=OGGI).dal == datetime.date(2026, 11, 18)
    with pytest.raises(ErroreInterrogazione):
        misure.risolvi_periodo("secolo", oggi=OGGI)


def test_confronto_anno_prima_stesso_tratto(registro, capo, monkeypatch):
    _netto(registro)
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    _attivita("quest'anno", "aperta", datetime.date(2026, 3, 1))
    _attivita("anno scorso, prima di oggi", "aperta", datetime.date(2025, 3, 1))
    _attivita("anno scorso, dopo oggi", "aperta", datetime.date(2025, 12, 1))
    r = misure.calcola("prova.netto", richiesta_di(capo), periodo="anno", confronta="anno_prima")
    assert r["periodo"]["al"] == "2026-11-17"
    assert (r["confronto"]["periodo"]["dal"], r["confronto"]["periodo"]["al"]) == ("2025-01-01", "2025-11-17")
    assert r["confronto"]["valore"] == 1
    assert r["confronto"]["delta_percento"] == 0.0


def test_primi_ordina_per_valore(registro, capo):
    misure.registra(misure.Misura(
        nome="prova.tutte", etichetta="Attività", definizione="tutte", unita="", raggruppamenti={"stato": "stato"},
        periodo_su="scadenza", componenti=(misure.Componente("todo.attivita", "count"),)))
    for i in range(3):
        _attivita(f"a{i}", "aperta", OGGI)
    _attivita("f", "fatta", OGGI)
    r = misure.calcola("prova.tutte", richiesta_di(capo), dal=OGGI, al=OGGI, per="stato", primi=1)
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("Aperta", 3)]
    assert r["valore"] == 4


def test_gruppo_solo_negativo_resta(registro, capo):
    _netto(registro)
    _attivita("f", "fatta", OGGI)
    r = misure.calcola("prova.netto", richiesta_di(capo), dal=OGGI, al=OGGI, per="stato")
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("Fatta", -1)]


def test_componente_senza_permesso_rifiuta(registro, db):
    misure.registra(misure.Misura(
        nome="prova.mista", etichetta="Mista", definizione="attività meno tag", unita="",
        componenti=(misure.Componente("todo.attivita", "count"), misure.Componente("todo.tag", "count", segno=-1))))
    u = User.objects.create_user("mario", "m@example.com", "x")
    u.user_permissions.add(Permission.objects.get(codename="view_attivita"))
    u = User.objects.get(pk=u.pk)
    Tag.objects.create(nome="t")
    with pytest.raises(ErroreInterrogazione, match="Mista"):
        misure.calcola("prova.mista", richiesta_di(u))


def test_url_lista_filtrata(registro, capo):
    _netto(registro)
    _attivita("a", "aperta", OGGI)
    r = misure.calcola("prova.netto", richiesta_di(capo), dal=OGGI.replace(day=1), al=OGGI, per="stato")
    assert r["url"].startswith("/todo/attivita/?")
    assert "f_scadenza_da=2026-11-01" in r["url"] and "f_scadenza_a=2026-11-17" in r["url"]
    assert "f_stato=aperta" in r["gruppi"][0]["url"]


def test_testo_prompt_stabile_e_ordinato(registro):
    for nome in ("prova.b", "prova.a"):
        misure.registra(misure.Misura(nome=nome, etichetta=nome[-1].upper(), definizione=f"misura {nome[-1]}",
                                      componenti=(misure.Componente("todo.attivita", "count"),)))
    testo = misure.testo_prompt()
    assert testo == misure.testo_prompt()
    assert testo.index("prova.a") < testo.index("prova.b")


def test_manifest_misure_valida(addons_tmp):
    cartella = addons_tmp.crea("alfa", misure="altro.misure")
    with pytest.raises(ManifestNonValido) as exc:
        manifest.leggi(cartella)
    assert "misure" in str(exc.value)
    assert manifest.leggi(addons_tmp.crea("beta", misure="beta.misure")).misure == "beta.misure"
