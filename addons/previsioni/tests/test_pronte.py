"""Le previsioni pronte di Vendite: il registro, il calcolo con l'intera azienda (la notte e «Aggiorna») e, per chi non
vede tutta la vista di origine, il calcolo al momento con i suoi permessi."""
import datetime
import re
import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.db.models import QuerySet
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import parametri, regole
from core.models import Azienda, Lavoro, Modulo, PermessoCampo, RegolaRiga, Ruolo
from core.viste.interroga import richiesta_di
from previsioni import calcolo, motore, pronte, servizio
from previsioni.models import PrevisionePronta, StatoCalcolo
from previsioni.tests.test_motore import _finta_risposta

pytestmark = pytest.mark.django_db
serve_vendite = pytest.mark.skipif(not apps.is_installed("vendite"), reason="serve Vendite (con Prodotti, Fiscale e Contatti)")
serve_fatturazione = pytest.mark.skipif(not apps.is_installed("fatturazione"), reason="serve Fatturazione")

CHIAMA_VERA = servizio.chiama
CHIAVI = ["vendite.fatturato_mese", "vendite.prodotti", "vendite.clienti"]
PERMESSI = ["vendite.view_ordinevendita", "vendite.view_rigavendita", "previsioni.view_previsionepronta"]


def _mese_fa(n):
    return motore.avanti(timezone.localdate().replace(day=1), "mese", -n).replace(day=10)


def _riserva(slug, *aziende):
    Modulo.objects.update_or_create(slug=slug, defaults={"nome": slug.title()})[0].aziende.set(aziende)


@pytest.fixture
def servizi(monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    chiamate = []

    def chiama(percorso, dati):
        chiamate.append(dati)
        return _finta_risposta(dati)
    monkeypatch.setattr(servizio, "chiama", chiama)
    return chiamate


def _utente(nome, azienda, ruolo=None, permessi=PERMESSI):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita, u.profilo.ruolo = azienda, ruolo
    u.profilo.save()
    for p in permessi:
        app, codename = p.split(".")
        u.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
    return User.objects.get(pk=u.pk)


def _ordine(azienda, cliente, righe, mese, commerciale=None):
    from vendite.models import OrdineVendita, RigaVendita
    o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, data=_mese_fa(mese), commerciale=commerciale)
    for prodotto, quantita in righe:
        RigaVendita.objects.create(ordine=o, prodotto=prodotto, quantita=Decimal(quantita))
    o.ricalcola()
    OrdineVendita.objects.filter(pk=o.pk).update(stato=OrdineVendita.CONFERMATO)
    return o


def _fattura(azienda, cliente, prodotto, quantita, mese):
    from fatturazione.models import Fattura, RigaFattura
    f = Fattura.objects.create(azienda=azienda, cliente=cliente, data=_mese_fa(mese), stato=Fattura.EMESSA)
    RigaFattura.objects.create(fattura=f, prodotto=prodotto, quantita=Decimal(quantita))
    f.ricalcola()
    return f


@pytest.fixture
def s(db):
    """Otto mesi di ordini confermati: ogni mese Anna vende un monitor (200 €) a Rossi, Bruno sette cavi (70 €) a
    Verdi. Anna e Bruno sono commerciali che vedono solo i propri ordini (regola di riga sugli ordini)."""
    import fiscale
    import prodotti
    from contatti.models import Contatto
    from prodotti.models import Prodotto
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    cache.clear()
    azienda = Azienda.objects.get(pk=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    commerciale = Ruolo.objects.create(nome="Commerciale", livello_base="lavoro")
    RegolaRiga.objects.create(vista="vendite.ordini", ruolo=commerciale, campo="commerciale", operatore="utente")
    anna, bruno = _utente("anna", azienda, commerciale), _utente("bruno", azienda, commerciale)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    verdi = Contatto.objects.create(azienda=azienda, nome="Verdi Spa", cliente=True)
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"))
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", prezzo_vendita=Decimal("10"))
    for m in range(1, 9):
        _ordine(azienda, rossi, [(monitor, "1")], m, commerciale=anna)
        _ordine(azienda, verdi, [(cavo, "7")], m, commerciale=bruno)
    return {"azienda": azienda, "altra": Azienda.objects.create(nome="Altra"), "capo": capo, "anna": anna,
            "bruno": bruno, "rossi": rossi, "verdi": verdi, "monitor": monitor, "cavo": cavo}


def _salvata(azienda, chiave):
    return PrevisionePronta.objects.get(azienda=azienda, chiave=chiave)


def _valori(dati):
    return [v for _, v in dati["storico"]]


@serve_vendite
@serve_fatturazione
def test_fatturato_se_c_e_fatturazione_altrimenti_ordinato(s, servizi):
    azienda, capo = s["azienda"], s["capo"]
    elenco = {p["chiave"]: p for p in pronte.per_request(richiesta_di(capo, azienda))}
    assert list(elenco) == CHIAVI
    assert elenco["vendite.fatturato_mese"]["titolo"] == "Fatturato previsto per mese"
    assert elenco["vendite.fatturato_mese"]["app"] == "vendite"
    assert elenco["vendite.fatturato_mese"]["spec"] == {"misura_aziendale": "fatturazione.fatturato", "per": "mese",
                                                        "orizzonte": 3}
    assert elenco["vendite.clienti"]["titolo"] == "Clienti: vendite previste, primi 10"
    assert elenco["vendite.clienti"]["spec"] == {"misura_aziendale": "fatturazione.fatturato", "raggruppa": "cliente",
                                                 "primi": 10, "per": "mese", "orizzonte": 3}

    # nessuna fattura: il fatturato non ha storia (lo dice la previsione salvata), i prodotti sì
    assert calcolo.vendite(azienda) == 1
    assert _salvata(azienda, "vendite.fatturato_mese").dati["errore"].startswith("Nessun dato nei periodi passati")
    d = pronte.dati_per(richiesta_di(capo, azienda), "vendite.fatturato_mese")
    assert d["dati"] is None and d["errore"].startswith("Nessun dato nei periodi passati") and d["salvata"] is True

    for m in range(1, 9):
        _fattura(azienda, s["rossi"], s["monitor"], "1", m)                     # 200 € al mese, gli ordini fanno 270
    servizi.clear()
    assert calcolo.vendite(azienda) == 3
    assert servizi[0]["series"][0]["values"] == [200.0] * 8                    # il fatturato viene dalle fatture
    assert _valori(_salvata(azienda, "vendite.fatturato_mese").dati["risultato"]) == [200.0] * 8

    _riserva("fatturazione", s["altra"])                                       # Fatturazione solo per un'altra azienda
    elenco = {p["chiave"]: p for p in pronte.per_request(richiesta_di(capo, azienda))}
    assert elenco["vendite.fatturato_mese"]["titolo"] == "Ordinato previsto per mese"
    assert elenco["vendite.fatturato_mese"]["spec"]["misura_aziendale"] == "vendite.ordinato"
    assert elenco["vendite.clienti"]["spec"]["misura_aziendale"] == "vendite.ordinato"
    # finché non si ricalcola, la salvata è del fatturato: non si spaccia per ordinato
    d = pronte.dati_per(richiesta_di(capo, azienda), "vendite.fatturato_mese")
    assert d["titolo"] == "Ordinato previsto per mese" and d["dati"] is None and d["errore"]
    servizi.clear()
    assert calcolo.vendite(azienda) == 3
    assert servizi[0]["series"][0]["values"] == [270.0] * 8                    # ora dagli ordini
    riga = _salvata(azienda, "vendite.fatturato_mese")
    assert riga.dati["spec"]["misura_aziendale"] == "vendite.ordinato" and riga.modello == "finto-timestral"
    d = pronte.dati_per(richiesta_di(capo, azienda), "vendite.fatturato_mese")
    assert d["salvata"] is True and d["dati"] == riga.dati["risultato"] and d["calcolata_il"] == riga.calcolata_il
    assert d["dati"]["futuro"][0][1:] == [268.0, 270.0, 272.0] and d["dati"]["affidabilita"]["livello"]


@serve_vendite
def test_prodotti_primi_dieci(s, servizi):
    azienda = s["azienda"]
    from prodotti.models import Prodotto
    articoli = [Prodotto.objects.create(azienda=azienda, nome=f"Articolo {i}") for i in range(1, 11)]
    for m in range(1, 9):                                    # 11…20 pezzi al mese: più del monitor e dei cavi
        _ordine(azienda, s["rossi"], [(a, str(10 + i)) for i, a in enumerate(articoli, start=1)], m)
    calcolo.vendite(azienda)

    chiamata = next(c for c in servizi if len(c["series"]) == 10)       # una sola chiamata per i dieci prodotti
    assert all(re.fullmatch(r"s\d+", x["id"]) for x in chiamata["series"]) and chiamata["horizon"] == 3
    assert sorted(x["values"][0] for x in chiamata["series"]) == [float(q) for q in range(11, 21)]
    dati = _salvata(azienda, "vendite.prodotti").dati
    assert dati["spec"] == {"vista": "vendite.righe_vendute", "data": "ordine__data", "misura": "sum:quantita_base",
                            "filtri": {"quantita_base__isnull": False}, "raggruppa": "prodotto", "primi": 10,
                            "per": "mese", "orizzonte": 3}
    assert dati["risultato"]["esclusi_unita"] == 0
    gruppi = dati["risultato"]["gruppi"]
    assert [g["nome"] for g in gruppi] == [f"Articolo {i}" for i in range(10, 0, -1)]     # monitor e cavo fuori
    assert [g["chiave"] for g in gruppi] == [a.pk for a in reversed(articoli)]
    assert len(dati["risultato"]["periodi"]) == 3 and all(len(g["futuro"]) == 3 for g in gruppi)
    assert gruppi[0]["totale"] == {"basso_10": 20 * 3 - 2 * 3 - 3, "mediana": 20 * 3 + 3, "alto_90": 20 * 3 + 2 * 3 + 3}


@serve_vendite
def test_prodotti_nell_unita_del_prodotto(s, servizi):
    """Le quantità per prodotto sono nell'unità del prodotto: una dozzina di monitor vale 12; una riga in un'unità
    che non si converte (quantità nell'unità del prodotto vuota, per esempio importata) si esclude e si conta."""
    azienda, monitor, cavo = s["azienda"], s["monitor"], s["cavo"]
    from prodotti.models import UnitaMisura
    from vendite.models import RigaVendita
    dozzina = UnitaMisura.objects.create(simbolo="dz", nome="dozzina", categoria=UnitaMisura.PEZZI, fattore=12)
    ordine = _ordine(azienda, s["rossi"], [], 1, commerciale=s["anna"])
    RigaVendita.objects.create(ordine=ordine, prodotto=monitor, quantita=Decimal("1"), unita=dozzina)
    senza_fattore = RigaVendita.objects.create(ordine=ordine, prodotto=cavo, quantita=Decimal("100"))
    RigaVendita.objects.filter(pk=senza_fattore.pk).update(unita=UnitaMisura.objects.get(simbolo="gg"),
                                                           quantita_base=None)
    calcolo.vendite(azienda)

    risultato = _salvata(azienda, "vendite.prodotti").dati["risultato"]
    assert risultato["esclusi_unita"] == 1
    assert {g["nome"]: _valori(g) for g in risultato["gruppi"]} == {"Monitor": [1.0] * 7 + [13.0], "Cavo": [7.0] * 8}
    d = pronte.dati_per(richiesta_di(s["capo"], azienda), "vendite.prodotti")
    assert d["salvata"] is True and d["dati"]["esclusi_unita"] == 1
    RegolaRiga.objects.create(vista="vendite.righe_vendute", ruolo=s["anna"].profilo.ruolo,
                              campo="ordine__commerciale", operatore="utente")
    d = pronte.dati_per(richiesta_di(s["anna"], azienda), "vendite.prodotti")      # al momento, con le sue righe
    assert d["salvata"] is False and d["dati"]["esclusi_unita"] == 1
    assert {g["nome"]: _valori(g) for g in d["dati"]["gruppi"]} == {"Monitor": [1.0] * 7 + [13.0]}
    assert pronte.dati_per(richiesta_di(s["bruno"], azienda), "vendite.prodotti")["dati"]["esclusi_unita"] == 0


@serve_vendite
def test_filtri_dei_moduli_non_usano_le_salvate(s, servizi, monkeypatch):
    """Un modulo che toglie righe per utente (core.regole.registra_filtro, come Connettori con i dati di Odoo): chi
    ne perde qualcuna sulla vista di origine non vede le salvate, ma il calcolo con le sue righe."""
    azienda, capo = s["azienda"], s["capo"]
    _riserva("fatturazione", s["altra"])
    calcolo.vendite(azienda)
    salvata = _salvata(azienda, "vendite.fatturato_mese").dati["risultato"]
    sara = _utente("sara", azienda)                                           # nessun ruolo, nessuna regola di riga
    assert pronte.limitato(richiesta_di(sara, azienda), "vendite.ordini", ("data",)) is False

    def senza_bruno(vista, request, qs):                     # a chi non è superuser toglie gli ordini di Bruno
        if vista.slug == "ordini" and not request.user.is_superuser:
            return qs.exclude(commerciale__username="bruno")
        return qs
    monkeypatch.setattr(regole, "_FILTRI", [])
    regole.registra_filtro(senza_bruno)
    cache.clear()                                            # il confronto di prima (con i filtri di Connettori) è in cache
    request = richiesta_di(sara, azienda)
    assert pronte.limitato(request, "vendite.ordini", ("data",)) is True
    assert pronte.limitato(request, "vendite.righe_vendute", ("ordine",)) is False     # lì non toglie nulla
    assert pronte.limitato(richiesta_di(capo, azienda), "vendite.ordini", ("data",)) is False
    servizi.clear()
    d = pronte.dati_per(request, "vendite.fatturato_mese")
    assert d["salvata"] is False and _valori(d["dati"]) == [200.0] * 8 and d["dati"] != salvata
    assert servizi[0]["series"][0]["values"] == [200.0] * 8
    assert pronte.dati_per(richiesta_di(capo, azienda), "vendite.fatturato_mese")["salvata"] is True

    monkeypatch.setattr(regole, "_FILTRI", [lambda vista, request, qs: qs])      # il confronto resta in cache
    assert pronte.limitato(richiesta_di(sara, azienda), "vendite.ordini", ("data",)) is True

    def rotto(vista, request, qs):
        raise RuntimeError("filtro rotto")
    monkeypatch.setattr(regole, "_FILTRI", [rotto])
    ugo = _utente("ugo", azienda)
    assert pronte.limitato(richiesta_di(ugo, azienda), "vendite.righe_vendute", ("ordine",)) is True
    d = pronte.dati_per(richiesta_di(ugo, azienda), "vendite.prodotti")       # il filtro rotto nasconde tutto
    assert d["salvata"] is False and d["dati"] is None and d["errore"]


@serve_vendite
def test_notturno_salva_le_pronte_di_vendite(s, servizi, monkeypatch):
    azienda = s["azienda"]
    _riserva("fatturazione", s["altra"])
    senza_vendite = Azienda.objects.create(nome="Senza Vendite")
    spenta = Azienda.objects.create(nome="Spenta", attiva=False)
    _riserva("vendite", azienda, spenta)

    parametri.scrivi("previsioni.url_servizio", "")                           # servizio non configurato: niente
    calcolo.notturno()
    assert not PrevisionePronta.objects.exists() and not StatoCalcolo.objects.exists() and servizi == []

    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    installata = apps.is_installed                                            # Vendite senza Magazzino: si calcola
    monkeypatch.setattr(apps, "is_installed", lambda nome: nome != "magazzino" and installata(nome))
    risultato = calcolo.notturno()
    assert sorted(PrevisionePronta.objects.values_list("azienda", "chiave")) == sorted((azienda.pk, c) for c in CHIAVI)
    stato = StatoCalcolo.objects.get(azienda=azienda, cosa="vendite")
    assert stato.errore == "" and stato.ultimo_ok is not None
    assert list(StatoCalcolo.objects.values_list("azienda", "cosa")) == [(azienda.pk, "vendite")]
    assert risultato == "Previsioni salvate: 0 del magazzino e 3 di Vendite, per 1 aziende (0 con errori)."
    assert not PrevisionePronta.objects.filter(azienda__in=[senza_vendite, spenta]).exists()

    _riserva("previsioni", s["altra"])                                        # Previsioni riservata a un'altra: niente
    PrevisionePronta.objects.all().delete()
    calcolo.notturno()
    assert not PrevisionePronta.objects.exists()


@serve_vendite
def test_chi_ha_regole_di_riga_non_vede_le_salvate(s, servizi):
    azienda, capo, anna, bruno = s["azienda"], s["capo"], s["anna"], s["bruno"]
    _riserva("fatturazione", s["altra"])
    calcolo.vendite(azienda)                                                  # con l'intera azienda: 270 € al mese
    salvata = _salvata(azienda, "vendite.fatturato_mese").dati["risultato"]
    assert _valori(salvata) == [270.0] * 8

    assert pronte.limitato(richiesta_di(anna, azienda), "vendite.ordini", ("data", "imponibile")) is True
    assert pronte.limitato(richiesta_di(anna, azienda), "vendite.righe_vendute", ("ordine", "quantita")) is False
    assert pronte.limitato(richiesta_di(capo, azienda), "vendite.ordini", ("data", "imponibile")) is False
    senza_ruolo = _utente("sara", azienda)
    assert pronte.limitato(richiesta_di(senza_ruolo, azienda), "vendite.ordini", ("data", "imponibile")) is False

    assert [p["chiave"] for p in pronte.per_request(richiesta_di(anna, azienda))] == CHIAVI
    servizi.clear()
    d = pronte.dati_per(richiesta_di(anna, azienda), "vendite.fatturato_mese")
    assert d["salvata"] is False and d["errore"] == "" and d["calcolata_il"] is not None
    assert _valori(d["dati"]) == [200.0] * 8 and d["dati"] != salvata         # solo i suoi ordini
    assert servizi[0]["series"][0]["values"] == [200.0] * 8
    chiamate = len(servizi)
    assert pronte.dati_per(richiesta_di(anna, azienda), "vendite.fatturato_mese")["dati"] == d["dati"]
    assert len(servizi) == chiamate                                           # dalla cache, per lei
    assert _valori(pronte.dati_per(richiesta_di(bruno, azienda), "vendite.fatturato_mese")["dati"]) == [70.0] * 8
    clienti = pronte.dati_per(richiesta_di(anna, azienda), "vendite.clienti")["dati"]
    assert [g["nome"] for g in clienti["gruppi"]] == ["Rossi Srl"]

    # chi non ha regole vede le salvate, senza chiamare il servizio
    servizi.clear()
    for utente in (capo, senza_ruolo):
        d = pronte.dati_per(richiesta_di(utente, azienda), "vendite.fatturato_mese")
        assert d["salvata"] is True and d["dati"] == salvata
    assert servizi == []


@serve_vendite
def test_campo_nascosto_non_usa_le_salvate(s, servizi):
    azienda = s["azienda"]
    _riserva("fatturazione", s["altra"])
    calcolo.vendite(azienda)
    ridotto = Ruolo.objects.create(nome="Senza importi", livello_base="lavoro")
    carla = _utente("carla", azienda, ridotto)
    permesso = PermessoCampo.objects.create(vista="vendite.ordini", campo="imponibile", ruolo=ridotto,
                                            livello=PermessoCampo.NASCOSTO)
    request = richiesta_di(carla, azienda)
    assert pronte.limitato(request, "vendite.ordini", ("data", "imponibile")) is True
    assert pronte.limitato(request, "vendite.ordini", ("data", "cliente")) is False
    servizi.clear()
    d = pronte.dati_per(request, "vendite.fatturato_mese")                     # calcolata con i suoi permessi: no
    assert d["salvata"] is False and d["dati"] is None and "imponibile" in d["errore"]
    assert servizi == []
    assert pronte.dati_per(request, "vendite.prodotti")["salvata"] is True    # le righe vendute non lo nascondono

    permesso.campo = "riferimento_cliente"                                    # un campo che la previsione non usa
    permesso.save()
    d = pronte.dati_per(richiesta_di(carla, azienda), "vendite.fatturato_mese")
    assert d["salvata"] is True and d["dati"] == _salvata(azienda, "vendite.fatturato_mese").dati["risultato"]


@serve_vendite
def test_solo_con_i_permessi_delle_viste_di_origine(s, servizi):
    azienda = s["azienda"]
    _riserva("fatturazione", s["altra"])
    calcolo.vendite(azienda)
    senza_righe = _utente("dario", azienda, permessi=["vendite.view_ordinevendita", "previsioni.view_previsionepronta"])
    request = richiesta_di(senza_righe, azienda)
    assert [p["chiave"] for p in pronte.per_request(request)] == ["vendite.fatturato_mese", "vendite.clienti"]
    d = pronte.dati_per(request, "vendite.prodotti")
    assert d["dati"] is None and d["errore"] == "Previsione non disponibile per te in questa azienda."
    assert pronte.per_request(richiesta_di(_utente("elio", azienda, permessi=PERMESSI[:2]), azienda)) == []

    if apps.is_installed("fatturazione"):                                    # il fatturato vuole le fatture
        _riserva("fatturazione")
        assert [p["chiave"] for p in pronte.per_request(richiesta_di(senza_righe, azienda))] == []
        con_fatture = _utente("fabio", azienda, permessi=[*PERMESSI, "fatturazione.view_fattura"])
        assert [p["chiave"] for p in pronte.per_request(richiesta_di(con_fatture, azienda))] == CHIAVI


def test_senza_vendite_nessuna_pronta(db, monkeypatch):
    azienda = Azienda.objects.get(pk=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")

    chiamate = []
    monkeypatch.setattr(servizio, "chiama", lambda percorso, dati: chiamate.append(dati))
    if apps.is_installed("vendite"):                          # Vendite riservata a un'altra azienda (spenta: la notte no)
        _riserva("vendite", Azienda.objects.create(nome="Altra", attiva=False))
    assert pronte.per_request(richiesta_di(capo, azienda)) == []
    assert calcolo.eseguibile("vendite", azienda) is False
    calcolo.notturno()
    assert not PrevisionePronta.objects.exists() and not StatoCalcolo.objects.filter(cosa="vendite").exists()
    assert chiamate == []

    installata = apps.is_installed                                           # Vendite non installata
    monkeypatch.setattr(apps, "is_installed", lambda nome: nome != "vendite" and installata(nome))
    Modulo.objects.filter(slug="vendite").delete()
    assert pronte.per_request(richiesta_di(capo, azienda)) == []
    assert calcolo.eseguibile("vendite", azienda) is False
    assert calcolo.vendite(azienda) == 0 and not PrevisionePronta.objects.exists()


@serve_vendite
def test_servizio_giu_restano_le_salvate(s, servizi, monkeypatch):
    azienda = s["azienda"]
    _riserva("fatturazione", s["altra"])
    assert calcolo.vendite(azienda) == 3
    ieri = timezone.now() - datetime.timedelta(days=1)
    PrevisionePronta.objects.update(calcolata_il=ieri)
    prima = list(PrevisionePronta.objects.order_by("pk").values())

    def giu(richiesta, timeout=None):
        raise urllib.error.URLError("rete giù")
    monkeypatch.setattr(servizio, "chiama", CHIAMA_VERA)
    monkeypatch.setattr("urllib.request.urlopen", giu)
    risultato = calcolo.aggiorna(azienda_id=azienda.pk, cosa="vendite")
    assert risultato == "Previsioni non aggiornate: Il servizio di previsione non risponde: riprova tra poco."
    assert list(PrevisionePronta.objects.order_by("pk").values()) == prima
    stato = StatoCalcolo.objects.get(azienda=azienda, cosa="vendite")
    assert stato.errore == "Il servizio di previsione non risponde: riprova tra poco." and stato.ultimo_tentativo > ieri
    d = pronte.dati_per(richiesta_di(s["capo"], azienda), "vendite.fatturato_mese")
    assert d["salvata"] is True and d["calcolata_il"] == ieri and d["dati"] is not None
    d = pronte.dati_per(richiesta_di(s["anna"], azienda), "vendite.fatturato_mese")   # al momento: l'errore, non 500
    assert d["dati"] is None and d["errore"] == "Il servizio di previsione non risponde: riprova tra poco."
    assert calcolo.notturno().endswith("(1 con errori).")


@serve_vendite
def test_le_sostituzioni_si_mettono_in_fila_sullo_stato(s, servizi, monkeypatch):
    """Due sostituzioni delle righe della stessa azienda (la notte e «Aggiorna», un doppio clic) si aspettano: prima di
    cancellare si blocca la riga di StatoCalcolo dell'azienda (select_for_update; su SQLite non blocca nulla)."""
    passi = []
    blocca, cancella = QuerySet.select_for_update, QuerySet.delete

    def spia_blocca(self, *args, **kwargs):
        qs = blocca(self, *args, **kwargs)
        passi.append(("blocca", self.model, list(self.values_list("azienda", "cosa"))))
        return qs

    def spia_cancella(self):
        passi.append(("cancella", self.model, None))
        return cancella(self)
    monkeypatch.setattr(QuerySet, "select_for_update", spia_blocca)
    monkeypatch.setattr(QuerySet, "delete", spia_cancella)
    calcolo.vendite(s["azienda"])
    assert passi.index(("blocca", StatoCalcolo, [(s["azienda"].pk, "vendite")])) < passi.index(
        ("cancella", PrevisionePronta, None))


@serve_vendite
def test_aggiorna_le_pronte_di_vendite(s, servizi, client):
    azienda = s["azienda"]
    _riserva("fatturazione", s["altra"])
    url = reverse("previsioni:aggiorna") + "?cosa=vendite"
    norma = _utente("norma", azienda, permessi=["previsioni.change_previsionearticolo"])
    client.force_login(norma)
    assert client.post(url).status_code == 403                    # il permesso degli articoli non basta
    norma.user_permissions.add(Permission.objects.get(codename="change_previsionepronta"))
    with override_settings(LAVORI_SINCRONI=True):
        assert client.post(url).status_code == 302
    lavoro = Lavoro.objects.get(funzione="previsioni.calcolo.aggiorna")
    assert lavoro.argomenti == {"azienda_id": azienda.pk, "cosa": "vendite"} and lavoro.stato == Lavoro.FATTO
    assert lavoro.risultato == "3 previsioni salvate."
    assert PrevisionePronta.objects.filter(azienda=azienda).count() == 3

    _riserva("vendite", s["altra"])                                # Vendite non vale per l'azienda corrente
    assert client.post(url).status_code == 400
    assert Lavoro.objects.filter(funzione="previsioni.calcolo.aggiorna").count() == 1


def test_gruppo_utente_vede_le_pronte():
    import previsioni
    from core.registry import manifest
    gruppi = manifest.leggi(Path(previsioni.__file__).parent).groups
    assert "previsioni.view_previsionepronta" in gruppi["Previsioni / Utente"]


@serve_vendite
def test_misura_o_data_nascoste_al_ruolo_non_si_prevedono(s, servizi):
    """Un campo nascosto al ruolo non si somma e non si raggruppa nel tempo, nemmeno con una previsione (come in
    interroga.aggrega): né la misura né la data, per la serie singola e per gruppo."""
    azienda = s["azienda"]
    ridotto = Ruolo.objects.create(nome="Senza importi", livello_base="lavoro")
    carla = _utente("carla", azienda, ridotto)
    spec = {"vista": "vendite.ordini", "data": "data", "misura": "sum:imponibile", "per": "mese", "orizzonte": 3}
    PermessoCampo.objects.create(vista="vendite.ordini", campo="imponibile", ruolo=ridotto, livello=PermessoCampo.NASCOSTO)
    request = richiesta_di(carla, azienda)
    with pytest.raises(servizio.ErrorePrevisione, match="«imponibile» non è disponibile per il tuo ruolo"):
        motore.calcola_previsione(spec, request)
    with pytest.raises(servizio.ErrorePrevisione, match="«imponibile» non è disponibile per il tuo ruolo"):
        motore.calcola_per_gruppo({**spec, "raggruppa": "cliente"}, request)
    PermessoCampo.objects.all().delete()
    PermessoCampo.objects.create(vista="vendite.ordini", campo="data", ruolo=ridotto, livello=PermessoCampo.NASCOSTO)
    request = richiesta_di(User.objects.get(pk=carla.pk), azienda)
    with pytest.raises(servizio.ErrorePrevisione, match="«data» non è disponibile per il tuo ruolo"):
        motore.calcola_previsione({**spec, "misura": "count"}, request)
    with pytest.raises(servizio.ErrorePrevisione, match="«data» non è disponibile per il tuo ruolo"):
        motore.calcola_per_gruppo({**spec, "misura": "count", "raggruppa": "cliente"}, request)
    assert not servizi


@serve_vendite
def test_un_calcolo_dal_vivo_fallito_resta_in_cache_un_minuto(s, monkeypatch):
    """Ruling 27: chi calcola al momento e trova il servizio giù non lo richiama a ogni pagina: il fallimento resta in
    cache 60 s, per utente, azienda e chiave."""
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    chiamate, scadenze = [], {}

    def giu(percorso, dati):
        chiamate.append(dati)
        raise servizio.ErroreServizio("Il servizio di previsione non risponde: riprova tra poco.")
    monkeypatch.setattr(servizio, "chiama", giu)
    imposta = cache.set

    def spia(chiave, valore, timeout=None, **altro):
        scadenze[chiave] = timeout
        return imposta(chiave, valore, timeout, **altro)
    monkeypatch.setattr(cache, "set", spia)
    _riserva("fatturazione", s["altra"])                         # l'ordinato: Anna vede solo i suoi ordini, al momento
    anna, bruno, azienda = s["anna"], s["bruno"], s["azienda"]
    for _ in range(2):
        d = pronte.dati_per(richiesta_di(anna, azienda), "vendite.fatturato_mese")
        assert d["dati"] is None and d["errore"] == "Il servizio di previsione non risponde: riprova tra poco."
    assert len(chiamate) == 1
    assert scadenze[f"previsioni:pronta:{anna.pk}:{azienda.pk}:vendite.fatturato_mese"] == 60
    pronte.dati_per(richiesta_di(bruno, azienda), "vendite.fatturato_mese")      # un altro utente: la sua chiamata
    assert len(chiamate) == 2
