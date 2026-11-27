"""Colonna di sinistra della chat: Preferiti e Aree di lavoro hanno un campo che filtra le voci nella pagina, come la
Cronologia ha la sua ricerca. Il filtro lo fa chat.js nel browser (provato con jsdom fuori dal repository: la CI non ha
un DOM); qui si controlla ciò che gli serve nella pagina e che lo script ci sia."""
import re
from html import unescape

from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.urls import reverse

from ai.models import Artifact, Conversazione, DocumentoChat, ProgettoChat
from ai.tests.test_aree_piu_aziende import _pannello, p  # noqa: F401  (fixture)
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)


def _pagina(client):
    return client.get(reverse("ai:chat")).content.decode()


def _cerca(html):
    """I testi in cui si cerca, uno per voce, nell'ordine della pagina."""
    return [unescape(t) for t in re.findall(r'data-cerca="([^"]*)"', html)]


def test_preferiti_hanno_il_campo_e_le_voci_cercabili(p, client):
    chat = p["chat_r"]
    DocumentoChat.objects.create(conversazione=chat, utente=p["u"], azienda=p["rossi"], titolo="Offerta ponteggi", salvato=True)
    Artifact.objects.create(conversazione=chat, utente=p["u"], azienda=p["rossi"], tipo="tabella", titolo="Ore per fase",
                            spec={"tipo": "tabella", "vista": "core.aziende"}, dati={}, salvato=True)
    bruno = User.objects.create_user("bruno", password="x", first_name="Bruno")
    DocumentoChat.objects.create(conversazione=Conversazione.objects.create(utente=bruno), utente=bruno,
                                 titolo="Verbale riunione").condiviso_con.add(p["u"])
    pannello = _pannello(_pagina(client), "preferite")
    assert "data-filtra" in pannello.split(">")[0]
    assert 'placeholder="Cerca nei preferiti…"' in pannello and "data-filtra-campo" in pannello
    assert re.search(r'data-filtra-vuoto[^>]*hidden[^>]*>Nessun preferito trovato\.', pannello)
    assert pannello.count("data-filtra-gruppo") == 4                 # Chat, Documenti, Grafici e tabelle, Condivisi
    voci = _cerca(pannello)
    assert any("Chat di Rossi" in v and "Commessa Alfa" in v for v in voci)        # titolo e area
    assert any("Chat di Bianchi" in v and "Bianchi Spa" in v for v in voci)        # e azienda
    assert any(v.startswith("Offerta ponteggi") for v in voci)
    assert "Ore per fase" in voci
    assert any("Verbale riunione" in v and "Bruno" in v for v in voci)             # e chi l'ha condiviso


def test_aree_hanno_il_campo_e_le_voci_cercabili(p, client):
    pannello = _pannello(_pagina(client), "progetti")
    assert "data-filtra" in pannello.split(">")[0]
    assert 'placeholder="Cerca nelle aree…"' in pannello and "data-filtra-campo" in pannello
    assert re.search(r'data-filtra-vuoto[^>]*hidden[^>]*>Nessuna area trovata\.', pannello)
    assert pannello.count("data-filtra-gruppo") == 3                 # Rossi, Bianchi, Verdi
    assert {"Commessa Alfa", "Commessa Beta"} <= set(_cerca(pannello))
    # «Nuova chat» in Verdi, dove non c'è ancora un'area: non è un'area, mentre si cerca non si vede
    nuova = re.search(r'<li ([^>]*)>\s*<a href="[^"]*" data-cambia-azienda="%d"' % p["verdi"].pk, pannello)
    assert nuova and "data-filtra-nascondi" in nuova.group(1) and "data-cerca" not in nuova.group(1)


def test_il_campo_c_e_solo_se_c_e_qualcosa_da_cercare(s, client):
    """Preferiti: almeno una voce. Aree: almeno due, perché quella personale c'è sempre."""
    html = _pagina(client)
    assert "data-filtra-campo" not in _pannello(html, "preferite")
    assert "data-filtra-campo" not in _pannello(html, "progetti")
    ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Commessa Gamma")
    assert "data-filtra-campo" in _pannello(_pagina(client), "progetti")


def test_titolo_con_virgolette_resta_un_attributo(s, client):
    Conversazione.objects.create(utente=s["u"], titolo='Preventivo "Alfa" <bozza>', preferita=True)
    assert 'data-cerca="Preventivo &quot;Alfa&quot; &lt;bozza&gt;' in _pannello(_pagina(client), "preferite")


def test_l_albero_dell_area_non_ha_voci_cercabili(p, client):
    """Guardia: l'albero si carica quando si apre un'area, anche mentre si cerca; le sue righe non sono aree."""
    risposta = client.get(reverse("ai:albero_progetto", args=[p["area_r"].pk]))
    assert risposta.status_code == 200 and "data-cerca" not in risposta.content.decode()


def test_lo_script_filtra_i_pannelli():
    js = open(finders.find("ai/chat.js"), encoding="utf-8").read()
    for pezzo in ("[data-filtra]", "[data-filtra-campo]", "normalize('NFD')", "parole.every", "dataset.cerca",
                  "dataset.totale", "[data-filtra-nascondi]", "[data-filtra-gruppo]", "[data-filtra-vuoto]"):
        assert pezzo in js, pezzo
