"""«Cerca ovunque»: oltre ai record, i grafici e le pagine di Analisi e le voci di menu, per parole (con i sinonimi
delle misure aziendali: «vendite» trova «Fatturato»); se nessun grafico corrisponde, il link per chiederlo ad Ada."""
import pytest

from core import cerca


def test_parole_tolgono_le_parole_vuote():
    assert cerca.parole("Grafico delle vendite di quest'anno") == (["vendite"], ["quest", "anno"])


def test_corrisponde_con_i_sinonimi_delle_misure(db):
    richieste, _ = cerca.parole("grafico vendite quest'anno")
    assert cerca.punteggio("Fatturato per mese", richieste) > 0              # vendite = fatturato
    assert cerca.punteggio("Vendite mensili 2026", richieste) > 0
    assert cerca.punteggio("Ticket per priorità", richieste) == 0
    assert cerca.punteggio("Scadenziario", cerca.parole("scadenz")[0]) > 0      # inizio di parola


def test_voci_di_menu(client, superuser):
    html = client.get("/cerca/", {"q": "scadenziario"}).content.decode()
    assert "Fatturazione" in html and "Scadenziario" in html and "/fatturazione/scadenzario/" in html


@pytest.mark.parametrize("q", ["grafico vendite quest'anno", "grafici vendite"])
def test_senza_grafici_propone_ada(client, superuser, q):
    html = client.get("/cerca/", {"q": q}).content.decode()
    assert "Chiedi ad Ada" in html and "/ai/chat/?chiedi=" in html
