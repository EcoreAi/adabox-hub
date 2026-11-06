"""Due strumenti con lo stesso nome: il registro tiene l'ultimo e l'altro sparisce senza errori (era successo a
leggi_documento dell'archivio, coperto da quello dei documenti della chat). Questo test lo impedisce."""
import ast
from collections import Counter
from pathlib import Path

from ai.strumenti import registro

RADICE = Path(__file__).resolve().parents[3]


def _nomi_registrati():
    """(nome, file) di ogni registra(Strumento("nome", ...)) nei sorgenti di kernel e moduli."""
    for file in list((RADICE / "addons").glob("*/**/*.py")) + list((RADICE / "core").glob("**/*.py")):
        if "migrations" in file.parts or "tests" in file.parts:
            continue
        try:
            albero = ast.parse(file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for nodo in ast.walk(albero):
            if (isinstance(nodo, ast.Call) and getattr(nodo.func, "id", getattr(nodo.func, "attr", "")) == "Strumento"
                    and nodo.args and isinstance(nodo.args[0], ast.Constant) and isinstance(nodo.args[0].value, str)):
                yield nodo.args[0].value, file.relative_to(RADICE)


def test_nessun_nome_doppio():
    voci = list(_nomi_registrati())
    doppi = {n: [str(f) for nome, f in voci if nome == n] for n, quante in Counter(n for n, _ in voci).items() if quante > 1}
    assert len(voci) > 20 and not doppi, doppi


def test_leggi_documento_legge_l_archivio():
    import ai.strumenti  # noqa: F401  (registra gli strumenti)
    assert registro._registro["leggi_documento"].app == "documenti"
    assert "leggi_documento_chat" in registro._registro
