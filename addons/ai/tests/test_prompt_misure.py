"""Le misure aziendali nel prompt di sistema e i segnaposto dei grafici tolti dalle risposte."""
from ai import markdown
from ai.motore import prompt
from core import misure


def test_prompt_con_misure_stabile(db):
    testo = prompt.sistema()
    assert testo == prompt.sistema()                         # byte-stabile: la cache del prefisso regge
    assert "Misure aziendali" in testo and "fatturazione.fatturato" in testo
    assert testo.index("calendario.appuntamenti") < testo.index("fatturazione.fatturato") < testo.index("vendite.ordinato")
    assert "«Vendite» è il fatturato" in testo


def test_prompt_senza_misure(db, monkeypatch):
    monkeypatch.setattr(misure, "tutte", lambda: [])
    assert "Misure aziendali" not in prompt.sistema()


def test_rendi_toglie_segnaposto_artifact():
    html = str(markdown.rendi("Ecco:\n\n![Top 5 clienti](artifact:44)\n\nTotale **3 €**, vedi ![g](artifact:7) sotto."))
    assert "artifact:" not in html
    assert "Totale <strong>3 €</strong>" in html and "vedi  sotto" not in html
