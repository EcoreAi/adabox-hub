# Liquidazione IVA e LIPE

Il modulo **IVA** calcola la liquidazione periodica senza contabilità, dai due registri:

- **vendite**: le fatture emesse del periodo, note di credito in negativo;
- **acquisti**: le fatture ricevute *registrate* nel periodo (conta la data di registrazione).

La dichiarazione annuale, l'F24 e la contabilità restano allo studio. Qui si preparano i numeri, si chiude il periodo e
si genera il file della comunicazione LIPE.

## Impostazioni (IVA → Impostazioni)

| Voce | A cosa serve |
|---|---|
| Liquidazione IVA | mensile o trimestrale, per azienda |
| Codice fiscale di chi firma la LIPE | il legale rappresentante: obbligatorio per le società |
| Codice carica di chi firma | 1 = rappresentante legale |
| Codice fiscale dell'intermediario | lo studio che trasmette il file, se non lo invia l'azienda |
| Versamento minimo dell'IVA | 100 € dal 2024: sotto, il debito passa al periodo dopo |

## Che cosa entra nel calcolo

| Caso | Come si tratta |
|---|---|
| Scissione dei pagamenti (split payment) | l'IVA la versa il cliente: non entra nel debito, si vede a parte |
| Esigibilità differita | entra quando si incassa, in proporzione all'incasso, o dopo un anno dalla fattura |
| Autofatture d'integrazione (TD16-TD20, TD28) | l'IVA è a debito e a credito insieme |
| Fatture ricevute in inversione contabile (N6) | non entrano nel totale degli acquisti: conta l'autofattura che le integra |
| Escluse e non soggette (N1, N2) | fuori dai totali delle operazioni |
| Detraibilità | sulla scheda della fattura ricevuta, riquadro «IVA detraibile» (auto 40%, telefoni 50%…); di base 100% |
| Trimestrali | 1% di interessi sul dovuto dei primi tre trimestri; il quarto si versa con la dichiarazione annuale |
| Credito | passa al periodo dopo nello stesso anno; quello dell'anno prima si indica a mano |

Le voci che non stanno nei registri si scrivono nella pagina del periodo: credito dell'anno prima usato, crediti
d'imposta, versamenti auto UE, acconto di dicembre (almeno 103,29 €, con il metodo).

Non sono gestiti il pro-rata di detraibilità e la liquidazione IVA di gruppo.

## Chiudere un periodo

**Chiudi il periodo** congela i numeri: il periodo dopo usa il suo credito o debito e la LIPE li prende così, anche se
poi si registra una fattura in ritardo. Se dopo la chiusura i registri cambiano, la pagina lo segnala: si riapre e si
richiude. Si chiude in ordine (gennaio prima di febbraio) e si riapre all'indietro. Dopo il versamento si segna la data.

Nella pagina del periodo ci sono anche la scadenza e il codice tributo dell'F24 e, a fine trimestre, l'imposta di bollo
delle fatture elettroniche (codici 2521-2524).

## Comunicazione LIPE

**IVA → Comunicazione LIPE** genera il file XML (fornitura IVP18) del trimestre: tre moduli per chi liquida ogni mese,
uno per i trimestrali. Prima di generarlo controlla partita IVA, codici fiscali, soglia del debito riportato, acconto e
avvisa se una liquidazione non è chiusa.

Il file segue le specifiche tecniche dell'Agenzia delle Entrate (aggiornamento 2024). Prima dell'invio va passato nel
**software di controllo** gratuito dell'Agenzia, oppure lo controlla lo studio che lo trasmette.

Scadenze: 31 maggio, 30 settembre, 30 novembre e fine febbraio (il quarto trimestre si può mettere nella dichiarazione
annuale).

Il CSV delle liquidazioni entra anche nel pacchetto per il commercialista.
