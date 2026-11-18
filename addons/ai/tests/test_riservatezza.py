"""Fonti riservate: quali sono e cosa ha letto uno strumento (piano 2026-11-18-chat-riservate)."""
import pytest
from django.contrib.auth.models import User

from ai.models import Conversazione
from core import parametri
from core.models import Azienda


@pytest.fixture
def azienda(db):
    return Azienda.objects.get(pk=1)


def test_campi_e_impostazione_di_partenza(azienda):
    from documenti.models import Cartella
    c = Conversazione.objects.create(utente=User.objects.create_user("u"))
    assert c.riservata is False and c.riservata_motivo == ""
    assert parametri.leggi("ai.app_riservate", azienda) == ""
    assert Cartella.objects.create(azienda=azienda, nome="Archivio").riservata is False


# --- Task 2: quali fonti sono riservate e cosa ha letto uno strumento ---

import json

from ai import riservatezza


def _riserva_app(azienda, testo):
    parametri.scrivi("ai.app_riservate", testo, azienda)


def _cartelle(azienda):
    from documenti.models import Cartella, Documento
    personale = Cartella.objects.create(azienda=azienda, nome="Personale", riservata=True)
    buste = Cartella.objects.create(azienda=azienda, nome="Buste paga", padre=personale)
    altro = Cartella.objects.create(azienda=azienda, nome="Altro")
    doc_buste = Documento.objects.create(azienda=azienda, cartella=buste, nome="busta.pdf")
    doc_altro = Documento.objects.create(azienda=azienda, cartella=altro, nome="listino.pdf")
    return {"personale": personale, "altro": altro, "doc_buste": doc_buste, "doc_altro": doc_altro}


def test_app_riservate_normalizza(azienda):
    _riserva_app(azienda, " Personale, BANCA ,")
    assert riservatezza.app_riservate(azienda) == {"personale", "banca"}


def test_vista_di_app_riservata(azienda):
    _riserva_app(azienda, "personale")
    assert riservatezza.fonte_riservata("cerca_record", {"vista": "personale.dipendenti"}, "[]", azienda) == "app «personale»"
    assert riservatezza.fonte_riservata("cerca_record", {"vista": "vendite.ordini"}, "[]", azienda) == ""


def test_misura_con_componente_riservato(azienda, monkeypatch):
    from core import misure
    finta = misure.Misura(nome="fatturazione.saldo", etichetta="Saldo", definizione="", app="fatturazione",
                          componenti=(misure.Componente(vista="banca.movimenti", misura="count"),))
    monkeypatch.setattr(misure, "per_nome", lambda nome: finta)
    _riserva_app(azienda, "banca")
    assert riservatezza.fonte_riservata("misura", {"nome": "fatturazione.saldo"}, "{}", azienda) == "app «banca»"
    assert riservatezza.fonte_riservata("grafico", {"misura_aziendale": "fatturazione.saldo"}, "{}", azienda) == "app «banca»"


def test_strumento_di_app_riservata(azienda):
    _riserva_app(azienda, "calendario")
    assert riservatezza.fonte_riservata("calendario_agenda", {}, "{}", azienda, app_strumento="calendario") == "app «calendario»"
    assert riservatezza.fonte_riservata("data_e_ora", {}, "{}", azienda) == ""


def test_analisi_riservata_se_c_e_un_app_riservata(azienda):
    assert riservatezza.fonte_riservata("analisi_leggi_pagina", {"id": 1}, "{}", azienda) == ""
    _riserva_app(azienda, "personale")
    assert riservatezza.fonte_riservata("analisi_leggi_pagina", {"id": 1}, "{}", azienda) != ""


def test_documento_in_sottocartella_riservata(azienda):
    c = _cartelle(azienda)
    assert riservatezza.fonte_riservata("leggi_documento", {"id": c["doc_buste"].pk}, "", azienda) == "cartella «Personale»"
    assert riservatezza.fonte_riservata("leggi_foglio", {"id": c["doc_altro"].pk}, "", azienda) == ""
    c["altro"].padre = c["personale"]                 # spostata sotto la riservata: vale subito
    c["altro"].save()
    assert riservatezza.fonte_riservata("leggi_documento", {"id": c["doc_altro"].pk}, "", azienda) == "cartella «Personale»"


def test_cerca_conoscenza_risultati_misti(azienda):
    c = _cartelle(azienda)
    risultati = [{"n": 1, "vista": "documenti.documenti", "id": c["doc_buste"].pk},
                 {"n": 2, "vista": "documenti.documenti", "id": c["doc_altro"].pk}]
    contenuto = json.dumps({"risultati": risultati}, ensure_ascii=False)
    assert riservatezza.fonte_riservata("cerca_conoscenza", {"domanda": "x"}, contenuto, azienda) == "cartella «Personale»"
    assert [r["n"] for r in riservatezza.risultati_ammessi(risultati, azienda)] == [2]
    troncato = contenuto[:75] +"\n[…risultato troncato: 999 caratteri in tutto]"      # JSON rotto: si legge lo stesso
    assert riservatezza.fonte_riservata("cerca_conoscenza", {}, troncato, azienda) == "cartella «Personale»"


def test_cerca_conoscenza_record_di_app_riservata(azienda):
    _riserva_app(azienda, "personale")
    contenuto = json.dumps({"risultati": [{"n": 1, "vista": "personale.dipendenti", "id": 4}]})
    assert riservatezza.fonte_riservata("cerca_conoscenza", {}, contenuto, azienda) == "app «personale»"


def test_segna_tiene_il_primo_motivo(azienda):
    c = Conversazione.objects.create(utente=User.objects.create_user("v"))
    riservatezza.segna(c, "app «personale»")
    riservatezza.segna(c, "cartella «X»")
    c.refresh_from_db()
    assert c.riservata and c.riservata_motivo == "app «personale»"


# --- Revisione finale: dati che entrano prima di qualunque strumento, viste generiche dei Documenti, voce ---

from types import SimpleNamespace


def test_motivo_record(azienda):
    c = _cartelle(azienda)
    _riserva_app(azienda, "personale")
    assert riservatezza.motivo_record(SimpleNamespace(modulo="personale"), object(), azienda) == "app «personale»"
    assert riservatezza.motivo_record(SimpleNamespace(modulo="documenti"), c["doc_buste"], azienda) == "cartella «Personale»"
    assert riservatezza.motivo_record(SimpleNamespace(modulo="documenti"), c["personale"], azienda) == "cartella «Personale»"
    assert riservatezza.motivo_record(SimpleNamespace(modulo="documenti"), c["doc_altro"], azienda) == ""
    assert riservatezza.motivo_record(SimpleNamespace(modulo="vendite"), object(), azienda) == ""


def test_motivo_pagina(azienda):
    c = _cartelle(azienda)
    assert riservatezza.motivo_pagina("/grafici/pagine/1/", azienda) == ""
    _riserva_app(azienda, "personale")
    assert riservatezza.motivo_pagina("/personale/dipendenti/3/", azienda) == "app «personale»"
    assert riservatezza.motivo_pagina(f"/documenti/documenti/{c['doc_buste'].pk}/", azienda) == "cartella «Personale»"
    assert riservatezza.motivo_pagina(f"/documenti/cartelle/{c['personale'].pk}/", azienda) == "cartella «Personale»"
    assert riservatezza.motivo_pagina(f"/documenti/documenti/{c['doc_altro'].pk}/", azienda) == ""
    assert riservatezza.motivo_pagina("/grafici/pagine/1/", azienda) != ""      # Analisi: dati di ogni app
    assert riservatezza.motivo_pagina("/vendite/ordini/", azienda) == ""


def test_documenti_con_le_viste_generiche(azienda):
    """cerca_record/leggi_record su documenti.* mostrano nomi e percorsi dei documenti riservati."""
    assert riservatezza.fonte_riservata("cerca_record", {"vista": "documenti.documenti"}, "[]", azienda) == ""
    c = _cartelle(azienda)
    assert riservatezza.fonte_riservata("leggi_record", {"vista": "documenti.documenti", "id": c["doc_buste"].pk}, "{}",
                                        azienda) == "cartella «Personale»"
    assert riservatezza.fonte_riservata("leggi_record", {"vista": "documenti.documenti", "id": c["doc_altro"].pk}, "{}",
                                        azienda) == ""
    assert riservatezza.fonte_riservata("cerca_record", {"vista": "documenti.documenti"}, "[]", azienda) != ""
    assert riservatezza.fonte_riservata("aggrega_record", {"vista": "documenti.cartelle"}, "[]", azienda) != ""


def test_lettura_ad_alta_voce_solo_locale_nelle_chat_riservate(azienda, monkeypatch):
    from ai import voce
    from ai.models import ServizioVoce
    monkeypatch.setattr(voce, "accesa", lambda az: True)
    monkeypatch.setattr(voce, "url_locale", lambda: "http://speaches:8000")
    parametri.scrivi("ai.voce_cloud", True, azienda)
    cloud = ServizioVoce.objects.create(nome="Cartesia", tipo=ServizioVoce.CARTESIA)
    assert voce.servizio_per(azienda) == cloud
    assert voce.servizio_per(azienda, solo_locale=True) is None
    locale = ServizioVoce.objects.create(nome="Kokoro", tipo=ServizioVoce.KOKORO)
    assert voce.servizio_per(azienda, solo_locale=True) == locale
