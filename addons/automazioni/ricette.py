"""Regole pronte: un clic le crea spente, con i loro modelli di email, da guardare e accendere."""
import uuid

from core.models import ModelloEmail, TipoAttivita

from . import catalogo
from .models import Regola

RICETTE = [
    {"codice": "preavviso", "nome": "Promemoria prima della scadenza", "descrizione": "Tre giorni prima, ricorda gentilmente al cliente la scadenza.",
     "icona": "inbox", "evento": "fattura.in_scadenza", "giorni": 3, "azioni": [{"tipo": "email", "a": "cliente", "modello": 0}],
     "modelli": [{"nome": "Promemoria di scadenza", "oggetto": "Promemoria: {{ documento }} in scadenza il {{ scadenza }}",
                  "corpo": "Gentile {{ cliente }},\nle ricordiamo che il {{ scadenza }} scade il pagamento di {{ importo_scadenza }} relativo a {{ documento }}.\n\nSe ha già provveduto, non consideri questo messaggio.\n\nCordiali saluti\n{{ azienda }}"}]},
    {"codice": "sollecito", "nome": "Sollecito gentile dopo 7 giorni", "descrizione": "Una settimana dopo la scadenza non pagata, il primo sollecito al cliente.",
     "icona": "alert-triangle", "evento": "fattura.scaduta", "giorni": 7, "azioni": [{"tipo": "email", "a": "cliente", "modello": 0}],
     "modelli": [{"nome": "Sollecito gentile", "oggetto": "Sollecito di pagamento: {{ documento }}",
                  "corpo": "Gentile {{ cliente }},\ndai nostri controlli non risulta ancora pagato l'importo di {{ importo_scadenza }}, scaduto il {{ scadenza }}, relativo a {{ documento }}.\n\nLe chiediamo di verificare e, se ha già provveduto, di non considerare questo messaggio.\n\nCordiali saluti\n{{ azienda }}"}]},
    {"codice": "sollecito_deciso", "nome": "Secondo sollecito dopo 30 giorni", "descrizione": "Dopo un mese manda un sollecito più deciso e dà a te l'attività di chiamare il cliente.",
     "icona": "alert-triangle", "evento": "fattura.scaduta", "giorni": 30,
     "azioni": [{"tipo": "email", "a": "cliente", "modello": 0},
                {"tipo": "attivita", "a": "utente", "utente": "io", "testo": "Chiamare {{ cliente }} per {{ documento }}", "giorni": 2}],
     "modelli": [{"nome": "Sollecito deciso", "oggetto": "Secondo sollecito di pagamento: {{ documento }}",
                  "corpo": "Gentile {{ cliente }},\nnonostante il precedente sollecito, l'importo di {{ importo_scadenza }}, scaduto il {{ scadenza }}, risulta ancora da pagare ({{ giorni_ritardo }} giorni di ritardo).\n\nLa preghiamo di provvedere al più presto o di contattarci per concordare una soluzione.\n\nCordiali saluti\n{{ azienda }}"}]},
    {"codice": "grazie", "nome": "Ringraziamento per il pagamento", "descrizione": "Quando la fattura è incassata tutta, ringrazia il cliente.",
     "icona": "check", "evento": "fattura.incassata", "azioni": [{"tipo": "email", "a": "cliente", "modello": 0}],
     "modelli": [{"nome": "Grazie per il pagamento", "oggetto": "Abbiamo ricevuto il pagamento di {{ documento }}",
                  "corpo": "Gentile {{ cliente }},\nabbiamo ricevuto il pagamento di {{ documento }}. Grazie!\n\nCordiali saluti\n{{ azienda }}"}]},
    {"codice": "sla", "nome": "Ticket oltre il tempo di risposta", "descrizione": "Dà un'attività urgente a chi ha il ticket quando supera lo SLA.",
     "icona": "zap", "evento": "ticket.sla", "azioni": [{"tipo": "attivita", "a": "assegnatario", "testo": "Rispondere subito: {{ ticket }}", "giorni": 0}]},
    {"codice": "urgente", "nome": "Avviso sui ticket urgenti", "descrizione": "Appena si apre un ticket urgente ti arriva un'email.",
     "icona": "zap", "evento": "ticket.creato", "condizioni": [{"campo": "priorita", "op": "uguale", "valore": "urgente"}],
     "azioni": [{"tipo": "email", "a": "utente", "utente": "io", "modello": 0}],
     "modelli": [{"nome": "Ticket urgente", "oggetto": "Ticket urgente: {{ ticket }}",
                  "corpo": "È stato aperto un ticket urgente.\n\n{{ ticket }}\nCliente: {{ cliente }}\n\n{{ link_interno }}"}]},
    {"codice": "richiamo", "nome": "Richiamare dopo il preventivo", "descrizione": "Se il preventivo resta senza risposta per 7 giorni, il commerciale riceve l'attività di richiamare.",
     "icona": "users", "evento": "ordine.senza_risposta", "giorni": 7,
     "azioni": [{"tipo": "attivita", "a": "commerciale", "testo": "Richiamare {{ cliente }} per il {{ documento }}", "giorni": 1}]},
    {"codice": "preventivo", "nome": "Preventivo in scadenza", "descrizione": "Tre giorni prima che scada, ricorda il preventivo al cliente.",
     "icona": "inbox", "evento": "ordine.in_scadenza", "giorni": 3, "azioni": [{"tipo": "email", "a": "cliente", "modello": 0}],
     "modelli": [{"nome": "Preventivo in scadenza", "oggetto": "Il preventivo {{ numero }} scade il {{ valido_fino_al }}",
                  "corpo": "Gentile {{ cliente }},\nle ricordiamo che il preventivo {{ numero }} di {{ totale }} è valido fino al {{ valido_fino_al }}.\n\nSe ha domande siamo a disposizione.\n\nCordiali saluti\n{{ azienda }}"}]},
    {"codice": "lead", "nome": "Nuove opportunità a te", "descrizione": "Le opportunità che arrivano senza commerciale vengono assegnate a te.",
     "icona": "user", "evento": "opportunita.creata", "condizioni": [{"campo": "senza_commerciale", "op": "si", "valore": ""}],
     "azioni": [{"tipo": "assegna", "utente": "io"}]},
    {"codice": "rinnovo", "nome": "Rinnovo dei contratti", "descrizione": "Un mese prima della fine del contratto ricevi l'attività di proporre il rinnovo.",
     "icona": "shield", "evento": "contratto.in_scadenza", "giorni": 30,
     "azioni": [{"tipo": "attivita", "a": "utente", "utente": "io", "testo": "Proporre il rinnovo di {{ contratto }} a {{ cliente }}", "giorni": 3}]},
    {"codice": "ritardo", "nome": "Attività in ritardo", "descrizione": "Dopo un giorno di ritardo manda un promemoria a chi ha l'attività.",
     "icona": "check", "evento": "attivita.scaduta", "giorni": 1, "azioni": [{"tipo": "email", "a": "assegnatario", "modello": 0}],
     "modelli": [{"nome": "Attività in ritardo", "oggetto": "Attività in ritardo: {{ attivita }}",
                  "corpo": "L'attività «{{ attivita }}» doveva essere fatta entro il {{ scadenza }}.\n\n{{ link_interno }}"}]},
]


def disponibili():
    return [r for r in RICETTE if catalogo.evento(r["evento"])]


def per_codice(codice):
    return next((r for r in disponibili() if r["codice"] == codice), None)


def crea(ricetta, azienda, utente):
    """La regola, spenta, con i modelli di email che le servono."""
    evento = catalogo.evento(ricetta["evento"])
    codici = []
    for m in ricetta.get("modelli", []):
        codice = f"personale.{uuid.uuid4().hex[:12]}"
        ModelloEmail.objects.create(azienda=azienda, codice=codice, nome=m["nome"], dominio=evento.dominio, oggetto=m["oggetto"],
                                    corpo=m["corpo"], aggiornato_da=utente)
        codici.append(codice)
    tipo = TipoAttivita.objects.first()
    azioni = []
    for a in ricetta["azioni"]:
        azione = dict(a)
        if "modello" in azione:
            azione["modello"] = codici[azione["modello"]]
        if azione.get("utente") == "io":
            azione["utente"] = utente.pk
        if azione["tipo"] == "attivita" and tipo:
            azione["tipo_attivita"] = tipo.pk
        azioni.append(azione)
    return Regola.objects.create(azienda=azienda, nome=ricetta["nome"], evento=ricetta["evento"], giorni=ricetta.get("giorni", 0),
                                 condizioni=ricetta.get("condizioni", []), azioni=azioni, creata_da=utente)
