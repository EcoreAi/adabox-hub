"""Lo strumento dell'assistente AI per le previsioni (chiave "ai" del manifest): `previsione`, sul motore del modulo."""
from ai import artifact
from ai.models import Artifact
from ai.strumenti import ErroreStrumento, Strumento, registra, richiesta
from ai.strumenti.viste import FILTRI, TESTO, VISTA, vista_per

from . import motore, servizio
from .motore import MAX_ORIZZONTE
from .servizio import ErrorePrevisione


def previsione(contesto, vista="", data="", misura="count", per="mese", orizzonte=3, filtri=None, testo="", titolo="",
               misura_aziendale="", raggruppa="", primi=10):
    try:
        orizzonte = max(1, min(int(orizzonte), MAX_ORIZZONTE))
    except (TypeError, ValueError):
        raise ErroreStrumento("«orizzonte» è un numero intero di periodi.")
    if raggruppa:
        try:
            primi = max(1, min(int(primi or 10), 50))
        except (TypeError, ValueError):
            raise ErroreStrumento("«primi» è un numero intero di gruppi.")
    if contesto.conversazione is None:
        raise ErroreStrumento("Le previsioni si mostrano solo in una chat.")
    if not servizio.abilitato(contesto.azienda, contesto.utente):     # spento o riservato ad altre aziende
        raise ErroreStrumento(servizio.SENZA_MODULO)
    if misura_aziendale:
        from core import misure
        spec = {"tipo": Artifact.GRAFICO, "grafico": "previsione", "misura_aziendale": misura_aziendale, "per": per,
                "orizzonte": orizzonte}
        predefinito = f"Previsione {misure.per_nome(misura_aziendale).etichetta.lower()} per {per}"
    elif vista and data:
        spec = {"tipo": Artifact.GRAFICO, "grafico": "previsione", "vista": vista, "data": data,
                "misura": misura or "count", "per": per, "orizzonte": orizzonte, "filtri": filtri or {}, "testo": testo or ""}
        predefinito = f"Previsione {vista}: {misura or 'count'} per {per}"
    else:
        raise ErroreStrumento("Indica «misura_aziendale» oppure «vista» e «data».")
    v = None if misura_aziendale else vista_per(contesto, vista)   # le viste della chat: ambito e sostituite
    if raggruppa:
        return _per_gruppo(contesto, {**spec, "tipo": Artifact.TABELLA, "raggruppa": raggruppa, "primi": primi}, v,
                           titolo, f"{predefinito}, per {raggruppa}")
    try:
        dati = motore.calcola_previsione(spec, richiesta.per(contesto), vista=v)
    except ErrorePrevisione as e:
        raise ErroreStrumento(str(e)) from e
    a = artifact._crea(contesto, Artifact.GRAFICO, titolo or predefinito, spec, dati)
    return {"artifact": a.pk, "titolo": a.titolo, "ultimi_periodi": dati["storico"][-6:],
            "previsione": [{"periodo": p, "basso_10": b, "mediana": m, "alto_90": a_} for p, b, m, a_ in dati["futuro"]],
            "totale_orizzonte": {**dati["totale"], "periodi": len(dati["futuro"])},
            "periodi_di_storia": len(dati["storico"]), "modello": dati["modello"], "affidabilita": dati["affidabilita"],
            "nota": "Numeri calcolati dal modello di previsione sulla storia del gestionale; il periodo in corso non è "
                    "nella storia perché incompleto. Riporta la mediana con l'intervallo 10-90 % e ricorda che è una "
                    "stima. Per il totale del periodo usa totale_orizzonte (somma delle mediane, con un intervallo "
                    "prudente più largo di quello reale): non sommare a mano. Il grafico è sotto la risposta. Di' "
                    "l'affidabilità (affidabilita.livello: alta, media o bassa) con il motivo principale."}


def _per_gruppo(contesto, spec, v, titolo, predefinito):
    """La previsione di ognuno dei primi gruppi: una tabella sotto la risposta, i numeri (con totali e affidabilità
    calcolati dal codice) ad Ada."""
    try:
        dati = motore.calcola_per_gruppo(spec, richiesta.per(contesto), vista=v)
    except ErrorePrevisione as e:
        raise ErroreStrumento(str(e)) from e
    a = artifact._crea(contesto, Artifact.TABELLA, titolo or predefinito, spec, motore.come_tabella(dati))
    nota = ("Numeri calcolati dal modello di previsione sulla storia del gestionale; il periodo in corso non è nella "
            "storia perché incompleto. La tabella è sotto la risposta: per ogni gruppo riporta la mediana con la fascia "
            "10-90 % (totale) e l'affidabilità (livello) con il motivo principale, ricordando che sono stime. Non "
            "sommare a mano: i totali sono già calcolati.")
    if dati["esclusi"]:
        nota += f" {dati['esclusi']} gruppi sono stati lasciati fuori perché con troppa poca storia."
    return {"artifact": a.pk, "titolo": a.titolo,
            "gruppi": [{"nome": g["nome"], "totale": g["totale"], "affidabilita": g["affidabilita"]}
                       for g in dati["gruppi"]],
            "modello": dati["modello"], "nota": nota}


registra(Strumento(
    "previsione", "Prevede i prossimi periodi di una misura del gestionale (es. fatturato o numero di ordini per mese) "
                  "con un modello di previsione locale: storia dai dati reali, previsione con mediana e fascia 10-90 %, "
                  "grafico sotto la risposta.",
    {"type": "object", "properties": {
        "vista": VISTA, "data": {"type": "string", "description": "campo data della serie, es. data"},
        "misura": {"type": "string", "description": "count (default) oppure sum:campo, es. sum:totale"},
        "per": {"type": "string", "enum": ["mese", "settimana", "giorno"], "description": "periodo (default mese)"},
        "orizzonte": {"type": "integer", "description": f"periodi da prevedere (1-{MAX_ORIZZONTE}, default 3)"},
        "filtri": FILTRI, "testo": TESTO, "titolo": {"type": "string"},
        "misura_aziendale": {"type": "string", "description": "una misura dell'elenco «Misure aziendali» (es. "
                                                              "fatturazione.fatturato) al posto di vista, data e misura"},
        "raggruppa": {"type": "string", "description": "campo della vista (o raggruppamento della misura aziendale) "
                                                       "per cui prevedere ogni gruppo, es. prodotto o cliente: "
                                                       "tabella con una previsione per gruppo"},
        "primi": {"type": "integer", "description": "con raggruppa: quanti gruppi (i più grandi, 1-50, default 10)"}},
     "required": []}, previsione, disponibile=servizio.attivo, ovunque=True))     # ovunque: anche nelle chat di un'app
