"""Le definizioni degli strumenti di scrittura dell'assistente, per registrarli in Agate.

    python manage.py agate_strumenti --output strumenti.json
    (in Agate) manage.py agate_add_internal_tools <tenant> production strumenti.json

Solo le scritture: le letture non passano da Agate (non cambiano nulla). L'effetto in Agate viene
dal rischio dello strumento: `scrittura` → write, `irreversibile` → irreversible (in Agate sempre
con l'approvazione di una persona, salvo una regola esplicita)."""
import json

from django.core.management.base import BaseCommand

EFFETTI = {"scrittura": ("write", "medium"), "irreversibile": ("irreversible", "high")}
DESCRIZIONE_MAX = 300  # il limite delle descrizioni dei tool in Agate


def _breve(testo):
    testo = " ".join(testo.split())
    if len(testo) <= DESCRIZIONE_MAX:
        return testo
    return testo[:DESCRIZIONE_MAX - 1].rsplit(" ", 1)[0] + "…"


def definizioni(prefisso="adabox"):
    from ai.strumenti.registro import _registro
    from ai.strumenti import app

    app.carica()
    righe = []
    for nome, strumento in sorted(_registro.items()):
        if strumento.rischio not in EFFETTI:
            continue
        effetto, rischio = EFFETTI[strumento.rischio]
        righe.append({"slug": f"{prefisso}.{nome}", "description": _breve(strumento.descrizione),
                      "side_effect": effetto, "risk_level": rischio, "params_schema": strumento.schema,
                      "accepts_free_text": True})
    return righe


class Command(BaseCommand):
    help = "Stampa in JSON gli strumenti di scrittura dell'assistente, da registrare in Agate"

    def add_arguments(self, parser):
        parser.add_argument("--prefisso", default="")
        parser.add_argument("--output", default="", help="file su cui scrivere (UTF-8) invece della console")

    def handle(self, *args, **options):
        from agate.models import Collegamento

        c = Collegamento.attuale()
        prefisso = options["prefisso"] or (c.prefisso if c else "adabox")
        testo = json.dumps(definizioni(prefisso), ensure_ascii=False, indent=2)
        if options["output"]:
            with open(options["output"], "w", encoding="utf-8") as file:
                file.write(testo)
        else:
            self.stdout.write(testo)
