"""Venduto per prodotto: le righe degli ordini confermati che contano nel totale (le opzionali solo se scelte),
sommate per prodotto. Stesso totale dell'ordinato; il clic sul gruppo apre proprio quelle righe."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from contatti.models import Contatto
from core import misure
from core.models import Azienda
from core.viste.interroga import richiesta_di
from vendite.models import OrdineVendita, RigaVendita


@pytest.fixture
def scena(db, client):
    import fiscale
    import prodotti
    from prodotti.models import Prodotto
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    bianchi = Contatto.objects.create(azienda=azienda, nome="Bianchi Spa", cliente=True)
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"))
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", prezzo_vendita=Decimal("10"))
    return {"azienda": azienda, "req": richiesta_di(capo), "rossi": rossi, "bianchi": bianchi, "monitor": monitor,
            "cavo": cavo, "client": client}


def _ordine(s, cliente, righe, stato=OrdineVendita.CONFERMATO):
    o = OrdineVendita.objects.create(azienda=s["azienda"], cliente=cliente)
    for prodotto, quantita, extra in righe:
        RigaVendita.objects.create(ordine=o, prodotto=prodotto, quantita=Decimal(quantita), **extra)
    o.ricalcola()
    OrdineVendita.objects.filter(pk=o.pk).update(stato=stato)
    return o


@pytest.fixture
def ordini(scena):
    s = scena
    _ordine(s, s["rossi"], [(s["monitor"], "3", {}), (s["cavo"], "5", {})])
    _ordine(s, s["bianchi"], [(s["monitor"], "1", {}), (s["cavo"], "20", {"opzionale": True}),   # non scelta: fuori
                              (s["cavo"], "2", {"opzionale": True, "scelta": True})])            # scelta: dentro
    _ordine(s, s["rossi"], [(s["monitor"], "9", {})], stato=OrdineVendita.BOZZA)                # preventivo: fuori
    return s


def test_venduto_per_prodotto(ordini):
    r = misure.calcola("vendite.venduto", ordini["req"], periodo="anno", per="prodotto")
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("Monitor", 800), ("Cavo", 70)]
    assert r["valore"] == misure.calcola("vendite.ordinato", ordini["req"], periodo="anno")["valore"] == 870


def test_quantita_venduta_per_prodotto(ordini):
    r = misure.calcola("vendite.quantita_venduta", ordini["req"], periodo="anno", per="prodotto")
    assert {g["gruppo"]: g["valore"] for g in r["gruppi"]} == {"Monitor": 4, "Cavo": 7}


def test_venduto_per_cliente_e_mese(ordini):
    per_cliente = misure.calcola("vendite.venduto", ordini["req"], periodo="anno", per="cliente")
    assert {g["gruppo"]: g["valore"] for g in per_cliente["gruppi"]} == {"Rossi Srl": 650, "Bianchi Spa": 220}
    assert misure.calcola("vendite.venduto", ordini["req"], periodo="anno", per="mese")["valore"] == 870


def test_il_clic_apre_proprio_quelle_righe(ordini):
    """Il link del gruppo «Cavo» apre la lista delle righe vendute del cavo: le stesse 2 righe che fanno 70 €."""
    r = misure.calcola("vendite.venduto", ordini["req"], periodo="anno", per="prodotto")
    cavo = next(g for g in r["gruppi"] if g["gruppo"] == "Cavo")
    assert cavo["url"] and f"f_prodotto={ordini['cavo'].pk}" in cavo["url"]
    pagina = ordini["client"].get(cavo["url"]).content.decode()
    assert pagina.count("/vendite/righe_vendute/") >= 2 and "Monitor" not in pagina.split("<tbody")[1]


def test_righe_vendute_in_sola_lettura_e_per_azienda(ordini):
    from core.viste import registry
    vista = next(v for v in registry.viste_di("vendite") if v.slug == "righe_vendute")
    req = ordini["req"]
    assert not vista.has_add_permission(req) and not vista.has_change_permission(req) and not vista.has_delete_permission(req)
    assert vista.get_queryset(req).count() == 4                            # 2 + 1 + 1 opzionale scelta
    altra = Azienda.objects.create(nome="Beta")
    req.azienda = altra
    assert vista.get_queryset(req).count() == 0
    assert ordini["client"].get("/vendite/righe_vendute/nuovo/").status_code in (403, 404)


def test_righe_vendute_non_indicizzate_per_la_ricerca(db):
    from ai import conoscenza
    assert "vendite.rigavendita" not in {v.opts.label_lower for v, _ in conoscenza._viste_indicizzabili()}
