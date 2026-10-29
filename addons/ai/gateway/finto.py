"""Modello finto per test e demo: risponde da un copione (o fa l'eco della domanda) senza rete né costi.

Nel copione ogni risposta è una lista di pezzi: str (testo), ("strumento", nome, argomenti),
("errore", codice), oppure una funzione(messaggi) che restituisce una di queste liste."""
from contextlib import contextmanager

from .tipi import ChiamataStrumento, ErroreModello, Fine, Testo, Uso

_copione = []
chiamate = []                          # le richieste ricevute (per i test)


@contextmanager
def con_copione(risposte):
    _copione[:] = list(risposte)
    chiamate.clear()
    try:
        yield chiamate
    finally:
        _copione.clear()


def flusso(modello, chiave, *, sistema, messaggi, strumenti=(), max_token=16000, effort="", http_client=None):
    chiamate.append({"modello": modello.id_api, "sistema": sistema, "messaggi": messaggi,
                     "strumenti": [s["nome"] for s in strumenti], "effort": effort})
    if _copione:
        risposta = _copione.pop(0)
        if callable(risposta):
            risposta = risposta(messaggi)
    else:
        ultima = next((m["testo"] for m in reversed(messaggi) if m["ruolo"] == "utente"), "")
        risposta = [f"Risposta di prova (modello finto) a: {ultima.splitlines()[-1] if ultima else ''}"]
    blocchi, n = [], 0
    for pezzo in risposta:
        if isinstance(pezzo, tuple) and pezzo[0] == "errore":
            raise ErroreModello(pezzo[1], "errore simulato")
        if isinstance(pezzo, tuple) and pezzo[0] == "strumento":
            n += 1
            blocchi.append({"tipo": "strumento", "id": f"finto_{len(chiamate)}_{n}", "nome": pezzo[1],
                            "argomenti": pezzo[2]})
            yield ChiamataStrumento(blocchi[-1]["id"], pezzo[1], pezzo[2])
        else:
            if blocchi and blocchi[-1]["tipo"] == "testo":
                blocchi[-1]["testo"] += pezzo
            else:
                blocchi.append({"tipo": "testo", "testo": pezzo})
            yield Testo(pezzo)
    yield Uso(input=sum(len(str(m)) for m in messaggi) // 4 + len(sistema) // 4, output=sum(
        len(b.get("testo", "")) for b in blocchi) // 4 + 1)
    yield Fine("strumenti" if any(b["tipo"] == "strumento" for b in blocchi) else "fine", blocchi)
