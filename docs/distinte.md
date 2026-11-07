# Distinte di pagamento: bonifici, SDD e RiBa

Il modulo **Distinte di pagamento** prepara i file da caricare nell'home banking partendo dalle scadenze aperte:

| Distinta | Da quali scadenze | File |
|---|---|---|
| Bonifici SEPA ai fornitori | fatture ricevute registrate, non pagate | pain.001 (ISO 20022) |
| Addebiti SDD ai clienti | fatture emesse, clienti con un mandato attivo | pain.008 (ISO 20022) |
| Ricevute bancarie (RiBa) | fatture emesse con modalità RiBa (MP12) | tracciato CBI a 120 caratteri |

I file SEPA si controllano con lo schema XSD ufficiale prima di uscire: un file che la banca scarterebbe per la
struttura non si scarica.

## Prima di cominciare

1. **Banca → Conti**: il conto dell'azienda (IBAN, e il BIC se c'è). Nella scheda del conto, riquadro *Distinte di
   pagamento*:
   - **codice SIA** (5 caratteri, lo dà la banca): serve per le RiBa;
   - **identificativo del creditore SEPA** (es. `IT66ZZZ0123456789`, lo dà la banca): serve per gli SDD;
   - **versione dei file SEPA**: la 2019 va bene quasi ovunque; la 2009 per le banche che non l'accettano ancora.
2. **Coordinate bancarie** sulla scheda del contatto:
   - per i **fornitori**, se la fattura elettronica non porta l'IBAN;
   - per i **clienti con RiBa**: l'IBAN italiano della loro banca, da cui si ricavano ABI e CAB.
3. **Mandati SDD**: uno per cliente, con riferimento univoco, IBAN, data di firma e schema (CORE o B2B). Senza un
   mandato attivo il cliente non compare negli addebiti.

## Fare una distinta

1. **Nuova distinta**: scegli tipo, conto e data (esecuzione dei bonifici o addebito SDD; per le RiBa la data di
   presentazione, perché ogni ricevuta ha la sua scadenza).
2. Compaiono le scadenze aperte. Sono spuntate quelle con la modalità di pagamento giusta. Quelle che non si possono
   mettere (manca l'IBAN, manca il mandato…) dicono perché.
3. **Crea la distinta**, poi **Scarica il file per la banca** e caricalo nell'home banking.
4. **Segna come presentata**.

Una scadenza in una distinta non compare in un'altra. Torna disponibile se la voce viene respinta.

## Esiti

Quando la banca dà l'esito, sulla distinta:

- **Incassata** (SDD, RiBa): registra l'incasso sulla fattura, metodo SDD o RiBa, alla data della scadenza o a quella
  scelta;
- **Eseguito** (bonifici): segna pagata la scadenza del fornitore;
- **Insoluta / Respinto**, con il motivo: annulla l'incasso o il pagamento e riapre la scadenza;
- **Tutte incassate / Tutti eseguiti**: per la distinta intera.

Quando tutte le voci hanno un esito la distinta si chiude.

Per l'SDD la data di addebito deve essere almeno il giorno lavorativo dopo la presentazione. Le banche spesso chiedono
qualche giorno in più: controlla le loro scadenze.

## Non ancora gestito

- La lettura automatica dei file di esito della banca (esiti RiBa, pain.002): per ora gli esiti si segnano a mano.
- Il formato XML CBI (`CBIPaymentRequest`) che alcuni corporate banking italiani chiedono al posto dell'ISO 20022.
