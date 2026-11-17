"""La chat che si allarga: con «Larga» e «Piena» la risposta (testo, grafici, tabelle) segue la colonna invece di
restare stretta a sinistra. Senza un browser nei test, si controllano le regole che lo decidono."""
import re
from pathlib import Path

STATICI = Path(__file__).resolve().parent.parent / "static" / "ai"
CSS = (STATICI / "chat.css").read_text(encoding="utf-8")
JS = (STATICI / "chat.js").read_text(encoding="utf-8")


def _regola(selettore):
    m = re.search(re.escape(selettore) + r"\s*\{([^}]*)\}", CSS)
    return m.group(1) if m else ""


def test_la_risposta_occupa_la_colonna():
    regola = _regola(".ai-msg-assistente .ai-msg-corpo")
    assert "flex: 1 1 auto" in regola and "width: 100%" in regola


def test_testo_non_fermo_a_82_battute():
    assert "82ch" not in CSS
    assert "max-width: 120ch" in _regola(".ai-chat.is-piena .ai-md > :is(p, ul, ol, blockquote, h1, h2, h3, h4)")


def test_grafici_con_altezza_massima():
    assert "max-height: 420px" in _regola(".ai-artifact-grafico svg")


def test_modalita_piena_segnata_sulla_chat():
    assert "chat.classList.toggle('is-piena', valore === 'piena')" in JS
