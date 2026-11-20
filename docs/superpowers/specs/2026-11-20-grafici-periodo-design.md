# Periodo sul grafico

Data: 2026-11-20 · Dimensione: media (design breve, approvato dall'utente in chat)

## Perché

Secondo pezzo dei grafici interattivi per le demo di Ada: cambiare il periodo di un grafico con un tocco, senza
riscrivere la domanda ad Ada. Il primo pezzo (clic sul punto → i record) è già sull'istanza.

## Cosa

- Sopra il grafico i pulsanti **Mese · Trimestre · Anno · Anno scorso** (periodi relativi di `core.misure.PERIODI`),
  con quello attuale evidenziato. Al tocco il server ricalcola e il grafico si ridisegna lì dov'è, come con ↻; i link
  ai record seguono il nuovo periodo.
- **Confronta**: una seconda serie, più chiara, con lo stesso periodo dell'anno prima, allineata per chiave (gennaio con
  gennaio, cliente con cliente). Non sulle torte.
- Dove: grafici della chat (sotto la risposta) e card dei grafici salvati in Analisi.

## Su quali grafici

- Misure aziendali con un periodo (`periodo_su`, non calcolate).
- Grafici su una vista raggruppati per data (`per` = `campo:mese`…): il periodo filtra su quel campo; c'è anche
  **Sempre**, per togliere il periodo.
- Gli altri no: senza una data certa un filtro sul periodo potrebbe essere sbagliato.

## Decisioni

- Pulsanti solo per il proprietario (come ↻ e il cambio di tipo); la scelta si salva nella specifica del grafico.
- In chat la scelta aggiorna il grafico, non il testo della risposta.
- Il periodo resta relativo («anno» è sempre l'anno in corso).

## Fuori

Filtri per cliente, agente o stato; periodo libero dal/al; pulsanti nella pagina «Apri in grande» di Analisi e nella
pagina del grafico della chat (si vede il periodo scelto); torte con confronto.
