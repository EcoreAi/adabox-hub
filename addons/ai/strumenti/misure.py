"""Lo strumento «misura»: le misure aziendali (core.misure) con la loro definizione fissa e i link ai record.
Le misure disponibili sono elencate nel prompt di sistema (ai.motore.prompt)."""
from core import misure

from . import richiesta
from .registro import Strumento, registra

NOTA = ("Riporta il valore e, la prima volta, la definizione in mezza frase. I link ai record e la definizione "
        "compaiono anche sotto la risposta.")


def misura(contesto, nome, periodo="", dal="", al="", per="", primi=None, confronta="", di="", aziende=None):
    r = misure.calcola(nome, richiesta.per(contesto), periodo=periodo, dal=dal or None, al=al or None, per=per,
                       primi=primi, confronta=confronta, aziende=aziende, di=di)
    return {**r, "nota": NOTA}


registra(Strumento(
    "misura", "Il valore di una misura aziendale dell'elenco «Misure aziendali» (fatturato, scaduto, ordinato, sotto "
              "scorta, appuntamenti...) con la sua definizione fissa: per periodo, raggruppato, i primi N, confrontato "
              "con il periodo prima o l'anno prima. Usalo per ogni domanda su queste misure.",
    {"type": "object", "properties": {
        "nome": {"type": "string", "description": "nome della misura come nell'elenco, es. fatturazione.fatturato"},
        "periodo": {"type": "string", "enum": list(misure.PERIODI),
                    "description": "periodo detto a parole (default: quello della misura); per anni o date precise usa dal e al"},
        "dal": {"type": "string", "description": "AAAA-MM-GG"}, "al": {"type": "string", "description": "AAAA-MM-GG"},
        "per": {"type": "string", "description": "raggruppamento della misura (es. cliente, mese)"},
        "primi": {"type": "integer", "description": "solo i primi N gruppi, dal più grande"},
        "confronta": {"type": "string", "enum": list(misure.CONFRONTI),
                      "description": "confronto con il periodo prima o con lo stesso tratto dell'anno prima"},
        "di": {"type": "string", "enum": ["miei", "tutti"], "description": "appuntamenti: i miei (default) o tutti"},
        "aziende": {"description": "consolidato di più aziende dell'utente: \"tutte\" o una lista di id"}},
     "required": ["nome"]}, misura))
