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
    misure.registra(misure.Misura(
        nome="prova.aperte", etichetta="Aperte", definizione="attività aperte", unita="",
        raggruppamenti={"assegnatario": "assegnatario"},
        componenti=(misure.Componente("todo.attivita", "count", {"stato": "aperta"}),)))
    Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="a", stato="aperta", assegnatario=capo)
    r = misure.calcola("prova.aperte", richiesta_di(capo), per="assegnatario")
    assert r["url"] == "/todo/attivita/?f_stato=aperta"
    assert r["gruppi"][0]["url"] == f"/todo/attivita/?f_stato=aperta&f_assegnatario={capo.pk}"


def test_periodo_su_un_campo_che_la_lista_non_filtra_toglie_il_link(registro, capo):
    _netto(registro)                     # la lista delle attività non filtra per scadenza
    _attivita("a", "aperta", OGGI)
    assert misure.calcola("prova.netto", richiesta_di(capo), dal=OGGI, al=OGGI)["url"] == ""


def test_testo_prompt_stabile_e_ordinato(registro, db):
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


# ---------- revisione finale ----------

def test_primi_veri_oltre_100_gruppi(registro, capo):
    """I primi N sono i più grandi di tutti, non dei primi 100 gruppi per chiave (I1)."""
    misure.registra(misure.Misura(
        nome="prova.per_titolo", etichetta="Per titolo", definizione="attività per titolo", unita="",
        raggruppamenti={"titolo": "titolo"}, periodo_su="scadenza",
        componenti=(misure.Componente("todo.attivita", "count"),)))
    for i in range(105):
        _attivita(f"t{i:03d}", "aperta", OGGI)
    _attivita("t104", "aperta", OGGI)                     # il titolo con la chiave più alta è il più grande
    r = misure.calcola("prova.per_titolo", richiesta_di(capo), dal=OGGI, al=OGGI, per="titolo", primi=1)
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("t104", 2)]


def test_confronto_periodo_prima_di_calendario(registro, capo, monkeypatch):
    """Il periodo prima è il mese (trimestre, anno) prima, non lo stesso numero di giorni (I2)."""
    _netto(registro)
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    req = richiesta_di(capo)
    r = misure.calcola("prova.netto", req, periodo="mese", confronta="periodo_prima")
    assert (r["confronto"]["periodo"]["dal"], r["confronto"]["periodo"]["al"]) == ("2026-10-01", "2026-10-17")
    r = misure.calcola("prova.netto", req, periodo="mese_scorso", confronta="periodo_prima")
    assert (r["confronto"]["periodo"]["dal"], r["confronto"]["periodo"]["al"]) == ("2026-09-01", "2026-09-30")
    r = misure.calcola("prova.netto", req, periodo="anno_scorso", confronta="periodo_prima")
    assert (r["confronto"]["periodo"]["dal"], r["confronto"]["periodo"]["al"]) == ("2024-01-01", "2024-12-31")


def test_link_solo_se_filtra_davvero(registro, capo):
    """Un filtro che la lista non sa applicare toglie il link invece di mostrare altri record (I3)."""
    misure.registra(misure.Misura(
        nome="prova.aperte_o_in_corso", etichetta="Aperte o in corso", definizione="x", unita="",
        componenti=(misure.Componente("todo.attivita", "count", {"stato__in": ["aperta", "in_corso"]}),)))
    _attivita("a", "aperta", OGGI)
    assert misure.calcola("prova.aperte_o_in_corso", richiesta_di(capo))["url"] == ""


def test_permesso_della_misura(registro, db):
    """Una misura calcolata con un permesso lo controlla: senza, rifiuta invece di dire 0 (I4)."""
    misure.registra(misure.Misura(nome="prova.calcolata", etichetta="Calcolata", definizione="x", unita="",
                                  permesso="todo.view_attivita", funzione=lambda request, di="": {"valore": 0, "righe": []}))
    u = User.objects.create_user("mario", "m@example.com", "x")
    with pytest.raises(ErroreInterrogazione, match="permesso"):
        misure.calcola("prova.calcolata", richiesta_di(u))


def test_moduli_spenti_fuori(registro, monkeypatch):
    """Le misure di un modulo spento (a mano o fuori licenza) non ci sono (I5)."""
    from core.registry import modules
    misure.registra(misure.Misura(nome="todo.prova", etichetta="P", definizione="x", app="todo",
                                  componenti=(misure.Componente("todo.attivita", "count"),)))
    monkeypatch.setattr(modules, "disattivati", lambda: frozenset({"todo"}))
    assert "todo.prova" not in misure.testo_prompt()
    with pytest.raises(ErroreInterrogazione):
        misure.per_nome("todo.prova")


def test_parametri_che_non_valgono_lo_dicono(registro, capo):
    misure.registra(misure.Misura(nome="prova.oggi", etichetta="Oggi", definizione="x", unita="",
                                  componenti=(misure.Componente("todo.attivita", "count"),)))
    r = misure.calcola("prova.oggi", richiesta_di(capo), periodo="mese_scorso")
    assert "situazione di oggi" in r["nota"]


def test_serie_porta_il_link_di_ogni_gruppo(registro, capo):
    """Il grafico su una misura sa quali record ci sono dietro ogni punto: il link del gruppo con i filtri della misura."""
    misure.registra(misure.Misura(
        nome="prova.aperte", etichetta="Aperte", definizione="attività aperte", unita="",
        raggruppamenti={"assegnatario": "assegnatario"},
        componenti=(misure.Componente("todo.attivita", "count", {"stato": "aperta"}),)))
    altro = User.objects.create_user("bruno", "b@example.com", "x")
    for i in range(2):
        Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=f"a{i}", stato="aperta", assegnatario=capo)
    Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="b", stato="aperta", assegnatario=altro)
    r = misure.serie({"misura_aziendale": "prova.aperte", "per": "assegnatario"}, richiesta_di(capo))
    assert r["link"] == [f"/todo/attivita/?f_stato=aperta&f_assegnatario={capo.pk}",
                         f"/todo/attivita/?f_stato=aperta&f_assegnatario={altro.pk}"]
    r = misure.serie({"misura_aziendale": "prova.aperte", "per": "assegnatario", "primi": 1}, richiesta_di(capo))
    assert len(r["link"]) == len(r["serie"]) == 2 and r["serie"][1][0] == "Altro" and r["link"][1] is None


# ---------- periodo sul grafico ----------

def _misura_con_periodo(registro):
    return misure.registra(misure.Misura(
        nome="prova.scadenze", etichetta="Scadenze", definizione="attività per scadenza", unita="",
        raggruppamenti={"stato": "stato", "mese": "scadenza:mese"}, periodo_su="scadenza",
        componenti=(misure.Componente("todo.attivita", "count"),)))


def test_periodo_del_grafico_solo_dove_c_e_una_data(registro, db):
    _misura_con_periodo(registro)
    p = misure.periodo_grafico({"misura_aziendale": "prova.scadenze", "per": "stato"})
    assert p["scelto"] == "anno" and p["sempre"] is False and p["confronta"] is False
    assert [k for k, _ in p["pulsanti"]] == ["mese", "trimestre", "anno", "anno_scorso"]
    fissa = misure.periodo_grafico({"misura_aziendale": "prova.scadenze", "per": "stato", "dal": "2026-01-01", "al": "2026-03-31"})
    assert fissa["scelto"] == ""                                       # date fisse: nessun pulsante acceso
    misure.registra(misure.Misura(nome="prova.oggi", etichetta="Oggi", definizione="x", unita="",
                                  funzione=lambda request, di="": {"valore": 0, "righe": []}))
    assert misure.periodo_grafico({"misura_aziendale": "prova.oggi"}) is None    # situazione di oggi: niente periodo
    v = misure.periodo_grafico({"vista": "todo.attivita", "per": "scadenza:mese", "periodo": "trimestre", "confronta": True})
    assert v == {**v, "scelto": "trimestre", "sempre": True, "confronta": True}
    assert misure.periodo_grafico({"vista": "todo.attivita", "per": "stato"}) is None
    assert misure.periodo_grafico({"vista": "x", "per": "data:mese", "grafico": "previsione"}) is None


def test_periodo_di_una_vista_filtra_la_data_del_raggruppamento(monkeypatch, db):
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    spec = {"vista": "todo.attivita", "per": "scadenza:mese", "periodo": "trimestre", "filtri": {"stato": "aperta"}}
    assert misure.spec_per_calcolo(spec)["filtri"] == {"stato": "aperta", "scadenza__gte": "2026-10-01", "scadenza__lte": "2026-12-31"}
    assert misure.spec_per_calcolo({"vista": "todo.attivita", "per": "scadenza:mese"}).get("filtri", {}) == {}
    misura = {"misura_aziendale": "prova.scadenze", "per": "stato", "periodo": "mese"}
    assert misure.spec_per_calcolo(misura) == misura                   # le misure il periodo lo applicano da sé


def test_anno_prima_sposta_il_periodo(registro, monkeypatch, db):
    _misura_con_periodo(registro)
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    prima = misure.spec_anno_prima({"misura_aziendale": "prova.scadenze", "per": "stato", "periodo": "mese", "confronta": True})
    assert (prima["dal"], prima["al"]) == ("2025-11-01", "2025-11-30") and "periodo" not in prima and "confronta" not in prima
    vista = misure.spec_anno_prima({"vista": "todo.attivita", "per": "scadenza:mese", "periodo": "anno"})
    assert vista["filtri"] == {"scadenza__gte": "2025-01-01", "scadenza__lte": "2025-12-31"} and "periodo" not in vista
    assert misure.spec_anno_prima({"vista": "todo.attivita", "per": "scadenza:mese"}) is None     # senza periodo


def test_confronto_allineato_per_chiave_e_per_mese():
    dati = {"serie": [("Aperta", 3), ("Fatta", 2)], "chiavi": ["aperta", "fatta"]}
    prima = {"serie": [("Fatta", 5), ("In corso", 1)], "chiavi": ["fatta", "in_corso"]}
    assert misure.con_confronto(dati, prima, temporale=False)["confronto"] == {"etichetta": "Anno prima", "valori": [0, 5]}
    mesi = {"serie": [("gen 2026", 4), ("feb 2026", 6)], "chiavi": ["2026-01-01", "2026-02-01"]}
    prima = {"serie": [("feb 2025", 2), ("gen 2025", 1)], "chiavi": ["2025-02-01", "2025-01-01"]}
    assert misure.con_confronto(mesi, prima, temporale=True)["confronto"]["valori"] == [1, 2]


# ---------- periodo sul grafico: revisione finale ----------

def test_confronta_tiene_date_fisse_e_periodi_non_a_pulsante(registro, db, monkeypatch):
    _misura_con_periodo(registro)
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    fissa = {"misura_aziendale": "prova.scadenze", "per": "stato", "dal": "2026-01-01", "al": "2026-03-31"}
    periodo, confronta = misure.scelta_dal_form({"confronta": "", "periodo_attuale": "", "inverti": "1"})
    nuova = misure.scegli_periodo(fissa, periodo, confronta)
    assert (nuova["dal"], nuova["al"], nuova["confronta"]) == ("2026-01-01", "2026-03-31", True)
    dodici = {"misura_aziendale": "prova.scadenze", "per": "stato", "periodo": "ultimi_12_mesi"}
    assert misure.scegli_periodo(dodici, *misure.scelta_dal_form({"periodo_attuale": "ultimi_12_mesi", "inverti": "1"})) == {**dodici, "confronta": True}


def test_il_periodo_si_interseca_con_i_filtri_sulla_stessa_data(db, monkeypatch):
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    spec = {"vista": "todo.attivita", "per": "scadenza:mese", "periodo": "anno", "filtri": {"scadenza__gte": "2026-06-01"}}
    assert misure.spec_per_calcolo(spec)["filtri"] == {"scadenza__gte": "2026-06-01", "scadenza__lte": "2026-12-31"}
    prima = misure.spec_anno_prima(spec)                    # anche i limiti dell'utente vanno indietro di un anno
    assert prima["filtri"] == {"scadenza__gte": "2025-06-01", "scadenza__lte": "2025-12-31"}
    altro = {**spec, "filtri": {"scadenza__year": 2026}}    # un filtro sulla data che non si sposta: niente confronto
    assert misure.spec_anno_prima(altro) is None


def test_confronto_settimanale_per_numero_di_settimana():
    dati = {"serie": [("sett. 45", 4)], "chiavi": ["2026-11-02"]}               # lunedì della settimana 45 del 2026
    prima = {"serie": [("sett. 45", 7)], "chiavi": ["2025-11-03"]}             # lunedì della settimana 45 del 2025
    assert misure.con_confronto(dati, prima, temporale="settimana")["confronto"]["valori"] == [7]


def test_anno_prima_senza_primi(registro, db, monkeypatch):
    _misura_con_periodo(registro)
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    assert "primi" not in misure.spec_anno_prima({"misura_aziendale": "prova.scadenze", "per": "stato", "primi": 5})


def test_etichetta_del_periodo(registro, db, monkeypatch):
    _misura_con_periodo(registro)
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    assert misure.etichetta_periodo({"misura_aziendale": "prova.scadenze", "per": "stato"}) == "dell'anno in corso"
    assert misure.etichetta_periodo({"vista": "todo.attivita", "per": "scadenza:mese", "periodo": "mese", "confronta": True}) == \
        "del mese in corso, a confronto con l'anno prima"
    assert misure.etichetta_periodo({"vista": "todo.attivita", "per": "scadenza:mese"}) == ""
