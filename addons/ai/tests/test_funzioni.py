"""Funzioni dell'assistente comprese nella licenza: strumenti, pagine, menu, impostazioni e chat."""
import datetime
import io
import json

import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse
from django.utils import timezone

from ai import licenza, pagine
from ai.models import Licenza
from ai.strumenti import registro, web
from ai.tests.test_licenza import _licenza, chiavi  # noqa: F401  (fixture)
from core import funzioni, parametri
from core import licenza as licenza_istanza
from core.registry import modules, pacchetti


def _solo(chiavi, *chiavi_funzioni):  # noqa: F811
    Licenza.objects.create(testo=_licenza(chiavi, funzioni=list(chiavi_funzioni)))


def test_formato_vecchio_e_senza_funzioni_le_comprendono_tutte(db, chiavi):  # noqa: F811
    assert licenza.leggi(_licenza(chiavi, funzioni=["chat", "strumenti", "conoscenza"])).funzioni is None
    senza = json.loads(_licenza(chiavi))
    del senza["licenza"]["funzioni"]
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    testo = json.dumps(licenza.firma(senza["licenza"], load_pem_private_key(chiavi.read_bytes(), None)))
    assert licenza.leggi(testo).funzioni is None
    assert licenza.leggi(_licenza(chiavi, funzioni=["memoria"])).funzioni == frozenset({"memoria"})


def test_senza_licenza_propria_valgono_le_funzioni_della_licenza_dell_istanza(db, chiavi, settings):  # noqa: F811
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    privata = load_pem_private_key(chiavi.read_bytes(), None)
    scadenza = (timezone.localdate() + datetime.timedelta(days=30)).isoformat()
    licenza_istanza.salva(json.dumps(licenza_istanza.firma(
        {"cliente": "Rossi Srl", "moduli": ["ai"], "scadenza": scadenza, "emessa": timezone.now().isoformat(),
         "funzioni": {"ai": ["memoria", "ricerca_web"]}}, privata)))
    assert licenza.attuale().funzioni == frozenset({"memoria", "ricerca_web"})
    assert funzioni.attiva("ai", "memoria") and not funzioni.attiva("ai", "aree_di_lavoro")


def test_gli_strumenti_delle_funzioni_non_comprese_non_ci_sono(db, chiavi, superuser):  # noqa: F811
    tutti = {s.nome for s in registro.disponibili(superuser)}
    assert {"crea_record", "grafico", "ricorda", "cerca_conoscenza"} <= tutti
    _solo(chiavi, "memoria")
    nomi = {s.nome for s in registro.disponibili(superuser)}
    assert {"ricorda", "data_e_ora", "cerca_record", "leggi_allegato"} <= nomi        # di base e la memoria
    assert not nomi & {"cerca_web", "leggi_pagina", "crea_record", "elimina_record", "grafico", "scrivi_documento",
                       "cerca_conoscenza", "crea_pianificata", "chiedi_esperto", "previsione"}
    # ogni strumento dell'assistente o è di base o appartiene a una funzione del catalogo
    catalogo = {f["chiave"] for f in funzioni.catalogo("ai")}
    from ai import funzioni as funzioni_ai
    assert set(funzioni_ai.STRUMENTI.values()) <= catalogo
    assert set(funzioni_ai.STRUMENTI) <= set(registro._registro)


def test_pagine_menu_e_chat_senza_le_funzioni(db, chiavi, superuser, client):  # noqa: F811
    _solo(chiavi, "memoria")
    voci = next(a for a in modules.app_visibili(superuser) if a["slug"] == "ai")["menu"]
    etichette = {v["label"] for v in voci}
    assert "Chat" in etichette and not etichette & {"Pianificate", "Assistenti", "Voce", "Sistemi esterni (MCP)", "Registro modifiche"}
    assert client.get(reverse("ai:memoria_lista")).status_code == 200
    for nome in ("ai:pianificate_lista", "ai:progetti_lista", "ai:mcp_lista", "ai:voce_lista", "ai:assistenti_lista"):
        assert client.get(reverse(nome)).status_code in (403, 404), nome
    html = client.get(reverse("ai:chat")).content.decode()
    assert 'data-pannello="progetti"' not in html and "ai-barra-area" not in html
    assert reverse("ai:memoria_lista") in html and reverse("ai:pianificate_lista") not in html
    assert pagine.livelli_modello(None) == []
    assert client.get(reverse("ai:progetto", args=[1])).status_code == 404
    assert client.post(reverse("ai:area_corrente"), {"area": "1"}).status_code == 404


def test_con_tutte_le_funzioni_la_chat_ha_aree_e_pianificate(db, superuser, client):
    html = client.get(reverse("ai:chat")).content.decode()
    assert 'data-pannello="progetti"' in html and reverse("ai:pianificate_lista") in html


def test_impostazioni_e_ricerca_web_seguono_la_licenza(db, chiavi, monkeypatch):  # noqa: F811
    valori = {"ai.url_ricerca_web": "http://searxng:8080", "ai.ricerca_web": True}
    originale = web.parametri.leggi
    monkeypatch.setattr(web.parametri, "leggi", lambda chiave, azienda=None: valori.get(chiave, originale(chiave, azienda)))
    assert web.abilitata(None)
    assert "ricerca_web" in parametri.ImpostazioniForm("ai", None).fields
    _solo(chiavi, "memoria")
    assert not web.abilitata(None)
    campi = parametri.ImpostazioniForm("ai", None).fields
    assert "tetto_mensile" in campi and not {"ricerca_web", "url_ricerca_web", "voce", "url_embeddings"} & set(campi)


def test_il_comando_emette_solo_funzioni_del_catalogo(db, chiavi, tmp_path):  # noqa: F811
    uscita = tmp_path / "l.json"
    call_command("ai_licenza", "--chiave", str(chiavi), "--cliente", "X", "--scadenza", "2099-12-31",
                 "--funzioni", "memoria, ricerca_web", "--uscita", str(uscita), stdout=io.StringIO())
    assert licenza.leggi(uscita.read_text()).funzioni == frozenset({"memoria", "ricerca_web"})
    with pytest.raises(CommandError, match="sconosciute: volare"):
        call_command("ai_licenza", "--chiave", str(chiavi), "--cliente", "X", "--scadenza", "2099-12-31",
                     "--funzioni", "memoria,volare", stdout=io.StringIO())
