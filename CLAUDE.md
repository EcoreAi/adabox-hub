# Adabox: note per Claude

Le convenzioni del codice (moduli in `addons/<slug>`, servizi del kernel, viste) sono nel README.
Qui solo come lavorare sul repository.

## Ambiente

- Python **3.12**, come in produzione (`Dockerfile`) e in CI.
- Nel container di Sviluppo Control l'ambiente è già pronto in `.venv` (escluso da Git, resta tra un
  lavoro e l'altro): usa `.venv/bin/pytest` e `.venv/bin/python manage.py …`, non il `python3` di
  sistema (3.11, senza dipendenze). Se `.venv` manca o le dipendenze sono cambiate:
  `python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`.
- Database dei test: SQLite, niente da avviare.

## Test

- Durante il lavoro fai girare **solo i test di ciò che tocchi**, per esempio
  `.venv/bin/pytest -q -p no:cacheprovider addons/magazzino/tests core/tests/test_grafico.py`.
- La suite intera nel container è lenta (la sola parte veloce, `-m "not slow and not postgres and not pdf"`,
  richiede circa 35 minuti): non lanciarla a ogni passo. La CI di GitHub la fa girare tutta, divisa in
  quattro parti, con Postgres e con i PDF; i test `postgres` e `pdf` nel container non girano.
- Un modulo nuovo ha i test in `addons/<slug>/tests/` e lo slug va aggiunto a `ADDONS_FORCE` in `pytest.ini`.
- Una correzione arriva con un test che fallisce senza di essa.

## Rami e pull request

- Parti sempre da `main` aggiornato: `git fetch origin && git switch -c <ramo> origin/main`. Il `main`
  locale del container può essere indietro.
- Task di ichnohub: ramo `fix/T123-…` e titolo della pull request che comincia con `T123`, così ichnohub
  collega il task e lo chiude al merge.
- Nel container non c'è `gh`: la pull request la apre Sviluppo Control (flusso GitHub del progetto) o una
  persona. Se non riesci ad aprirla, dillo e fermati lì: non scrivere che è aperta.
- Mai push su `main` e mai merge: le pull request le rivede e le unisce una persona.
