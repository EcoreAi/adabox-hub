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


# ---------- le pagine per nome: «Grafici», «Statistiche» (segnalazione: non trovavano nulla) ----------

def test_le_parole_generiche_da_sole_contano():
    assert cerca.parole("Grafici") == (["grafici"], [])
    assert cerca.parole("le statistiche") == (["statistiche"], [])
    assert cerca.parole("grafici vendite") == (["vendite"], [])                     # in una frase no


def _scorciatoie(client, q):
    import re
    html = client.get("/cerca/", {"q": q}).content.decode()
    return html, re.findall(r'<a class="ui-link" href="([^"]+)">([^<]+)</a> <small class="ui-help">', html)


def test_grafici_porta_alla_pagina_per_crearli(client, superuser):
    html, voci = _scorciatoie(client, "Grafici")
    assert ("/grafici/costruttore/", "Nuovo grafico") in voci and ("/grafici/salvati/", "Analisi › Grafici salvati") in voci
    assert "/ai/chat/?chiedi=" not in html                   # «grafici» non è un grafico da disegnare: niente proposta


def test_statistiche_porta_a_statistiche_una_volta_sola(client, superuser):
    _, voci = _scorciatoie(client, "statistiche")
    assert [u for u, _ in voci].count("/grafici/") == 1      # pagina di Analisi e voce di menu: lo stesso indirizzo
    _, voci = _scorciatoie(client, "dashboard")              # anche per le sue parole
    assert "/grafici/" in [u for u, _ in voci] and "/dashboard/" in [u for u, _ in voci]


def test_le_pagine_del_kernel_con_i_permessi(client, superuser, django_user_model):
    _, voci = _scorciatoie(client, "utenti")
    assert ("/utenti/", "Utenti e ruoli") in voci
    semplice = django_user_model.objects.create_user("semplice", password="pass12345!")
    client.force_login(semplice)
    _, voci = _scorciatoie(client, "utenti")
    assert "/utenti/" not in [u for u, _ in voci]
    _, voci = _scorciatoie(client, "password")
    assert ("/accounts/password_change/", "Cambia password") in voci
