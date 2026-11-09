# adabox-hub: analisi delle funzioni mancanti rispetto ai principali ERP

Confronto con la checklist di `docs/features-gap` (Odoo, ERPNext, NetSuite, Business Central), aggiornato al 2026-11-04. L'elenco dei risultati è nella sezione B, le lacune in ordine di priorità nella C.

## In sintesi

- **Su 219 voci, 31 sono complete, 95 parziali, 52 mancanti e 41 escluse dal perimetro.** Solo il 29% delle voci Core nel perimetro è completo: adabox-hub copre molto in superficie, ma spesso senza una parte attesa dai clienti.
- **Punti forti:** assistente AI, agenti e MCP, conversazioni, documenti, fatturazione elettronica, progetti, ticket, capacità.
- **Punti deboli:** funzioni trasversali del kernel (multi-valuta, multilingua, approvazioni generiche, storico su tutti i record, filtri salvati, pivot), portale clienti e pagamenti online, magazzino avanzato (costi, lotti, ubicazioni), timbratura.
- **Falla corretta:** chi non aveva aziende attive vedeva i record di tutte le aziende, e alcune pagine aprivano record di altre aziende. Ora non più (sezione D, punto 1).
- **Acquisti è stata l'app scelta per l'intervento:** passa da 0 a 8 voci complete su 14 (sezione E).
- **Fatti il 2026-11-05:** scadenziario a fasce, fido dei clienti e pacchetto per il commercialista (FIN-06, FIN-07, FIN-01).
- **Fatti il 2026-11-05 anche:** ricerche salvate, ricerca in tutte le app, Pivot, registro delle modifiche, scadenza e limiti dei token API (RPT-03, RPT-02, PLT-04, parte di PLT-17 e PLT-14).
- **Fatto il 2026-11-08:** chatter completo, con messaggi fissati, menzioni senza Discuss e invio a indirizzi esterni scelti al momento (PLT-10), e tolleranza alla perdita di connessione: avviso offline, «Riprova» sugli errori, bozze dei form (PLT-19), posizioni e organigramma (HR-01), dashboard per ruolo e pagine di Analisi condivise con ruoli e gruppi (RPT-01), riaddebito delle spese ai clienti e rimborso abbinato alla banca (FIN-24), modulo web-to-lead per il sito (CRM-19), nuovo modulo Reception per i visitatori (HR-14), accesso al portale con Google e Microsoft (COM-10), «Scrivi con Ada» in ogni campo e riassunto dei record (AI-08), riconciliazione bancaria che impara dagli abbinamenti (AI-03), API su tutte le viste con schemi e limiti, SDK Python e istanza di prova per chi integra (PLT-14, INT-08), modulo Privacy per il GDPR (LOC-07), consolidato su più aziende in Analisi e in Ada (gran parte di PLT-01), regole sulle righe e permessi per campo per ruolo (PLT-03), modelli di stampa per azienda e documento (PLT-09), approvazioni generiche sui documenti (PLT-07), report pianificati per email (RPT-06), app installabile con notifiche push (PLT-16), timbratura e presenze (HR-03).
- **Integrazioni, iniziate il 2026-11-05 nel modulo Connettori:** webhook firmati in uscita, identificativi esterni sui record, bottoni via API, chat collegata al contatto e primo connettore HubSpot sui contatti delle persone, provato solo contro un sistema simulato. Mancano aziende e opportunità e gli altri sistemi. Zucchetti e TeamSystem Enterprise/Lynfa non hanno documentazione pubblica trovata: servono partner o contatto commerciale.

## Da dove partire

| Priorità | Che cosa | Voci | Perché |
|---|---|---|---|
| 1 | Integrazione con CRM e gestionali esterni: base generica, chat collegata al cliente, poi connettori (Salesforce, HubSpot, Zoho, Zucchetti, TeamSystem) | PLT-14, INT-06, INT-08, INT-05 | Decisione del 2026-11-05: adabox deve poter entrare accanto al software che il cliente ha già |
| 3 | Portale clienti e pagamenti online | COM-01, CRM-09, COM-02, FIN-25 | Le altre sezioni lo danno per scontato |
| 4 | Banca e fisco italiani: file SEPA e RiBa, liquidazione IVA e LIPE | FIN-32, FIN-16, LOC-02 | Servono in Italia e non richiedono un mastro |
| 5 | Magazzino: costi, lotti e seriali, ubicazioni | INV-09, INV-03, INV-04 | Sbloccano resi, garanzie, assistenza sul campo e la valorizzazione |

## Decisioni sul perimetro

Esclusioni confermate il 2026-11-05: queste voci restano N/A e non entrano nella roadmap.

| Tema | Voci | Motivo |
|---|---|---|
| Contabilità generale | 12 voci FIN, LOC-06, RPT-04 | Resta al commercialista (decisione del 2026-11-03); al massimo un'esportazione per lo studio |
| Produzione | 16 voci MFG | Fuori dal prodotto |
| POS, eCommerce, CMS | COM-03..06, IND-05 | Fuori dal prodotto |
| Multilingua | PLT-15 | Il prodotto resta in italiano. È una voce Core nei concorrenti: pesa nei confronti con clienti esteri |
| Paghe | HR-09, LOC-04 | Restano al consulente del lavoro, a cui arriva l'esportazione delle presenze (HR-03) |
| Selezione e valutazioni | HR-06, HR-15, HR-07 | Fuori dal prodotto |

La timbratura (HR-03) resta invece nel perimetro, con l'esportazione mensile per il consulente. Più avanti si può aggiungere l'importazione dei cedolini in PDF, da mostrare ai dipendenti.

## Come è stata fatta

Sei ricerche parallele hanno letto modelli, logica, viste e test di ogni area applicando le regole della checklist. Ho poi verificato a campione alcune assenze cercandole nel codice (pivot, gateway di pagamento, lotti, traduzioni) e controllato che le voci sovrapposte tra sezioni dessero lo stesso giudizio; una coppia è stata allineata (AI-03 con FIN-37). La lettura è statica: a parte acquisti e l'isolamento tra aziende, le funzioni non sono state provate in esecuzione, quindi uno stato può essere impreciso. Gli effort sono stime.

## A. Riepilogo per sezione

Copertura Core = voci Core HAVE / voci Core non N/A. Tra parentesi la stessa quota contando anche le PARTIAL.

| Sezione | Voci | HAVE | PARTIAL | MISSING | N/A | Copertura Core % |
|---|---:|---:|---:|---:|---:|---:|
| Piattaforma e architettura (PLT) | 26 | 4 | 20 | 1 | 1 | 24% (94%) |
| Finanza e contabilità (FIN) | 38 | 5 | 13 | 8 | 12 | 29% (82%) |
| Vendite, CRM e marketing (CRM) | 20 | 2 | 14 | 4 | 0 | 22% (100%) |
| Acquisti (PUR) | 14 | 8 | 2 | 4 | 0 | 100% (100%) |
| Magazzino (INV) | 21 | 0 | 11 | 10 | 0 | 0% (69%) |
| Produzione (MFG) | 18 | 0 | 0 | 2 | 16 | – |
| Persone e paghe (HR) | 16 | 2 | 4 | 6 | 4 | 33% (100%) |
| Progetti, servizio e assistenza (PRJ) | 13 | 3 | 7 | 3 | 0 | 33% (100%) |
| Commercio e front office (COM) | 11 | 0 | 3 | 4 | 4 | 0% (50%) |
| Report e analisi (RPT) | 11 | 4 | 4 | 2 | 1 | 60% (100%) |
| AI e automazione (AI) | 9 | 3 | 4 | 2 | 0 | – |
| Integrazioni ed estensibilità (INT) | 9 | 0 | 7 | 2 | 0 | 0% (100%) |
| Localizzazione e conformità (LOC) | 8 | 0 | 5 | 1 | 2 | 0% (67%) |
| Pacchetti di settore (IND) | 5 | 0 | 1 | 3 | 1 | – |
| **Totale** | 219 | 31 | 95 | 52 | 41 | 29% (89%) |

## Cosa sviluppare per ogni applicazione

Ogni voce aperta è assegnata all'app dove andrebbe costruita. Ordine dentro ogni app: Core, poi Adv, poi Edge; a parità, prima quelle piccole. Effort: S meno di 1 settimana, M 1–4 settimane, L oltre 1 mese, per uno sviluppatore. Le voci chiuse in questo lavoro sono nella sezione E, non qui.

### core

11 voci aperte: 6 Core, 5 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PLT-01 | Core | PARTIAL | S | Restano il livello filiale sotto l'azienda e le operazioni tra aziende (es. vendita interna); il consolidato di interrogazioni, grafici, KPI e Ada è fatto (2026-11-08). |
| PLT-05 | Core | PARTIAL | M | Pagina front per le sequenze, modello Esercizio o Periodo per azienda con data di blocco controllata da un servizio del kernel in save, azioni e API di fatturazione, sdi, banca e magazzino. |
| PLT-13 | Core | PARTIAL | M | Import a testata e righe sulle viste con inlines, risoluzione della variante per riga quando INV-01 esiste, import_key sulle anagrafiche principali. |
| PLT-17 | Core | PARTIAL | M | Attributo Gantt nella ModelView: ricerca trasversale, ricerche salvate e pivot fatte il 2026-11-05. |
| CRM-08 | Core | PARTIAL | L | Caselle per utente con OAuth Gmail e Microsoft Graph oltre a IMAP, abbinamento automatico per mittente a contatto e opportunità aperta, invio al cliente dal chatter del record. |
| PLT-02 | Core | MISSING | L | Modello Valuta e Cambio con aggiornamento da BCE, valuta e cambio su documenti, listini, scadenze e incassi, totali in valuta aziendale, Divisa in FatturaPA, report delle differenze di cambio. |
| CRM-16 | Adv | PARTIAL | M | Servizio di firma riusabile sui documenti: richiesta con OTP via email o SMS, PDF con pagina di attestazione e hash conservato, opzione verso provider qualificato; applicato a preventivi e contratti. |
| IND-03 | Adv | PARTIAL | M | Meccanismo di modelli di settore (moduli da attivare, ruoli, ricette di automazione, dati iniziali) e primo modello agenzia/consulenza; modulo agenda risorse per i saloni. |
| PLT-23 | Adv | PARTIAL | M | Accesso OIDC e SAML configurabile da UI con creazione utente e mappatura di gruppi su ruoli, backend LDAP facoltativo. |
| PLT-26 | Adv | PARTIAL | M | Comando clona in staging da backup, con anonimizzazione dichiarata per campo, blocco di email e canali esterni e banner di ambiente di prova. |
| LOC-08 | Adv | PARTIAL | L | Cifrare backup e file privati, documentare la cifratura del disco nel deploy, aggiungere un audit log immutabile e la raccolta dei controlli ISO 27001. |

### magazzino

15 voci aperte: 10 Core, 5 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INV-05 | Core | HAVE | M | Documento di trasferimento a doppio movimento, stato «pronto», evasione parziale con documento di residuo legato alla riga d'ordine e storno controllato dei documenti fatti. | **Fatto il 2026-11-09**: consegna «pronta» (anche dalla lettura dei codici), evasione parziale con residuo in un nuovo documento della stessa origine, storno di consegne e ricevimenti fatti con movimenti opposti allo stesso costo (bloccato se il DDT è in fattura o la merce non c'è più), annullo del ricevimento in bozza. I trasferimenti c'erano già da INV-04.
| INV-06 | Core | HAVE | M | Stampa e pagina di prelievo per consegna con percorso per ubicazione, quantità prelevata confermata e colli con contenuto, prima dell'emissione del DDT. | **Fatto il 2026-11-09**: pagina «Prelievo e colli» della consegna con il giro ordinato per ubicazione, ubicazione e lotti suggeriti, kit esplosi, prelevato confermato (il resto parte dopo o si toglie), collo di ogni riga che dà i colli del DDT; stampa della lista di prelievo e della distinta colli. L'impegno della merce sull'ordine resta quello del riordino (consegne aperte).
| INV-07 | Core | HAVE | M | Regole per magazzino e colonna del previsto nella pagina Giacenze, riusando acquisti.riordino. | **Fatto il 2026-11-09**: scorte per magazzino (punto e obiettivo) che il riordino valuta magazzino per magazzino, con il magazzino nella riga della richiesta; la pagina Giacenze mostra impegnato, in arrivo (anche gli ordini d'acquisto) e previsto, e chi è sotto scorta in quale magazzino.
| INV-08 | Core | HAVE | M | Documento di inventario con fotografia del teorico, inserimento o importazione del contato, approvazione che genera le rettifiche; pianificazione delle conte cicliche; esportazione del valore delle differenze per il commercialista. | **Fatto il 2026-11-09**: inventari per magazzino, ubicazione o categoria con fotografia del teorico (anche per lotto), conta alla cieca scritta, letta con il lettore o importata da CSV, approvazione con rettifiche sulla giacenza di adesso e al costo di magazzino, conta ciclica settimanale dei prodotti contati da più tempo, differenze valorizzate nel pacchetto per lo studio.
| INV-10 | Core | HAVE | M | Pagine di giacenza a data, prevista, anzianità per fasce e valore di magazzino, con esportazione. | **Fatto il 2026-11-09**: giacenze a una data passata e di oggi con impegnato, in arrivo e previsto, anzianità per fasce (giacenza attribuita agli ultimi carichi) con valore, tutte con CSV; il valore a una data c'era già da INV-09.
| INV-11 | Core | HAVE | M | Interfaccia mobile di lettura (lettore o fotocamera) che guida ricevimento, prelievo, conta e trasferimento, confermando le quantità sui documenti aperti. | **Fatto il 2026-11-09**: pagina «Lettura codici» per telefono o lettore (che scrive e preme Invio), con fotocamera dove il browser ha BarcodeDetector e la pagina è in https; ricevimenti e consegne in bozza (quantità lette sulle righe, prodotti in più aggiunti solo nel ricevimento, poi ricevi o spedisci) e spostamento di merce; il codice della confezione vale tutti i pezzi. Il conteggio d'inventario arriva con INV-08.
| INV-12 | Core | HAVE | M | Modello Reso da consegna o fattura con autorizzazione, motivo, rientro con carico o scarto e nota di credito parziale precompilata sulle righe rese. | **Fatto il 2026-11-09**: documento Reso (RES/anno) dal DDT o a mano, con motivo, autorizzazione o rifiuto, esito per riga (a magazzino o scarto), rientro con carico al costo di magazzino e nota di credito in bozza con le sole righe rese al prezzo della fattura trovata dal DDT o dall'ordine. Il rimborso resta quello della nota di credito.
| INV-03 | Core | HAVE | L | Modelli Lotto e Seriale con scadenza, obbligo di indicazione su ricevimenti e consegne per i prodotti tracciati, giacenza per lotto e report di tracciabilità a monte e a valle. | **Fatto il 2026-11-07**: lotti e seriali con scadenza, tracciamento per prodotto, obbligo su ricevimenti e consegne, uscite per scadenza (FEFO), seriali unici, tracciabilità verso fornitori e clienti nella scheda del lotto.
| INV-04 | Core | HAVE | L | Modello Ubicazione ad albero sotto Magazzino, ubicazione su movimenti e righe documento, giacenza per ubicazione, con migrazione verso un'ubicazione predefinita. | **Fatto il 2026-11-07**: ubicazioni ad albero per magazzino, su movimenti e righe, carichi nella predefinita e uscite da dove ce n'è di più, trasferimenti al costo invariato, merce per ubicazione. La merce di prima resta «senza ubicazione» finché non si sposta.
| INV-09 | Core | HAVE | L | Costo unitario su ogni movimento, strati di costo per FIFO e medio ponderato, standard opzionale, rivalutazione e valore di magazzino a una data; nessuna scrittura contabile, solo esportazione. | **Fatto il 2026-11-07**: costo e valore su ogni movimento, medio ponderato, FIFO o standard (per azienda e per prodotto), valore a una data ripercorrendo i movimenti, CSV dell'inventario anche nel pacchetto per lo studio. Rivalutazione solo cambiando il costo standard.
| INV-20 | Adv | PARTIAL | M | Lavoro periodico che calcola la domanda per articolo e aggiorna scorta di sicurezza e punto di riordino consigliati, con un'alternativa locale quando il servizio manca. |
| PUR-09 | Adv | MISSING | M | Documento di costi accessori legato a ricevimenti, ripartizione per valore, peso o quantità con aggiornamento degli strati di costo. |
| INV-14 | Adv | MISSING | L | Regole di stoccaggio per prodotto e categoria che suggeriscono l'ubicazione, regole di prelievo che ordinano lotti e ubicazioni nella lista di prelievo. |
| INV-15 | Adv | MISSING | L | Percorsi configurabili per magazzino con documenti concatenati, raggruppamento di più consegne in un'ondata di prelievo. |
| INV-19 | Adv | MISSING | L | Proprietario della giacenza su movimenti e ubicazioni, magazzini presso terzi per il conto deposito, passaggio diretto da ricevimento a consegna. |

### fatturazione

6 voci aperte: 5 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| COM-02 | Core | HAVE | M | Interfaccia gateway con almeno due fornitori (es. Stripe, PayPal o Nexi), link di pagamento su fatture e preventivi, webhook firmato che registra l'incasso via incassa_fattura. | **Fatto il 2026-11-09**: secondo fornitore reale PayPal (Orders v2, sandbox o produzione, webhook verificato da PayPal) accanto a Stripe e al simulato. Il link di pagamento vale per le fatture; un acconto sul preventivo accettato non c'è.
| FIN-12 | Core | HAVE | M | Credito cliente non allocato e riutilizzabile sulle scadenze. Registro dei pagamenti su ScadenzaPassiva, simmetrico a Incasso, con parziali e abbuoni. | **Fatto il 2026-11-09**: crediti dei clienti (acconti registrati a mano ed eccedenze di un pagamento) usati con «Usa il credito» sulle scadenze di un'altra fattura, che tornano disponibili se l'incasso si annulla; registro dei pagamenti ai fornitori con parziali e abbuoni, pagina per registrarli e annullarli, banca e distinte che pagano anche in parte, ritenute e IVA per cassa calcolate sui pagamenti. Manca il resto di un movimento bancario girato a credito del cliente.
| FIN-16 | Core | HAVE | M | Pagina di liquidazione IVA mensile o trimestrale dai due registri, con credito riportato e detraibilità, ed export dati per lo studio; il file ufficiale è LOC-02. | **Fatto il 2026-11-07** nel modulo `iva`: liquidazione mensile o trimestrale con split, differita, autofatture, detraibilità per fattura, riporti, soglia di 100 €, interessi dei trimestrali, chiusura che congela i numeri, bollo del trimestre e CSV nel pacchetto per lo studio.
| FIN-25 | Core | HAVE | M | Pagina pubblica con token per fattura, connettore a un provider di pagamento con webhook che registra l'Incasso, link nelle email di invio e sollecito. | Dal 2026-11-09 il link è anche nelle email di invio della fattura e nei promemoria e solleciti delle automazioni (campi paga_online e link_pagamento).
| LOC-02 | Core | HAVE | M | File XML LIPE trimestrale dalla liquidazione, validato con lo schema. Export delle ritenute per la CU allo studio. | **2026-11-07**: file LIPE IVP18 dalle liquidazioni, con i controlli bloccanti delle specifiche 2024; lo schema XSD ufficiale non è nel repository, il file va passato nel software di controllo dell'Agenzia. **Dal 2026-11-09** le ritenute d'acconto delle fatture ricevute (RT01 e RT02, causale, cassa) si leggono dall'XML; la pagina Ritenute le mostra per mese di pagamento con il codice tributo dell'F24 e per la CU dell'anno, con CSV anche nel pacchetto per lo studio.
| LOC-05 | Adv | PARTIAL | M | Dati Intrastat su prodotti e righe, modelli INTRA 1 e 2 dalle operazioni con nature N3.2 e autofatture TD18, export per lo studio. |

### banca

7 voci aperte: 4 Core, 2 Adv, 1 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| FIN-14 | Core | HAVE | S | Distinta di pagamento come lotto di scadenze, con totale, stato e file bancario. Stampa assegni solo se richiesta. | **2026-11-07**: la distinta del modulo `distinte` è il lotto, con totale, stato e file. Assegni non richiesti.
| FIN-10 | Core | HAVE | M | Connettore a un aggregatore PSD2 con consenso per conto, lettura periodica nel cron e movimenti passati dalla stessa deduplica. | **Fatto il 2026-11-09**: GoCardless Bank Account Data (consenso sul sito della banca, conto trovato per IBAN, movimenti e saldo ogni 6 ore con la stessa deduplica dei file) più un servizio simulato; avviso nel riepilogo quando il consenso scade. Provato solo contro un server finto: serve un account GoCardless per la prova vera, e GoCardless potrebbe non accettare nuovi clienti per questo servizio.
| FIN-11 | Core | HAVE | M | Regole configurabili per causale, controparte e importo che classificano i movimenti senza fattura e li rendono esportabili allo studio. | **Fatto il 2026-11-09**: regole dei movimenti (testi alternativi nella descrizione, controparte, IBAN, segno, fascia d'importo) che all'importazione classificano i movimenti senza fattura con categoria e conto per lo studio; classificazione a mano dalla riconciliazione che può creare la regola per i prossimi uguali; «Applica le regole»; movimenti classificati non abbinabili finché non si ripristinano; categoria e conto nel CSV per lo studio con il riepilogo per categoria.
| FIN-13 | Core | HAVE | M | Conto di tipo cassa senza IBAN, movimenti manuali, apertura e chiusura con quadratura, collegamento a incassi e rimborsi in contanti. | **Fatto il 2026-11-09**: modulo «Cassa» con casse senza IBAN, movimenti per causale, chiusura con apertura, atteso, contato e differenza registrata, blocco dei movimenti chiusi e annullamento dell'ultima chiusura; gli incassi di fattura in contanti entrano nella cassa predefinita, i rimborsi delle note spese si pagano dalla cassa.
| FIN-32 | Adv | HAVE | M | Distinte da scadenze aperte con pain.001 per i bonifici, pain.008 e mandati per gli SDD, RiBa in formato CBI; ritorno dell'esito sugli incassi. | **Fatto il 2026-11-07** nel modulo `distinte`: bonifici pain.001 e SDD pain.008 (ISO 2019 o 2009, validati con gli XSD), mandati SDD, RiBa CBI; esiti segnati a mano registrano o annullano incassi e pagamenti. Mancano la lettura automatica dei file di esito e la variante XML CBI.
| FIN-34 | Adv | MISSING | M | Registro dei finanziamenti con piano delle rate che genera scadenze da pagare. ESG solo su richiesta. |
| FIN-37 | Edge | MISSING | M | Punteggio aggiuntivo da abbinamenti confermati (controparte, IBAN, causale), con spiegazione nel motivo e conferma umana. |

### commesse

5 voci aperte: 4 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| FIN-19 | Core | HAVE | M | Budget economico per commessa e periodo, a voci, con consuntivo da ore, fatture passive e note spese imputate. | **Fatto il 2026-11-09** nel modulo «Analitica»: budget per voce (centro di costo o commessa) e periodo con righe per categoria (ricavi, costi esterni, note spese, costo delle ore), consuntivo dalle imputazioni e dalle ore del progetto collegato, percentuale e proiezione a fine periodo con avviso oltre il previsto.
| FIN-20 | Core | HAVE | M | Dimensioni analitiche configurabili (commessa, centro di costo) sulle righe di documento, con ripartizioni percentuali, modifica massiva e report per asse. | **Fatto il 2026-11-09**: modulo «Analitica» con assi configurabili (centro di costo, commessa…), voci collegabili a un progetto, imputazione delle righe di fatture emesse, fatture ricevute e note spese anche ripartite in percentuale, modelli di ripartizione, imputazione di massa con filtro «solo da imputare», report per asse con ricavi, costi e margine, non imputato e CSV, sezione «Analitica» su fatture, fatture ricevute e note spese. Ordini d'acquisto non imputabili (sono impegni, non costi).
| PRJ-02 | Core | HAVE | M | Tipo di fatturazione a milestone con percentuale o importo per tappa, fattura in bozza al completamento, acconti e controllo del residuo a corpo. | **Fatto il 2026-11-09**: fatturazione a tappe (milestone o SAL) con percentuale o importo per tappa, «Completata: fattura» che crea la fattura in bozza una volta sola e controlla che le tappe non superino il valore; a corpo, acconti con il controllo del residuo e saldo finale.
| PRJ-03 | Core | HAVE | M | Budget economico per voce, costi da spese, acquisti e magazzino collegati al progetto, confronto preventivo e consuntivo con proiezione a finire e vista portafoglio. | **Fatto il 2026-11-09**: la redditività conta anche fatture ricevute e note spese imputate (modulo Analitica) alle voci collegate al progetto; budget economico per voce e periodo con confronto e proiezione a finire; nuova vista «Portafoglio» di tutti i progetti con ricavi, costi, margine e budget. I materiali scaricati dal magazzino non si legano ancora al progetto.
| PRJ-12 | Adv | PARTIAL | L | Report di utilizzo per persona e reparto; progetto e flag riaddebitabile su RigaSpesa con riga in fattura; ricavi maturati per avanzamento, come esportazione per il commercialista. |

### prodotti

5 voci aperte: 4 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| CRM-05 | Core | HAVE | M | Listino predefinito sul contatto, date di validità sulle voci, regole di sconto per cliente, categoria e quantità in prezzi.py, valuta del listino quando esiste la multivaluta. | **Fatto il 2026-11-09**: listino e sconto generale del cliente dalla sua scheda (gli ordini nuovi nascono con il suo listino), voci di listino con date di validità, regole di sconto per cliente, prodotto, categoria, quantità e periodo con la più precisa che vince, listini IVA inclusa (FIN-15). La valuta del listino aspetta la multivaluta.
| INV-02 | Core | HAVE | M | Categorie e fattori di conversione, UM di acquisto e di vendita sul prodotto, UM sulle righe con conversione alla UM base nei movimenti. | **Fatto il 2026-11-09**: unità con categoria e fattore (nuove dz, g, t, ml, m³, cm, mm, km, m², min), unità di vendita e di acquisto sul prodotto, unità su righe di ordini di vendita, ordini d'acquisto e fatture con quantità base calcolata e prezzo di listino riportato all'unità; consegne, ricevimenti e movimenti restano nell'unità del prodotto (convertiti dall'ordine), così giacenze, riordino, riscontro e contratti contano nella stessa unità; l'XML della fattura porta l'unità della riga.
| INV-13 | Core | HAVE | M | Confezioni per prodotto (pezzi per scatola o pallet) e kit con componenti, esplosi in consegna con scarico dei componenti e disponibilità calcolata. | **Fatto il 2026-11-09**: confezioni per prodotto (pezzi, codice a barre, peso) che danno colli e peso suggeriti sul DDT; kit con componenti che in consegna escono come componenti, con controllo della disponibilità e kit disponibili nella scheda. Un kit non ha giacenza propria: non si riceve.
| INV-01 | Core | PARTIAL | L | Modello attributi e varianti con generazione degli articoli, più barcode per articolo, tabella alternativi e codici per cliente, adeguando le righe documento. |
| CRM-18 | Adv | MISSING | L | Attributi e valori con regole di compatibilità e sovrapprezzi, configuratore in riga di preventivo che genera descrizione e prezzo, approvazione degli sconti oltre soglia. |

### personale

2 voci aperte: 2 Core, 0 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| HR-02 | Core | HAVE | M | Modello Contratto con validità, CCNL e livello, retribuzione e voci, storico per dipendente, avvisi di scadenza; spostare ore e ferie annue sul contratto in vigore. | **Fatto il 2026-11-09**: contratti di lavoro per dipendente (tipo, CCNL, livello, mansione, periodo senza sovrapposizioni, orario, ferie e permessi annui, retribuzione con mensilità e voci retributive), storico nella scheda, quello in vigore aggiorna orario, ferie e permessi su cui contano saldi e presenze (anche con il giro del mattino quando ne inizia uno), avviso nel riepilogo dei contratti in scadenza senza rinnovo; dati riservati e senza API.
| HR-08 | Core | PARTIAL | M | Pagina Il mio profilo che riunisce assenze, spese, ore, contratto, cedolini e documenti HR riservati, con richiesta di modifica dei dati anagrafici. |

### vendite

3 voci aperte: 2 Core, 0 Adv, 1 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| CRM-03 | Core | HAVE | S | FK opzionale da OrdineVendita a Opportunita, pulsante Crea preventivo sull'opportunità, sezione documenti collegati e opportunità vinta alla conferma dell'ordine; fatturazione parziale per consegnato da valutare a parte. | **Fatto il 2026-11-07**: «Crea preventivo» sull'opportunità, preventivi e ordini collegati sulle due schede, opportunità vinta alla conferma dell'ordine. La fatturazione parziale per consegna c'è già con le fatture differite dai DDT.
| CRM-04 | Core | HAVE | M | Modello ModelloPreventivo con righe e testi precompilati; righe marcate opzionali, escluse dal totale finché il cliente non le sceglie dalla pagina online, con impronta ricalcolata sulla scelta. | **Fatto il 2026-11-09**: modelli di preventivo con righe (anche opzionali), testo e giorni di validità da applicare a una bozza; righe opzionali escluse dal totale, scelte dal cliente con una spunta sulla pagina online (totale che si aggiorna, impronta che le conta), tolte alla conferma se non scelte; la validità c'era già.
| CRM-20 | Edge | PARTIAL | M | Gestore delle email dedicate che classifica la richiesta, abbina mittente e prodotti, estrae le righe anche dal PDF e prepara un preventivo in bozza da approvare, con i dubbi segnalati al commerciale. |

### fiscale

2 voci aperte: 2 Core, 0 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| FIN-15 | Core | HAVE | M | Posizioni fiscali su contatto e paese che mappano le aliquote in automatico, prezzi IVA inclusa, dichiarazioni d'intento con plafond, lettura delle ritenute passive. | **Fatto il 2026-11-09**: posizioni fiscali con regole per beni e servizi, due automatiche (clienti UE con partita IVA: N3.2 e N2.1; fuori UE: N3.1 e N2.1) e altre da assegnare al cliente dalla sua scheda; dichiarazioni d'intento con plafond che portano le righe in N3.5, si legano alla fattura all'emissione (bloccata oltre il plafond) e mettono il protocollo nell'XML; listini IVA inclusa scorporati sulle righe; ritenute passive lette da LOC-02. Gruppi di imposte non fatti.
| LOC-01 | Core | PARTIAL | L | Separare le regole italiane in un pacchetto caricabile per paese (aliquote, tipi documento, formato elettronico). Da fare solo se si vende all'estero. |

### crm

3 voci aperte: 1 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| CRM-07 | Core | HAVE | M | Modelli TeamVendita e ObiettivoVendita per persona, team e periodo, riassegnazione per team; report consuntivo su obiettivo, tasso di vittoria, durata media e motivi di perdita. | **Fatto il 2026-11-09**: team di vendita con responsabile e membri (le opportunità nuove prendono il team del commerciale), obiettivi per persona o team e periodo, azione «Riassegna nel team» a chi ha meno opportunità aperte, pagina «Obiettivi e risultati» con obiettivo e raggiunto, vinte e perse, tasso di vittoria, durata media, pipeline ponderata e motivi di perdita.
| CRM-14 | Adv | MISSING | M | Punteggio salvato sull'opportunità con ricalcolo periodico nel worker da storico vinte/perse, attività e dati del contatto, spiegazione dei fattori e ordinamento in kanban. |
| CRM-15 | Adv | PARTIAL | M | Piani provvigionali per venditore e prodotto maturati su ordine o incasso con estratto; quote legate agli obiettivi; vista previsione per periodo da pipeline ponderata con rettifica manuale. |

### grafici

2 voci aperte: 0 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| FIN-29 | Adv | PARTIAL | L | Modulo di pianificazione con versioni di budget e forecast per dimensione, driver semplici e confronto con il consuntivo. |
| PLT-25 | Adv | PARTIAL | L | Foglio integrato con formule che leggono da interroga.py con i permessi dell'utente, oppure connettore live per Excel come OData. |

### sdi

3 voci aperte: 1 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| FIN-05 | Core | HAVE | M | Confronto per riga leggendo CodiceArticolo dall'XML e abbinandolo al codice fornitore del listino; blocco facoltativo alla registrazione oltre la tolleranza. | **Fatto il 2026-11-09**: le righe delle fatture ricevute salvano il codice articolo dall'XML; sulla fattura collegata agli ordini, confronto per riga con il prodotto trovato dal codice del listino o delle righe d'ordine (o dalla descrizione), prezzo netto e quantità contro il ricevuto con la tolleranza; con l'impostazione accesa la registrazione fuori tolleranza si ferma e un responsabile può «Registra comunque». Le fatture passive si creano ancora solo dall'XML.
| FIN-33 | Adv | PARTIAL | M | Canale verso un intermediario accreditato con conservazione a norma nell'interfaccia di canali.py. Peppol tramite access point solo se servono clienti esteri. |
| LOC-03 | Adv | PARTIAL | M | Vedi FIN-33. |

### studio

2 voci aperte: 1 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PLT-06 | Core | PARTIAL | M | ProprietaMixin esteso a righe e modelli restanti, campo collegamento a record, editor delle voci di menu interne, personalizzazioni per ruolo e azienda. |
| PLT-21 | Adv | PARTIAL | L | Modelli definiti da UI, in tabelle generiche con JSON o migrazioni generate, che producono una ModelView con liste, form, permessi, chatter e API. |

### automazioni

2 voci aperte: 1 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PLT-08 | Core | PARTIAL | M | Eventi generici su qualsiasi ModelView, azioni di modifica campo, esecuzione di bottoni, chiamata webhook, e pagina front per le pianificazioni. |
| INT-06 | Adv | PARTIAL | M | Azione webhook firmata nelle regole, sottoscrizioni via API con ritentativi e registro, poi connettore pubblicato su una piattaforma. |

### theme

0 voci aperte.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|

### spese

1 voce aperta: 0 Core, 0 Adv, 1 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| HR-16 | Edge | MISSING | M | Lavoro in background che legge la ricevuta col modulo ai, propone data, importo e categoria, e segnala all'approvatore duplicati e incoerenze con la policy. |

### contatti

2 voci aperte: 1 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| CRM-06 | Core | HAVE | S | Modello IndirizzoContatto tipizzato (fatturazione, consegna, sede) con scelta su ordine e consegna e riporto in DDT e FatturaPA; società madre opzionale tra aziende. | **Fatto il 2026-11-07**: indirizzi di consegna, fatturazione e sedi sul contatto, scelta sull'ordine e sulla consegna, luogo di destinazione sul DDT; società madre tra aziende. La FatturaPA resta con la sede legale dell'anagrafica.
| CRM-11 | Adv | PARTIAL | M | Modello Segmento con regole salvate e ricalcolate, classe ABC periodica dal fatturato, uso del segmento in liste, automazioni e campagne. |

### assistenza

1 voci aperte: 1 Core, 0 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PRJ-06 | Core | HAVE | S | Pagina di dettaglio del progetto nel portale con avanzamento (Progetto.riepilogo_compiti), milestone e rilasci, e un flag sui compiti visibili al cliente. | **Fatto il 2026-11-07**: pagina del progetto nel portale con avanzamento, tappe, rilasci, richieste del cliente e i soli compiti segnati «visibile al cliente».

### ai

6 voci aperte: 0 Core, 0 Adv, 6 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| AI-05 | Edge | PARTIAL | M | Trigger per evento e assegnazione sugli assistenti (anche come azione di Automazioni), con budget e operazioni ammesse per agente ed esecuzione nel worker. |
| AI-07 | Edge | PARTIAL | M | Previsione di cassa da scadenze attive e passive più storico, domanda per prodotto con proposta di riordino, rilevamento degli scostamenti dalla previsione con avvisi. |
| FIN-36 | Edge | MISSING | M | Estrazione con modello visione da foto e PDF in bozza di riga spesa e di fattura passiva, sempre da confermare, sul gateway addons/ai/gateway. |
| FIN-38 | Edge | PARTIAL | M | Agente pianificato che controlla ogni fattura ricevuta contro ordine e storico, segnala le anomalie e propone registrazione o contestazione all'approvatore. |
| INV-21 | Edge | PARTIAL | M | Agente dedicato che incrocia previsione, scorte e fornitori e propone i riordini da confermare, spiegando il perché e imparando dalle proposte respinte. |
| PUR-14 | Edge | PARTIAL | M | Strumento dedicato che calcola il fabbisogno e propone gli ordini con la motivazione, e assiste la decisione sulle approvazioni, sopra le proposte con conferma già esistenti. |

### acquisti

5 voci aperte: 0 Core, 5 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| FIN-31 | Adv | MISSING | M | Regola per coppie di aziende che, alla conferma di un ordine di vendita, crea l'ordine d'acquisto speculare e collega le fatture. |
| PUR-10 | Adv | MISSING | M | Riga di vendita marcata «in triangolazione» che genera l'ordine al fornitore con il destinatario del cliente; conferma di spedizione senza movimentare la giacenza propria. |
| PUR-12 | Adv | MISSING | M | Link firmato o accesso fornitore per confermare ordine e data di consegna, comunicare ritardi e caricare DDT o fattura, sul modello di assistenza/portale.py. |
| PUR-13 | Adv | PARTIAL | M | Aggiungere alla pagella l'andamento dei prezzi rispetto al listino e agli altri fornitori; legare la qualità ai controlli in ingresso quando esisteranno (INV-18). |
| PUR-11 | Adv | MISSING | L | Ordine di conto lavoro con elenco componenti, DDT di invio verso un magazzino del terzista, rientro del finito con consumo dei componenti e costo della lavorazione. |

### rivendita

3 voci aperte: 0 Core, 3 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PLT-20 | Adv | PARTIAL | M | Registrazione degli editori con le loro chiavi, flusso di invio e revisione con modulo collauda automatico, scheda pubblica con recensioni, permessi dichiarati nel manifest. |
| PLT-22 | Adv | PARTIAL | M | Provisioning automatico per istanza dal portale (stack, database, dominio, TLS, token), aggiornamenti controllati e monitoraggio della flotta. |
| INT-07 | Adv | PARTIAL | L | Pubblicare un contratto del modulo versionato con politica di compatibilità e aggiungere al portale registrazione dei partner, chiavi di firma, revisione e pagamenti. |

### ricorrenti

2 voci aperte: 0 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| COM-09 | Adv | PARTIAL | M | Sezione portale con contratti, scadenze, fatture e disdetta entro i termini, modifica dei dati anagrafici e di pagamento con revisione interna. |
| FIN-28 | Adv | PARTIAL | M | Righe a consumo con misuratore, cambi piano con data di effetto e conguaglio pro-rata in fattura. |

### calendario

2 voci aperte: 0 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| CRM-13 | Adv | MISSING | M | Tipi di appuntamento con durata e operatori, fasce di disponibilità al netto degli eventi, pagina pubblica di prenotazione con conferma e .ics, contatto od opportunità creati in automatico. |
| PRJ-13 | Adv | PARTIAL | M | Tipi di appuntamento con durata e orari, pagina pubblica che propone fasce libere dalle agende, conferma con .ics, cancellazione e promemoria. |

### documenti

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PLT-24 | Adv | PARTIAL | M | Richieste di firma su ogni PDF con più firmatari in ordine, verifica via email o SMS, firma apposta sul PDF con pagina di evidenze e impronta, archiviata nei documenti. |

### awf

1 voci aperte: 0 Core, 0 Adv, 1 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| AI-04 | Edge | PARTIAL | L | Definire e collaudare i cinque agenti come offerta del catalogo o come pacchetti locali, ciascuno con operazioni ammesse, domande d'oro e casi di prova. |

## Applicazioni nuove che servirebbero

Nessuna di queste esiste oggi: il nome è solo una proposta.

### portale

2 voci aperte: 2 Core, 0 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| COM-01 | Core | HAVE | M | Spostare AccessoPortale e l'involucro del portale in un modulo proprio, con sezioni registrate dalle app (vendite, fatturazione, documenti, assistenza) tramite hook e filtro unico sul cliente. |
| CRM-09 | Core | HAVE | M | Sezioni Preventivi, Ordini e Fatture nel portale filtrate su AccessoPortale.contatti(), con PDF scaricabili e riuso di operazioni.accetta per i preventivi aperti. |

### obiettivi

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| HR-11 | Adv | MISSING | M | Obiettivi per dipendente o reparto con misura, avanzamento; riconoscimenti pubblicati in Discuss. |

### wiki

1 voci aperte: 1 Core, 0 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PRJ-05 | Core | PARTIAL | M | App di pagine gerarchiche in markdown con permessi per spazio, versioni, ricerca e collegamenti ai record, indicizzate dalla conoscenza di addons/ai. |

### sync_posta_calendario

1 voci aperte: 1 Core, 0 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INT-01 | Core | PARTIAL | L | OAuth per utente con Google e Microsoft: posta collegata ai record per mittente e sync bidirezionale degli eventi, più un feed ICS privato come primo passo. |

### connettori_pagamenti_spedizioni

1 voci aperte: 1 Core, 0 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INT-03 | Core | PARTIAL | L | Link di pagamento su fatture e scadenze (Stripe o Nexi) con incasso automatico da webhook, feed bancario PSD2 tramite aggregatore, spedizioni e tracking con uno o due corrieri. |

### interventi

3 voci aperte: 0 Core, 3 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| PRJ-09 | Adv | MISSING | M | Termini di garanzia per prodotto, scadenza calcolata dalla consegna per seriale, pratica con esito e addebito o copertura, con recupero dal fornitore. |
| PRJ-11 | Adv | MISSING | M | Ordine di riparazione con ingresso del bene, preventivo, ricambi scaricati da magazzino, ore da timesheet, riconsegna e fattura. |
| PRJ-08 | Adv | PARTIAL | L | App con ordine di intervento da ticket o contratto, pianificazione su calendario dei tecnici, rapportino da mobile con firma, ore e materiali, e fatturazione tramite commesse. |

### marketing

2 voci aperte: 0 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| CRM-10 | Adv | PARTIAL | L | Campagne a passi con attese e condizioni di uscita su un segmento di contatti, costruite sopra motore e modelli email, con registro consensi, disiscrizione e tracciamento. |
| CRM-12 | Adv | MISSING | L | Campagne email con liste e disiscrizione, gateway SMS, sondaggi con link pubblico e risultati, eventi con iscrizioni e partecipanti: da spezzare in rilasci separati. |

### promozioni

2 voci aperte: 0 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| COM-07 | Adv | MISSING | M | Riuso del motore promozioni e saldi di CRM-17 sui canali POS ed eCommerce, se riaperti. |
| CRM-17 | Adv | PARTIAL | L | Regole promozionali e coupon applicati alle righe di vendita, carte regalo e punti come saldo del contatto con registro movimenti; il noleggio segue COM-11. |

### spedizioni

2 voci aperte: 0 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INV-17 | Adv | MISSING | M | Modello Spedizione con colli e modelli di imballo, viaggi di consegna con mezzo, autista e ordine delle tappe. |
| INV-16 | Adv | MISSING | L | Connettori verso corrieri italiani e aggregatori, con preventivo, creazione spedizione, stampa etichetta e aggiornamento dello stato. |

### manutenzione

2 voci aperte: 0 Core, 2 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| MFG-13 | Adv | MISSING | M | Anagrafica attrezzature, piani periodici che generano interventi, interventi correttivi con ricambi e ore; legame opzionale ai centri di lavoro. |
| PRJ-10 | Adv | MISSING | L | Registro attrezzature per sede o cliente, piani preventivi a calendario o a contatore che generano interventi, storico guasti e costi. |

### controllo_merce

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INV-18 | Adv | MISSING | M | Punti di controllo per prodotto e fase con esito superato o respinto, blocco in quarantena e non conformità legata al fornitore, tenendo separata l'app qualita. |

### iot

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| MFG-16 | Adv | MISSING | L | Agente locale che collega bilance, stampanti e sensori via API, con eventi che si traducono in operazioni di magazzino. |

### competenze

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| HR-10 | Adv | MISSING | L | Catalogo competenze con livelli per dipendente, certificazioni con scadenza e avviso; corsi con lezioni e quiz in un secondo passo. |

### flotta

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| HR-12 | Adv | MISSING | M | Veicoli assegnati ai dipendenti, contratti di leasing e assicurazione, scadenze (revisione, bollo), costi e chilometri, con avvisi. |

### turni

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| HR-13 | Adv | MISSING | M | Modelli di turno, griglia settimanale per reparto con trascinamento, controllo su assenze e sovrapposizioni, pubblicazione e scambio; le ore pianificate alimentano capacita. |

### reception

0 voci aperte.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| HR-14 | Adv | HAVE | S | **Fatto il 2026-11-08** nel nuovo modulo `reception`: vedi la sezione B. |

### connettori

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| COM-08 | Adv | MISSING | L | Quadro di connettori con mappature, coda e riprova sul modello di discuss/connettori.py; primi: un corriere (etichette e tracking) e uno store (ordini e giacenze). |

### noleggio

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| COM-11 | Adv | MISSING | L | Noleggi con disponibilità per periodo, ritiro, rientro, cauzione e fatturazione; biglietti con tipologie, posti, QR e check-in, in un modulo eventi separato. |

### report_designer

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| RPT-07 | Adv | PARTIAL | L | Editor di layout per stampe e report su dataset definiti da viste e campi collegati, resi con WeasyPrint. Un eventuale SQL solo in sola lettura e su viste autorizzate. |

### fogli

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| RPT-08 | Adv | MISSING | L | Foglio web con componente esistente, salvato nei Documenti, con funzioni che leggono da core/viste/interroga.py con i permessi di chi apre. |

### connettori_bi

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| RPT-09 | Adv | PARTIAL | M | Dataset analitici documentati con estrazione incrementale, feed OData o schema SQL di sola lettura per azienda, con guide per Power BI e Metabase. |

### esporta_dati

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| RPT-10 | Adv | MISSING | M | Esportazione pianificata e incrementale (Parquet o CSV su storage esterno, per azienda) e supporto a una replica Postgres per letture pesanti e analisi. |

### acquisizione_documenti

1 voci aperte: 0 Core, 0 Adv, 1 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| AI-02 | Edge | MISSING | M | Pipeline allegato, OCR o modello con visione, campi estratti con punteggio di confidenza, bozza di FatturaPassiva o riga spesa confermata da una persona. |

### suite_ufficio

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INT-02 | Adv | PARTIAL | L | Prima notifiche e comandi su Slack e Teams via webhook, poi add-in Outlook collegato ai contatti e collegamento ai file di Drive e OneDrive dai Documenti. |

### firma_elettronica

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INT-04 | Adv | MISSING | M | Connettore astratto con un provider (Namirial o Yousign): invio dagli allegati, firmatari, webhook di stato e documento firmato archiviato nel record. |

### connettori_commerce

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INT-05 | Adv | MISSING | L | Base comune di sincronizzazione (mappature, code, riprova) e primo connettore Shopify o WooCommerce per ordini, giacenze e prezzi. |

### edizioni

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| INT-09 | Adv | PARTIAL | M | Formato dichiarativo di edizione (moduli, ruoli, automazioni, campi personalizzati, cruscotti, dati demo) applicabile a un'istanza, con una prima edizione di settore di prova. |

### retail

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| IND-01 | Adv | MISSING | L | Dopo aver riaperto POS e varianti: pacchetti con dati iniziali, ruoli e automazioni per tipo di negozio. |

### ospitalita

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| IND-02 | Adv | MISSING | L | Modulo con camere, tariffe, prenotazioni, conto ospite con addebiti e pulizie; la ristorazione dipende da COM-06. |

### verticali

1 voci aperte: 0 Core, 1 Adv, 0 Edge.

| ID | Tier | Stato | Effort | Cosa costruire |
|---|---|---|---|---|
| IND-04 | Adv | MISSING | L | Moduli separati da scegliere in base al mercato, sopra il meccanismo dei modelli di settore: nessuno ha senso prima di una richiesta concreta. |

## B. Risultati completi

### Piattaforma e architettura (PLT)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| PLT-01 | Multi-azienda e filiali in un solo database, con report consolidati | Core | PARTIAL | core/mixins.py AziendaMixin (47 modelli); core/azienda.py consentite, corrente; core/middleware.py AziendaCorrenteMiddleware; core/viste/base.py get_queryset, form_per_azienda; core/api/auth.py azienda_per (header X-Azienda); core/sequenze.py per azienda; README sezione Multi-azienda | Separazione per azienda completa con selettore, scelte FK filtrate, API e sequenze. Dal 2026-11-08 consolidato su più aziende dell'utente in interrogazioni, grafici e KPI di Analisi (scelta «Tutte le mie aziende» o una sola diversa dalla corrente) e negli strumenti aggrega_record e grafico di Ada: ogni azienda con le regole della sua vista, poi somme, conteggi, minimi e massimi uniti per gruppo e medie da somme e conteggi (core/viste/interroga.py aziende_di, _aggrega_aziende, _kpi_aziende; core/tests/test_consolidato.py). Mancano le filiali come livello sotto l'azienda e le operazioni tra aziende |
| PLT-02 | Multi-valuta: tabelle cambi, aggiornamento automatico, differenze di cambio | Core | MISSING | Nessun campo valuta o cambio nei modelli (ricerca su valuta, currency, cambio: «valuta» in addons/banca è la data valuta); addons/fatturazione/fatturapa.py _sub Divisa fissa a EUR; simbolo € in oltre 200 punti tra codice e template; addons/automazioni/catalogo.py _euro | Tutto in euro: importi senza valuta, nessuna tabella cambi. Le differenze di cambio andrebbero solo calcolate e mostrate: le scritture contabili restano al commercialista |
| PLT-03 | Controllo accessi per ruoli: gruppi, regole sulle righe, visibilità per campo | Core | HAVE | core/regole.py (nascosti, bloccati, applica_righe, adatta_form); core/models.py PermessoCampo, RegolaRiga; core/viste/registry.py _con_regole; core/viste/base.py colonne; core/api/modelli.py campi_api; core/viste/interroga.py controlla_nascosti; core/tests/test_regole_accesso.py | Fatto il 2026-11-08: da Utenti → Ruoli si dichiarano campi nascosti o in sola lettura per ruolo e regole sulle righe (campo, condizione, valore; «è l'utente che guarda» per commerciale, responsabile…). Le regole sulle righe avvolgono get_queryset di ogni vista, anche quelle che lo ridefiniscono: valgono per liste, dettagli, API, export e assistente; una regola rotta nasconde tutto. I campi nascosti spariscono da form, dettaglio, lista, export, API e dalle letture di Ada, e non si possono filtrare, raggruppare né sommare; quelli in sola lettura sono disabilitati nel form (vale il valore salvato). Restano fuori kanban, pivot, calendario e stampe, che mostrano ancora tutti i campi della vista |
| PLT-04 | Storico modifiche su ogni record (chi, cosa, quando, valori vecchi e nuovi) | Core | HAVE | core/registro.py; core/models.py RegistroModifica; core/viste/base.py storico; core/tests/test_ricerche_pivot_registro.py | Fatto il 2026-11-05: registro di chi, cosa, quando e da dove su ogni record con una vista e sulle righe dei documenti, in sola lettura e senza segreti. Non vede QuerySet.update(), bulk_create() e i molti-a-molti; non è protetto a livello di database e non ha una pulizia automatica. |
| PLT-05 | Numerazioni per azienda e tipo documento; esercizi, periodi, date di blocco | Core | PARTIAL | core/sequenze.py prossimo (select_for_update), core/models.py Sequenza (azienda, codice, formato, azzera); chiave manifest sequences; core/admin.py SequenzaAdmin; addons/fatturazione/operazioni.py controllo della data rispetto alle fatture emesse; addons/timesheet/models.py bloccata | Sequenze solide per azienda e tipo, con azzeramento annuale. Formato modificabile solo dall'admin Django, riservato al Global Admin. Nessun esercizio diverso dall'anno solare e nessuna data di blocco che impedisca di modificare documenti, incassi o registri IVA di periodi chiusi. Il controllo sulle fatture è solo sulla sequenza delle date. Contabilità generale esclusa, ma il blocco dei periodi IVA e documentali resta utile |
| PLT-06 | Campi, form, liste e menu configurabili senza codice | Core | PARTIAL | core/views.py CampoPersonalizzatoView (/core/campi/); core/proprieta.py; core/mixins.py ProprietaMixin (13 modelli); addons/studio/campi.py, servizi.py (colonne, filtri, ricerca, raggruppamenti, form, etichette, storico, esporta/importa); core/viste/personalizza.py ATTRIBUTI; core/barra.py, core/applicazioni.py nome | Liste, form e etichette configurabili, con storico. Campi personalizzati solo su 13 modelli, nessuno sulle righe dei documenti; nessun tipo collegamento a un record. Menu: solo ordine, visibilità e nome delle app nella barra; le voci interne vengono dal manifest. Studio vale per tutta l'istanza, non per ruolo o azienda, e non ha campi condizionali |
| PLT-07 | Motore di approvazioni multilivello (ordini d'acquisto, spese, ferie, sconti) | Core | HAVE | core/approvazioni.py (controlla, decidi, puo_decidere, promemoria, avvolgi); core/models.py CatenaApprovazione, PassoApprovazione, RichiestaApprovazione, DecisioneApprovazione, Delega; core/views.py da_approvare; core/tests/test_approvazioni.py | Fatto il 2026-11-08: catene configurabili su qualsiasi bottone di qualsiasi documento (es. conferma dei preventivi da 5.000 € o con uno sconto di riga da 15 %), per azienda o per tutte, con passi in ordine per ruolo o persona e giorni per decidere; il bottone resta bloccato finché l'ultimo passo non approva, dalla pagina, dall'API e dall'assistente; chi chiede non approva; deleghe con periodo; se il valore sale serve un nuovo giro; storico delle decisioni, pagina «Da approvare», avvisi nel chatter e promemoria dei passi scaduti. Le approvazioni specifiche di acquisti, spese e ferie restano accanto. Non bloccano le azioni di massa dalla lista |
| PLT-08 | Regole di automazione e lavori pianificati (creazione, modifica, tempo, azioni server) | Core | PARTIAL | addons/automazioni/motore.py, regole.py, catalogo.py FONTI, pagine.py (costruttore, simulazione, storico, riprova); core/lavori.py; core/cron.py; core/models.py Lavoro, Pianificazione; core/management/commands/worker.py; core/admin.py PianificazioneAdmin | Motore reale con condizioni, prova a secco, eventi al salvataggio e a tempo, esecuzioni uniche. Eventi solo da catalogo a codice su 7 fonti (fatture, ticket, ordini, CRM, attività, contratti, compiti): fuori acquisti, magazzino, personale, spese. Quattro azioni soltanto (email, attività, nota, assegna): nessuna scrittura di campi, webhook o azione server. Pianificazioni solo da manifest, attivabili nell'admin Django |
| PLT-09 | Modelli di stampa e PDF modificabili per tipo documento e azienda | Core | HAVE | core/stampe.py; core/models.py ModelloStampa; core/report.py html; core/templates/core/report/base.html; core/views.py ModelloStampaView, anteprima_stampa; core/tests/test_modelli_stampa.py | Fatto il 2026-11-08: per azienda (o per tutte) e per documento (preventivo, fattura, DDT, ordine d'acquisto, ogni report delle viste) colore, logo sì o no, righe sotto l'intestazione, testo prima e dopo il documento con segnaposto ({{ cliente }}, {{ documento }}, {{ totale }}…, sostituiti senza eseguire codice e con l'escape), piè di pagina, colonne nascoste tra quelle che il documento permette (in fattura solo sconto e codice IVA); anteprima sull'ultimo documento vero e «Torna all'originale». Provato con il PDF vero di WeasyPrint. Nessun editor grafico del layout |
| PLT-10 | Email sui record: invio e ricezione, log a thread, follower, menzioni, messaggi fissati | Core | HAVE | core/chatter/__init__.py scrivi, fissa, menzionati, puo_vedere; core/chatter/email.py notifica, menzioni, _allega; core/chatter/entrata.py esterno_ammesso; core/viste/chatter.py fissa, indirizzi; core/tests/test_chatter_plt10.py | Fatto il 2026-11-08: messaggi e note fissati in cima; le @menzioni arrivano per email anche senza Discuss (con Discuss nella posta in arrivo); campo «Anche a» per scrivere a indirizzi esterni scelti al momento, con proposte dal record (cliente, fornitore), allegati inviati davvero e risposte che tornano sul record. Chatter attivato anche su scadenze, scadenze da pagare, distinte, lotti, istanze e richieste di rivendita: 37 viste, le altre sono tabelle di configurazione. Manca il completamento automatico delle @menzioni nel pannello |
| PLT-11 | Chat interna, messaggi diretti e canali | Core | HAVE | addons/discuss/models.py Canale, Iscrizione, Messaggio, Reazione, Presenza; addons/discuss/pagine.py nuovo_canale, diretto, invia, cerca; addons/discuss/servizi.py; addons/discuss/notifiche.py; addons/discuss/tests/test_chat.py | Completa: canali, diretti, gruppi, thread, reazioni, fissati, ricerca, presenza, chiamate; anche sito, WhatsApp e Telegram |
| PLT-12 | Allegati e gestione documenti con cartelle, tag, versioni | Core | HAVE | addons/documenti/models.py Cartella, Documento, Tag, Versione, Spazio, Condivisione; addons/documenti/pagine.py, servizi.py, accesso.py, quote.py, collegamenti.py; core/allegati.py; core/viste/allegati.py; addons/documenti/tests/ | Completa: cartelle con permessi ereditati, tag, versioni con ripristino, cestino, quote, link pubblici, cartelle legate ai record |
| PLT-13 | Import CSV e XLSX con mappatura, validazione e varianti per riga; export di massa | Core | PARTIAL | core/importa.py proponi, valida, esegui, in_background; core/viste/importa.py; core/esporta.py; core/viste/esporta.py; ModelView.import_key | Mappatura colonne, prova a secco con errori per riga, tutto o niente, worker, export Excel e CSV su ogni vista. Mancano le varianti di prodotto, assenti in tutto il prodotto (nessun riferimento in addons), e l'import delle righe dei documenti: campi() legge solo i campi del form, non gli inline. import_key dichiarato solo in 5 viste |
| PLT-14 | API REST o JSON-RPC su tutti i modelli, con autenticazione e webhook | Core | HAVE | core/api/modelli.py (router per ogni ModelView, campi_api con filtro SEGRETI, schema_record, /azioni/<nome>/); core/api/__init__.py LimitePerToken; core/models.py TokenApi; addons/connettori (webhook firmati); core/tests/test_api_ovunque.py | Fatto il 2026-11-08: API accesa di default su tutte le viste (circa 110), spenta solo dove ci sono segreti o credenziali (chiavi AI, provider, server MCP, webhook, fornitori di pagamento, connessioni, accessi social, istanze), campi segreti mai in uscita, bottoni via API, token con scadenza, sola lettura e moduli (2026-11-05), limite di richieste al minuto per token (API_LIMITE, 429 con Retry-After), webhook in uscita nei Connettori. Il limite usa la cache di Django: con più processi senza una cache condivisa vale per processo |
| PLT-15 | Interfaccia multilingua e valori dei campi traducibili | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... lingue oltre l'italiano»; config/settings.py LANGUAGE_CODE it, nessun LocaleMiddleware né LOCALE_PATHS; nessun .po; nessun gettext né {% trans %} in addons e core | Esclusa esplicitamente dalla spec, ma è una voce Core del benchmark: la decisione va riconfermata se si vende fuori dall'Italia. Costo se riaperta: L, per testi cablati in italiano ovunque, inclusi manifest e template |
| PLT-16 | Interfaccia responsive e app mobile native o PWA sui flussi principali | Core | HAVE | theme/views.py manifest, icona, service_worker, offline; theme/templates/theme/sw.js; core/push.py (cifra RFC 8291, vapid, invia); core/models.py IscrizionePush; core/views.py tasca, iscrivi_push; core/static/core/push.js; core/tests/test_pwa_push.py | Fatto il 2026-11-08: app installabile dal browser (manifest, icone, service worker con pagina offline e cache degli statici; le pagine con i dati vengono sempre dal server), pagina «In tasca» per il telefono con attività del giorno, approvazioni, nota spese con foto, giacenze, reception, Ada e messaggi secondo i permessi; notifiche push Web Push con VAPID scritte senza librerie in più, attivabili per dispositivo dal profilo, mandate per ogni notifica di Discuss (menzioni, messaggi diretti, attività, approvazioni). Servono un indirizzo https e, su iPhone, l'app aggiunta alla Home. Nessuna app nativa |
| PLT-17 | Ricerca globale, filtri salvati e preferiti; viste kanban, lista, pivot, grafico, calendario, Gantt | Core | PARTIAL | core/viste/lista.py, filtri.py, gruppi.py, kanban.py, calendario.py, grafico.py, interroga.py; addons/grafici/costruttore.py; addons/capacita/pagine.py gantt; addons/discuss/pagine.py palette (Ctrl+K) | Lista con raggruppamenti, kanban, calendario e grafico generici. Mancano: ricerca globale sui record (Ctrl+K copre solo canali, persone e messaggi, e richiede discuss; l'AI cerca solo in conversazione); filtri salvati e preferiti (restano nell'URL); vista pivot; Gantt generico (solo capacita, in sola lettura) |
| PLT-18 | Attività pianificate, notifiche, posta da fare per utente | Core | HAVE | core/attivita.py pianifica, raggruppate, promemoria; core/models.py AttivitaPianificata, TipoAttivita; core/views.py attivita_mie (/attivita/); core/viste/chatter.py attivita_fatta; addons/discuss/notifiche.py, addons/discuss/pagine.py posta, contatore | Completa con discuss installato: la campanella e la posta in arrivo vengono da lì; senza, restano /attivita/ e i promemoria email |
| PLT-19 | Tolleranza alla perdita di connessione nell'interfaccia | Adv | HAVE | theme/static/theme/rete.js; core/templates/core/vista/form.html data-bozza; theme/tests/test_rete.py | Fatto il 2026-11-08: su ogni pagina una barra «Sei offline» finché la rete non torna; gestore globale di htmx:sendError, htmx:timeout e htmx:responseError con un avviso chiaro per tipo di errore e «Riprova» che rifà la stessa richiesta; bozza locale per utente dei form delle viste, proposta alla riapertura se l'invio non è arrivato o la scheda si è chiusa, cancellata all'uscita. Le righe aggiunte a mano nei form con righe non si ripristinano; i form fuori dalle viste non hanno la bozza |
| PLT-20 | Marketplace di moduli: installare moduli di terzi senza toccare il kernel | Adv | PARTIAL | core/registry/pacchetti.py (firma, hash, estrazione); core/management/commands/modulo.py impacchetta, carica, indice, collauda; core/views.py moduli_carica, moduli_scarica; core/applicazioni.py; core/licenza.py; addons/rivendita/models.py, servizi.py, api.py; MODULI_CHIAVI_FIDATE | Moduli installabili senza forkare, con catalogo firmato e richieste dal cliente. Il catalogo è però del solo venditore ICHNOBYTE: nessun accesso per editori terzi, revisione, recensioni o pagamento. Un modulo gira con tutti i privilegi del processo |
| PLT-21 | Costruttore low-code di app (modelli, viste, automazioni dalla UI) | Adv | PARTIAL | addons/studio/ (viste esistenti); core/proprieta.py (campi JSON); addons/automazioni/pagine.py (regole); core/viste/interroga.py | Si adattano viste esistenti e si aggiungono campi e regole, ma non si creano nuovi modelli, relazioni o app dalla UI. Ogni modello richiede codice e migrazione |
| PLT-22 | Opzioni di installazione: SaaS multi-tenant e on-premise | Adv | PARTIAL | deploy/compose.cliente.yml, deploy/Dockerfile.cliente, docker-compose.yml, deploy/entrypoint.sh, deploy/nginx.conf; core/licenza.py; addons/rivendita/models.py Istanza; spec fase 1 «Multi-azienda dal primo giorno, multi-tenant mai» | On-premise e istanza ospitata per singolo cliente funzionano con Docker. Multi-tenant escluso per scelta di modello. Manca la creazione automatica di un'istanza ospitata: Rivendita gestisce licenze e moduli, non provisioning, aggiornamenti della flotta o backup remoti |
| PLT-23 | SSO (OAuth2, SAML), due fattori, LDAP o AD | Adv | PARTIAL | core/due_fattori.py, core/due_fattori_viste.py, core/models.py DueFattori, core/middleware.py DueFattoriObbligoMiddleware; core/utenti.py due_fattori_azzera; django-axes in requirements.txt | Due fattori completi: TOTP, codici di recupero, dispositivi fidati, obbligo per amministratori o per tutti. SSO, OIDC, SAML e LDAP assenti: nessuna libreria in requirements.txt e nessun backend nel codice |
| PLT-24 | Firma elettronica integrata sui documenti | Adv | PARTIAL | addons/vendite/operazioni.py accetta (nome, IP, impronta); addons/vendite/models.py risposta_*; addons/vendite/templates/vendite/online.html | Solo accettazione online dei preventivi: nome digitato, data, IP e impronta del documento. Nessuna richiesta di firma su documenti qualsiasi, firma disegnata, più firmatari, verifica OTP, PDF firmato o certificato di completamento |
| PLT-25 | Foglio di calcolo o BI integrati con collegamenti vivi ai dati | Adv | PARTIAL | addons/grafici/models.py Pagina, Grafico; addons/grafici/costruttore.py, motore.py, lavori.py; core/viste/interroga.py; core/static/core/grafici.js; core/esporta.py | BI presente: grafici e KPI da query salvate che si aggiornano, pagine condivise, drill-down, previsioni. Nessun foglio di calcolo con celle e formule collegate ai dati; nessuna tabella pivot; l'export è un'istantanea |
| PLT-26 | Ambienti sandbox o staging e anonimizzazione dei dati di prova | Adv | PARTIAL | core/management/commands/modulo.py collauda (istanza usa e getta); core/management/commands/dati_demo.py; core/backup.py; addons/qualita/models.py Ambiente (solo anagrafica); addons/discuss/sandbox.py (solo canali di messaggistica) | Si possono alzare istanze separate, con collaudo moduli e dati demo. Nessuna funzione per clonare la produzione in staging né per anonimizzare i dati (nessun riferimento nel codice; adabox-pii maschera solo i testi verso i modelli AI) |

### Finanza e contabilità (FIN)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| FIN-01 | Contabilità generale in partita doppia e registri per tipo | Core | N/A | addons/banca/abbina.py (docstring: nessuna registrazione contabile); nessun modello di mastro in addons/ | Decisione utente 2026-11-03: la contabilità generale resta al commercialista. Fatta il 2026-11-05 l'esportazione per lo studio: addons/fatturazione/commercialista.py prepara uno ZIP del periodo con registri, XML, incassi, crediti e debiti aperti e movimenti di banca |
| FIN-02 | Piano dei conti configurabile e centri di costo | Core | N/A | Nessun modello conto contabile; banca.Conto è solo il conto bancario (addons/banca/models.py) | Decisione utente 2026-11-03. Niente esportazione specifica oltre a quella di FIN-01; i centri di costo fuori dal mastro sono valutati in FIN-20 |
| FIN-03 | Contabilità per competenza e per cassa | Core | N/A | Nessun mastro; regime RF17 IVA per cassa solo come codice in fatturazione.DatiFiscali.REGIMI | Decisione utente 2026-11-03. L'esportazione di FIN-01 dovrebbe riportare date di documento e di incasso, utili allo studio per entrambi i criteri |
| FIN-04 | Fatture, note di credito, termini, rate e invio email | Core | HAVE | addons/fatturazione/operazioni.py (emetti, nota_di_credito, da_ordine, da_consegne); addons/fatturazione/lavori.py invia con PDF; addons/fiscale/calcoli.py scadenze; addons/fiscale/models.py TerminePagamento; addons/fatturazione/views.py FatturaView | Completa anche per TD differite, autofatture, bollo, CIG e CUP. Le rate si scrivono come JSON a mano nel form del termine: usabile ma scomodo |
| FIN-05 | Fatture fornitore proposte da ordini o ricevimenti (3-way match) | Core | HAVE | addons/acquisti/riscontro.py fattura_ricevuta, _candidati; addons/sdi/passive.py | Migliorata in questo lavoro: la fattura SDI trova da sola l'ordine (numero, DDT, causale) e si confronta con merce e ordine. Mancano il confronto per riga e il blocco alla registrazione; le fatture passive si creano solo dall'XML. Fatto il 2026-11-09: riscontro.confronto_righe e blocco alla registrazione. |
| FIN-06 | Scadenziario clienti e fornitori con aging a fasce | Core | HAVE | addons/fatturazione/scadenzario.py tabella, risposta; addons/sdi/pagine.py scadenzario_fornitori; core/viste/filtri.py _campo; test_scadenzario_commercialista.py | Fatto il 2026-11-05: clienti e fornitori a fasce (a scadere, 1-30, 31-60, 61-90, oltre 90), per controparte, con link alle scadenze, CSV e PDF. Le note di credito ricevute non contano come debiti. Non c'è un partitario con saldo progressivo. |
| FIN-07 | Fido clienti con avviso o blocco sugli ordini | Core | HAVE | addons/contatti/models.py fido, fido_blocca; addons/vendite/fido.py; addons/vendite/views.py conferma; addons/vendite/operazioni.py accetta; addons/vendite/tests/test_fido.py | Fatto il 2026-11-05: fido sul contatto, esposizione da scadenze aperte e ordini non fatturati, avviso o blocco per contatto. Il preventivo accettato online oltre un fido bloccante resta accettato e aspetta una conferma a mano. |
| FIN-08 | Solleciti di pagamento a livelli con email | Core | HAVE | addons/automazioni/ricette.py (preavviso, sollecito, sollecito_deciso); addons/automazioni/catalogo.py evento fattura.scaduta; addons/automazioni/motore.py Esecuzione.chiave evita i doppi; addons/automazioni/tests/test_automazioni.py test_sollecito_una_volta_sola_e_mai_sulle_pagate | I livelli sono regole configurabili, create spente, con storico delle esecuzioni e attività di chiamata. Limiti minori: un'email per scadenza, nessun riepilogo per cliente, nessun interesse di mora |
| FIN-09 | Importazione estratti conto | Core | HAVE | addons/banca/estratti.py (leggi, _camt, _mt940, _cbi, _tabella per CSV ed Excel); addons/banca/abbina.py importa; addons/banca/pagine.py importa; addons/banca/tests/test_banca.py | CAMT.053, MT940, CBI, CSV ed Excel, con deduplica e quadratura dei saldi. OFX e QIF non ci sono: scelta ragionevole per le banche italiane, da aggiungere solo se richiesti |
| FIN-10 | Sincronizzazione bancaria automatica | Core | HAVE | Nessuna integrazione PSD2 o aggregatore in addons/banca; solo caricamento manuale del file | Nulla di presente; Importazione e impronte di deduplica sono riutilizzabili Fatto il 2026-11-09: addons/banca/sincronia.py. |
| FIN-11 | Riconciliazione con suggerimenti e modelli di abbinamento | Core | HAVE | addons/banca/abbina.py (_valuta, proposte, e_sicura, abbina_i_sicuri, abbina); addons/banca/pagine.py riconcilia, scegli | Suggerimenti a punteggio su numero, importo, partita IVA e nome, abbinamento multiplo e dei casi sicuri con conferma. Mancano i modelli configurabili e la gestione dei movimenti senza documento (commissioni, F24, stipendi), che si possono solo ignorare Fatto il 2026-11-09: banca.RegolaMovimento e classifica.py. |
| FIN-12 | Pagamenti parziali, eccedenze, abbuoni e crediti da allocare | Core | HAVE | addons/fatturazione/operazioni.py (registra_incasso, incassa_fattura, _compensa, da_rimborsare); fatturazione.Incasso tipo abbuono; addons/banca/abbina.py _su_passiva | Lato clienti ci sono parziali, abbuoni e compensazione con nota di credito. Mancano eccedenze e acconti non allocati (importo oltre il residuo rifiutato). Lato fornitori ScadenzaPassiva non ha parziali né abbuoni: va pagata per intero Fatto il 2026-11-09: fatturazione.CreditoCliente, sdi.PagamentoPassivo. |
| FIN-13 | Casse e piccola cassa con saldo di apertura e chiusura | Core | HAVE | banca.Conto richiede IBAN; Incasso.metodo contanti è solo un'etichetta; nessun modello di cassa | Nulla di presente. Si può fare senza mastro Fatto il 2026-11-09: modulo addons/cassa. |
| FIN-14 | Stampa assegni e pagamenti a lotti | Core | HAVE | addons/sdi/views.py ScadenzaPassivaView paga_selezionate; addons/fatturazione/views.py incassa_selezionate | Le azioni di gruppo cambiano solo lo stato (segna pagate). Nessuna distinta di pagamento né stampa assegni, marginale in Italia | Dal 2026-11-07 addons/distinte (Distinta e VoceDistinta).
| FIN-15 | Motore fiscale: gruppi, IVA inclusa, posizioni fiscali, ritenute | Core | HAVE | addons/fiscale/models.py AliquotaIva (natura, esigibilità, scissione); addons/fiscale/calcoli.py riepilogo_iva; fatturazione.Ritenuta e CassaPrevidenziale; Fattura.bollo_dovuto; addons/fatturazione/fatturapa.py | Coperti nature, split payment, ritenute attive, casse e bollo. Mancano prezzi IVA inclusa, gruppi di imposte, posizioni fiscali per cliente o paese: l'aliquota viene dal prodotto o ripiega su 22, anche per esteri, PA e dichiarazioni d'intento. Ritenute delle fatture passive non lette (passive.leggi ignora DatiRitenuta) Fatto il 2026-11-09: fatturazione/posizioni.py. |
| FIN-16 | Report IVA di periodo con export per l'Agenzia | Core | HAVE | addons/fatturazione/registro.py registro_iva; addons/sdi/pagine.py registro_acquisti | Registri vendite e acquisti per mese o anno con riepilogo e CSV. Mancano la liquidazione periodica (debito meno credito), la gestione di esigibilità differita e split nei totali, le autofatture separate, la detraibilità, il conteggio trimestrale del bollo e il file LIPE | Fatto il 2026-11-07: modulo `iva` (addons/iva/calcolo.py, lipe.py); pro-rata e IVA di gruppo esclusi.
| FIN-17 | Cespiti e ammortamenti | Core | N/A | Solo il tipo documento TD26 in fatturazione.Fattura.TIPI | Decisione utente 2026-11-03. Esportazione non necessaria: lo studio ricava i cespiti dalle fatture passive |
| FIN-18 | Risconti di ricavi e costi su più periodi | Core | N/A | Le date ci sono: ricorrenti.FatturaCanone dal e al (addons/ricorrenti/models.py) | Dipende dal mastro, decisione utente 2026-11-03. Servirebbe un'esportazione a fine anno delle quote di competenza dei contratti, ricavabile da FatturaCanone |
| FIN-19 | Budget con confronto budget e consuntivo | Core | HAVE | addons/progetti/models.py budget_ore e budget(); addons/progetti/segnali.py controlla_budget; addons/commesse/operazioni.py redditivita | Budget solo in ore per progetto, con avvisi all'80 e al 100 per cento. La redditività confronta ricavi e costo ore. Mancano budget in euro, per periodo o centro di costo, e i costi non orari (acquisti, fatture passive, note spese) nel consuntivo Fatto il 2026-11-09: analitica.Budget. |
| FIN-20 | Contabilità analitica a dimensioni | Core | HAVE | addons/commesse/operazioni.py redditivita; commesse.FatturaProgetto; fatturazione.Fattura.commessa è testo libero per l'XML verso la PA | Un solo asse (progetto) e solo ricavi e ore. Righe di fattura attive e passive, ordini d'acquisto e spese non hanno dimensioni analitiche; niente modelli di ripartizione né modifica massiva. Fattibile senza mastro Fatto il 2026-11-09: addons/analitica. |
| FIN-21 | Bilancio, conto economico, flussi, bilancio di verifica | Core | N/A | Nessun mastro | Decisione utente 2026-11-03. Le scadenze aperte sono in FIN-06; l'esportazione per lo studio è quella di FIN-01 |
| FIN-22 | Valorizzazione del magazzino contabilizzata | Core | N/A | magazzino.Movimento senza costo (addons/magazzino/models.py); prodotti.Prodotto.costo unico (addons/prodotti/models.py) | La contabilizzazione dipende dal mastro, decisione utente 2026-11-03. Servirebbe però un'esportazione delle rimanenze valorizzate a una data, che oggi manca: i movimenti non registrano il costo, quindi niente FIFO né costo medio |
| FIN-23 | Scritture di assestamento e storni automatici | Core | N/A | Nessun mastro | Decisione utente 2026-11-03. Le fatture da ricevere si potrebbero aggiungere all'esportazione di FIN-01 confrontando ricevimenti e fatture passive, dopo FIN-05 |
| FIN-24 | Note spese: invio, ricevute da mobile, approvazione, rimborso, riaddebito | Core | HAVE | addons/spese/riaddebito.py da_riaddebitare, fattura, movimenti_per; addons/spese/pagine.py riaddebiti, rimborso; addons/banca/abbina.py abbina_documento, candidati_uscita; addons/spese/tests/test_riaddebito.py | Fatto il 2026-11-08: cliente sulla riga di spesa e pagina «Da riaddebitare» che crea la fattura in bozza (le spese tornano libere se la fattura si annulla, si storna o si elimina); dal telefono il campo della ricevuta apre la fotocamera; il rimborso si abbina al movimento bancario in uscita che lo paga, proposto per importo e data. Non ci sono il progetto sulla riga (le note spese non dipendono da Progetti) né la lettura automatica degli scontrini (OCR in attesa) |
| FIN-25 | Link di pagamento e pagamento online delle fatture | Core | HAVE | Nessun provider nel codice (ricerca stripe, paypal, nexi, pagamento online senza risultati); addons/assistenza/portale.py non mostra fatture; MP23 PagoPA è solo un codice | Nulla di presente Fatto il 2026-11-06: modulo «pagamenti», «Paga ora» nel portale e da un link firmato per le email, Stripe Checkout, conferma al ritorno e con webhook firmato, incasso con incassa_fattura una volta sola. Dal 2026-11-09 il link entra da solo nelle email di invio, promemoria e sollecito. |
| FIN-26 | Blocco periodi e chiusura d'esercizio | Core | N/A | Nessun mastro; in addons/fatturazione/operazioni.py controlla impone solo l'ordine di date nella numerazione | Decisione utente 2026-11-03 per la chiusura. Resta utile, senza mastro, un blocco dei registri IVA per periodo già comunicato allo studio, oggi assente |
| FIN-27 | Riconoscimento ricavi (IFRS 15, ASC 606) | Adv | N/A | Nessun mastro | Dipende dal mastro, decisione utente 2026-11-03. Non serve esportazione oltre a quella di FIN-18 |
| FIN-28 | Abbonamenti: ricorrenza, consumo, pro-rata, cambi piano | Adv | PARTIAL | addons/ricorrenti/operazioni.py (giro, _crea_fattura, adegua, disdici, previsione, ricavi_mensili); addons/ricorrenti/models.py Canone; addons/commesse/operazioni.py monte_ore | Ricorrenza, rinnovi, disdette, ISTAT, MRR e previsione ci sono. Mancano fatturazione a consumo (il monte ore vale solo per i ticket), pro-rata e upgrade o downgrade datati: le righe si modificano e valgono dal periodo dopo. Periodi sempre interi |
| FIN-29 | FP&A: piani, modelli, allocazioni, versioni di forecast | Adv | PARTIAL | addons/ai/specialisti.py calcola_previsione; addons/grafici/motore.py _previsione; addons/ricorrenti/operazioni.py previsione | Esistono solo previsioni statistiche di serie e la proiezione dei canoni. Mancano piani, driver, allocazioni, versioni e scenari |
| FIN-30 | Consolidamento multi-azienda con elisioni e conversione | Adv | N/A | core.Azienda separa le società; nessun mastro | Dipende dal mastro, decisione utente 2026-11-03. Non serve esportazione dedicata: va allo studio |
| FIN-31 | Automazione delle operazioni tra aziende del gruppo | Adv | MISSING | addons/sdi/passive.py azienda_di riconosce il destinatario solo all'arrivo del file SDI; nessuna logica di specchio | Nulla da ordine a ordine o da fattura a fattura tra aziende della stessa installazione |
| FIN-32 | File di pagamento SEPA, SDD e RiBa | Adv | HAVE | Solo codici MP12, MP19-21 in addons/fiscale/models.py; addons/banca/abbina.py METODI li usa per etichettare l'incasso; nessun generatore pain o CBI | Nessun file bancario. Contatto non ha IBAN né mandati SDD; ScadenzaPassiva.iban è già disponibile. Nella decisione del 2026-11-03 questa parte è in ambito, appoggiata alle scadenze | Dal 2026-11-07 addons/distinte (sepa.py, riba.py, servizi.py).
| FIN-33 | Fatturazione elettronica: SDI, Peppol, attiva e passiva con stati | Adv | PARTIAL | addons/fatturazione/fatturapa.py genera; addons/sdi/validazione.py con XSD 1.2.2; addons/sdi/canali.py Manuale, Pec, Prova; addons/sdi/pec.py; addons/sdi/notifiche.py; addons/sdi/passive.py | SDI completo in entrata e in uscita con stati e scarti. Mancano Peppol, un canale API o intermediario (SDICoop fuori scope nella spec di fase 7), la fattura semplificata e la conservazione digitale a norma |
| FIN-34 | Finanziamenti, spese indeducibili, report ESG | Adv | MISSING | Nessun riscontro per mutuo, finanziamento, ESG | Nulla di presente. L'indeducibilità fiscale spetta allo studio; piani di ammortamento dei prestiti ed ESG si possono fare senza mastro |
| FIN-35 | Gestione della chiusura con checklist | Adv | N/A | addons/banca/pagine.py riconcilia copre solo la banca | La chiusura contabile dipende dal mastro, decisione utente 2026-11-03. Sarebbe utile una lista mensile di consegna allo studio, ottenibile con automazioni e FIN-01 |
| FIN-36 | OCR e AI su fatture e ricevute in bozza | Edge | MISSING | Nessun OCR (spec fase 6 lo esclude per i documenti); ai.models campo visione mai usato altrove; addons/sdi/views.py FatturaPassivaView has_add_permission False | Nessuna estrazione da PDF o foto. Le fatture SDI non ne hanno bisogno: resta il valore su ricevute e documenti cartacei o esteri, ma non esiste una bozza passiva manuale |
| FIN-37 | Abbinamento bancario AI che impara dallo storico | Edge | MISSING | addons/banca/abbina.py punteggi fissi (PUNTI_NUMERO ecc.); banca.Abbinamento conserva lo storico, non usato per imparare | Nulla di adattivo. Ada può leggere i dati ma non c'è logica di abbinamento in addons/ai |
| FIN-38 | Agente contabilità fornitori che prepara le fatture per l'approvazione | Edge | PARTIAL | addons/sdi/pec.py leggi_tutte e addons/sdi/passive.py importa creano le fatture da verificare; addons/ai/strumenti/scritture.py bottoni su conferma; addons/ai/proposte.py | L'arrivo automatico e la proposta generica del bottone Registra su conferma esistono. Manca un agente dedicato: nessun controllo su ordine, prezzi, duplicati o anomalie, nessuna coda di approvazione né gerarchia |

### Vendite, CRM e marketing (CRM)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| CRM-01 | Lead e opportunità con fasi, kanban, probabilità, valore atteso, motivi di perdita | Core | HAVE | addons/crm/models.py (FaseCrm, Opportunita.applica_fase, MotivoPerdita); addons/crm/views.py (OpportunitaView: kanban trascinabile, kanban_colonna col ponderato, segna_vinta, segna_persa, riapri, crea_contatto); addons/crm/tests/test_crm.py | Lead e opportunità sono un solo modello (campi nome_contatto, email, telefono), senza qualificazione separata; il motivo di perdita è suggerito ma non obbligatorio in segna_persa. Non bloccante. |
| CRM-02 | Attività (chiamate, riunioni, email) pianificate sui record con promemoria | Core | HAVE | core/attivita.py (pianifica, segna_fatta, promemoria); core/models.py (TipoAttivita, AttivitaPianificata); core/migrations/0012_tipi_attivita.py; core/viste/chatter.py; core/cron.py (promemoria alle 07:00); core/urls.py (attivita/) | La scadenza è una data senza ora e il promemoria è un riepilogo giornaliero; le attività non compaiono nel calendario. Limiti minori. |
| CRM-03 | Flusso lead, preventivo, ordine, consegna, fattura con documenti collegati | Core | HAVE | addons/vendite/operazioni.py (conferma, segnale ordine_confermato); addons/magazzino/collegamenti.py (consegna_da_ordine, origine_tipo/origine_id); addons/fatturazione/operazioni.py (da_ordine), models.py (Fattura.ordine); addons/magazzino/apps.py e addons/fatturazione/apps.py (sezioni sull'ordine) | Da preventivo a fattura il flusso è completo. Manca l'anello iniziale: Opportunita non ha alcun legame con OrdineVendita, nessun pulsante crea preventivo (il manifest crm dipende solo da contatti) e la vittoria non segue la conferma dell'ordine. da_ordine fattura tutto l'ordine in una volta, non per quantità consegnata. | **Fatto il 2026-11-07**: «Crea preventivo» sull'opportunità, preventivi e ordini collegati sulle due schede, opportunità vinta alla conferma dell'ordine. La fatturazione parziale per consegna c'è già con le fatture differite dai DDT.
| CRM-04 | Modelli di preventivo, prodotti opzionali, date di validità | Core | HAVE | addons/vendite/models.py (OrdineVendita.validita e clean); addons/vendite/operazioni.py (da_token: preventivo scaduto); addons/automazioni/catalogo.py (ordine.in_scadenza) | C'è solo la validità, con scadenza del link e promemoria. Mancano modelli di preventivo e righe opzionali: nessun modello o campo e la pagina online non permette scelte al cliente. Fatto il 2026-11-09: vendite.ModelloPreventivo, righe opzionali. |
| CRM-05 | Listini e regole di sconto per cliente, quantità, data, valuta | Core | HAVE | addons/prodotti/models.py (Listino, PrezzoListino.quantita_minima); addons/prodotti/prezzi.py (prezzo); addons/vendite/models.py (RigaVendita.sconto, OrdineVendita.listino) | Esistono listino scelto a mano sul documento, scaglioni per quantità e sconto manuale di riga. Mancano listino predefinito del cliente (nessun campo su Contatto), periodi di validità, regole di sconto (per categoria o cliente) e valuta: tutti gli importi sono in euro e la multivaluta è fuori scope nella spec fase 5. RigaCanone ignora i listini. Fatto il 2026-11-09: vendite.CondizioniCliente e RegolaSconto. |
| CRM-06 | Contatti: aziende e persone, più indirizzi, tag, gerarchia | Core | HAVE | addons/contatti/models.py (Contatto.tipo, societa, categorie, responsabile); addons/contatti/views.py; addons/contatti/validatori.py, vies.py; addons/contatti/templates (_persone.html) | Aziende, persone, gerarchia a un livello, categorie, VIES e dati fiscali ci sono. Manca il multi-indirizzo: un solo indirizzo sul contatto, quindi nessuna sede di consegna o fatturazione distinta su ordini e DDT. La gerarchia tra aziende (gruppo, filiale) è vietata da clean. | **Fatto il 2026-11-07**: indirizzi di consegna, fatturazione e sedi sul contatto, scelta sull'ordine e sulla consegna, luogo di destinazione sul DDT; società madre tra aziende. La FatturaPA resta con la sede legale dell'anagrafica.
| CRM-07 | Team di vendita, obiettivi, report pipeline e vinte/perse | Core | HAVE | addons/crm/views.py (graph per fase, commerciale, stato, mese); addons/crm/dashboard.py (kpi); addons/grafici/motore.py (KPI con obiettivo in opzioni) | C'è il report di pipeline per fase e commerciale con ponderato. Mancano modello di team (esiste solo in helpdesk), obiettivi di vendita per persona o periodo, tasso di vittoria e analisi per motivo di perdita (motivo_perdita non è tra le dimensioni del grafico). L'obiettivo di un KPI Analisi è un numero fisso del singolo grafico. Fatto il 2026-11-09: crm.TeamVendita, ObiettivoVendita, risultati.py. |
| CRM-08 | Sincronizzazione email su contatti e opportunità (IMAP, Gmail, Exchange) | Core | PARTIAL | core/chatter/entrata.py (ricevi, _abbina, leggi_casella, registra_gestore); core/chatter/email.py; core/viste/base.py (destinatari_esterni); addons/helpdesk/views.py | C'è una sola casella IMAP di sistema (IMAP_URL) che abbina le risposte tramite Message-ID o token, solo verso utenti e follower. OpportunitaView e ContattoView non definiscono destinatari_esterni, quindi lead e clienti non entrano nel filo e le email non abbinate non si legano per mittente; solo helpdesk registra un gestore. Mancano caselle per utente, OAuth Gmail/Microsoft Graph, email inviate dal client di posta. |
| CRM-09 | Portale clienti: preventivi, accetta/firma, ordini e fatture | Core | HAVE | addons/vendite/pagine.py (preventivo_online), operazioni.py (link, da_token, accetta, rifiuta), templates/vendite/online.html; addons/assistenza/portale.py (portale con solo ticket, progetti, guida) | L'accettazione del preventivo funziona bene ma da link firmato per singolo documento, senza account. Il portale con accesso non elenca preventivi, ordini o fatture: non esiste nessuna pagina del portale su quei modelli. Fatto il 2026-11-06: sezione «Preventivi e ordini» filtrata sul cliente, risposta al preventivo con operazioni.accetta dalla stessa pagina del link, PDF. |
| CRM-10 | Automazione marketing: campagne a gocce e trigger | Adv | PARTIAL | addons/automazioni/catalogo.py (eventi crm e vendite); addons/automazioni/motore.py (azioni email, attività, nota, assegna; controlla_tempo); addons/automazioni/ricette.py; addons/automazioni/models.py (Regola, Esecuzione) | Regole con trigger, condizioni ed email per singolo record, anche a tempo, con simulazione e storico. Non esistono sequenze multi-passo con attese e uscita, destinatari su lista o segmento, consenso e disiscrizione, metriche di apertura e clic. Il catalogo è volutamente chiuso e non ha eventi sui contatti. |
| CRM-11 | Segmentazione clienti: profilazione, ABC, tag, liste dinamiche | Adv | PARTIAL | addons/contatti/models.py (Categoria, cliente, fornitore, responsabile); addons/contatti/views.py (list_filter); addons/crm/models.py (EtichettaCrm); core/models.py (CampoPersonalizzato); core/viste/filtri.py, gruppi.py | Tag, filtri, raggruppamenti e campi personalizzati ci sono. Mancano filtri salvati o liste dinamiche riusabili (nessun modello in core/viste), classificazione ABC e segmenti calcolati su fatturato o attività. |
| CRM-12 | Email marketing, SMS, sondaggi, gestione eventi | Adv | MISSING | Cercati senza esito: campagn, newsletter, mailing, sms, sondagg, survey. Solo vicini: addons/helpdesk/models.py (Valutazione 1-5 sul ticket); addons/calendario/models.py (Evento interno); addons/discuss/modelli_wa.py (modelli WhatsApp inviati solo da un operatore) | Nessun invio massivo, SMS, costruttore di sondaggi o eventi con iscrizioni. La valutazione del ticket è solo un voto post-chiusura e l'Evento del calendario è un appuntamento interno. |
| CRM-13 | Prenotazione online di appuntamenti collegata ai calendari | Adv | MISSING | addons/calendario/models.py (solo Evento interno); addons/calendario/ics.py (inviti .ics); nessun prenotaz, booking o appointment nel codice | Il calendario ha inviti e promemoria ma nessuna disponibilità né pagina pubblica. Evento.contatti non riceve inviti: invia_inviti scrive solo agli utenti partecipanti. |
| CRM-14 | Punteggio predittivo dei lead | Adv | MISSING | addons/crm/models.py (solo priorita e probabilita manuali o da fase); addons/ai/specialisti.py (decidi) e addons/ai/strumenti/specialisti.py (classifica: strumento generico di Ada) | Nessun punteggio sul lead e nessun modello appreso dallo storico vinte/perse. Lo strumento classifica valuta un testo su richiesta e, se attivo il servizio url_decider, può essere un punto di partenza, ma non scrive nulla sull'opportunità. |
| CRM-15 | Provvigioni, quote e previsione delle vendite | Adv | PARTIAL | addons/crm/views.py (kanban_colonna: ponderato); addons/grafici/motore.py (_previsione, tipo PREVISIONE); addons/ai/specialisti.py (calcola_previsione); addons/ricorrenti/operazioni.py (previsione ricavi ricorrenti) | Esistono pipeline ponderata, previsione di una serie storica (solo con modulo AI e servizio url_forecast esterno) e previsione dei canoni. Mancano provvigioni (nessuna occorrenza), quote per venditore e previsione commerciale con categorie, periodi e rettifiche del responsabile. |
| CRM-16 | Firma elettronica su preventivi e contratti | Adv | PARTIAL | addons/vendite/operazioni.py (accetta, impronta); addons/vendite/models.py (risposta_nome, risposta_il, risposta_ip, risposta_impronta); addons/vendite/templates/vendite/online.html (nome più spunta) | Accettazione tracciata con nome, data, IP e impronta del contenuto, solo sui preventivi. Mancano tratto di firma, verifica del firmatario (OTP), PDF firmato con attestato conservato, sigillo o provider qualificato. Contratti (ricorrenti.Canone, assistenza.Contratto) e altri documenti non si firmano. |
| CRM-17 | Abbonamenti, noleggio, fedeltà, promozioni, gift card, coupon | Adv | PARTIAL | addons/ricorrenti/models.py (Canone, FatturaCanone, Adeguamento); addons/ricorrenti/operazioni.py (giro, disdici, _chiudi_o_rinnova, adegua); addons/ricorrenti/pagine.py (cruscotto MRR) | Gli abbonamenti sono completi: fatturazione periodica, rinnovo, disdetta, ISTAT, cruscotto. Non esiste nulla per noleggio, fedeltà, promozioni, gift card e coupon (nessuna occorrenza nel codice). |
| CRM-18 | Configuratore di prodotto / CPQ | Adv | MISSING | addons/prodotti/models.py (nessun attributo o variante); spec fase 5, Fuori scope: varianti di prodotto; nessuna occorrenza di configurator o variante | Nessun attributo, regola di compatibilità o prezzo configurato. L'esclusione esplicita riguarda le varianti, non il CPQ, quindi resta MISSING. |
| CRM-19 | Chat sul sito e moduli web-to-lead | Adv | HAVE | addons/crm/models.py ModuloWeb, Opportunita.origine; addons/crm/modulo_web.py invia, crea_lead; addons/crm/static/crm/modulo-web.js; addons/discuss/schede.py iniziali; addons/crm/tests/test_modulo_web.py | Fatto il 2026-11-08: modulo «contattaci» da incorporare con due righe, solo dai siti ammessi, con esca e limite per indirizzo; crea l'opportunità con origine, etichetta, contatto già in anagrafica, pagina e UTM, e un'attività al commerciale. Dalla chat del sito l'opportunità creata a mano parte con nome ed email del visitatore. La chat non crea ancora lead da sola |
| CRM-20 | Agente che prepara ordini dalle email dei clienti | Edge | PARTIAL | core/chatter/entrata.py (registra_gestore, usato solo da helpdesk); addons/ai/strumenti/scritture.py (crea_record con righe, proposta da confermare); addons/ai/strumenti/specialisti.py (classifica); addons/awf/eventi.py (record.assigned verso agenti) | I blocchi ci sono: email in entrata, Ada che propone un preventivo con righe e conferma umana. Manca il flusso: nessun gestore riconosce una richiesta d'ordine, individua cliente e prodotti, legge l'allegato e crea la bozza. |

### Acquisti (PUR)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| PUR-01 | Richieste d'offerta a più fornitori, confronto, ordini | Core | HAVE | addons/acquisti/models.py Gara, RigaGara; addons/acquisti/operazioni.py crea_offerte, invia_offerte, aggiudica, _chiudi_gara; addons/acquisti/templates/acquisti/_confronto.html | Fatto in questo lavoro. I prezzi offerti si scrivono sulle singole richieste; manca un portale dove li inserisca il fornitore (PUR-12). |
| PUR-02 | Listini fornitore, tempi di consegna, quantità minime, codici fornitore | Core | HAVE | addons/acquisti/models.py VoceListino; addons/acquisti/listini.py voce, minimo, scegli_fornitore; RigaAcquisto.save | Fatto in questo lavoro: codice fornitore, scaglioni, minimi, tempi di consegna, validità, preferito. Solo in euro (vedi PLT-02). |
| PUR-03 | Ricevimenti da ordine, fatture da ordine, riscontro a tre vie | Core | HAVE | addons/acquisti/riscontro.py riepilogo, collega, fattura_ricevuta, crea_residuo; addons/sdi/segnali.py; addons/acquisti/models.py FatturaOrdine | Fatto in questo lavoro. Il confronto con la fattura è per ordine, non per riga: le righe dell'XML non portano il prodotto. Lo scostamento si segnala ma non blocca la registrazione. |
| PUR-04 | Regole di approvazione per importo o categoria | Core | HAVE | addons/acquisti/models.py RegolaApprovazione, Approvazione; addons/acquisti/operazioni.py conferma, approva, rifiuta, puo_decidere | Fatto in questo lavoro: soglia e categoria, più livelli in ordine, chi compra non si approva, storico delle decisioni. Il superuser può approvare anche i propri ordini. |
| PUR-05 | Ordini aperti e contratti quadro con richiami | Core | HAVE | addons/acquisti/models.py ContrattoQuadro, RigaContratto; addons/acquisti/operazioni.py richiamo, residui_contratto, _controlla_contratto | Fatto in questo lavoro: prezzi concordati, residuo, periodo di validità, blocco oltre il residuo. |
| PUR-06 | Regole di riordino che generano richieste o ordini | Core | HAVE | addons/acquisti/riordino.py proposte, crea_richieste, automatico; addons/acquisti/models.py RegolaRiordino; cron in addons/acquisti/__manifest__.py | Fatto in questo lavoro. Il calcolo è sul totale dei magazzini, non per magazzino. Un ordine ricevuto in parte senza ricevimento del residuo aperto non conta come in arrivo. |
| PUR-07 | Anagrafica fornitore con pagamenti, banca e fisco | Core | HAVE | addons/acquisti/models.py CondizioniFornitore; addons/acquisti/operazioni.py applica_condizioni; addons/acquisti/templates/acquisti/_fornitore.html | Fatto in questo lavoro: pagamento, IVA, IBAN validato e giorni di consegna, proposti sugli ordini nuovi. |
| PUR-08 | Resi a fornitore e note di credito fornitore | Core | HAVE | addons/acquisti/riscontro.py crea_reso; addons/acquisti/views.py rendi; note di credito TD04 in riscontro.imponibile_con_segno | Fatto in questo lavoro: documento di reso con DDT e scarico, nota di credito che rientra nel riscontro. |
| PUR-09 | Costi accessori di acquisto ripartiti sul valore di magazzino | Adv | MISSING | addons/magazzino/models.py Movimento (nessun campo di costo); addons/magazzino/operazioni.py ricevi | Il magazzino non valorizza i movimenti: non c'è valore su cui ripartire trasporti e dazi. Registrazione contabile esclusa |
| PUR-10 | Triangolazione: il fornitore spedisce al cliente | Adv | MISSING | addons/magazzino/collegamenti.py consegna_da_ordine, ricevimento_da_ordine (flussi separati) | Vendita e acquisto non si collegano; nessun indirizzo di consegna a terzi sull'ordine al fornitore. Ogni bene venduto passa per una consegna che scarica il magazzino |
| PUR-11 | Conto lavoro in acquisto (invio componenti, rientro del finito) | Adv | MISSING | addons/magazzino/models.py Consegna.CAUSALI (nessuna causale conto lavoro), Magazzino | Nessun concetto di conto lavoro né di giacenza presso terzi |
| PUR-12 | Portale fornitori (conferma ordini, caricamento fatture) | Adv | MISSING | addons/assistenza/portale.py, addons/assistenza/models.py AccessoPortale (solo clienti e ticket); addons/vendite/operazioni.py accetta, rifiuta (accettazione preventivo cliente via token) | Nessun accesso per i fornitori. I due schemi esistenti (portale con utente esterno e link firmato) sono riutilizzabili. |
| PUR-13 | Valutazione fornitori (puntualità, qualità, prezzo) | Adv | PARTIAL | addons/acquisti/valutazione.py schede; addons/acquisti/templates/acquisti/valutazione.html | Fatto in questo lavoro: puntualità, completezza, giorni medi, resi, fatture coerenti. Manca una misura diretta del prezzo (es. confronto col listino o con altri fornitori) e i controlli qualità in ingresso (INV-18). |
| PUR-14 | Agente AI per approvazioni e proposte di riapprovvigionamento | Edge | PARTIAL | addons/ai/strumenti/viste.py, addons/ai/strumenti/scritture.py, addons/ai/proposte.py, addons/ai/pianificate.py nota_per_il_modello; addons/awf/squadre.py REPARTI (acquisti); addons/awf/mcp.py | Solo capacità generica: Ada legge le viste di acquisti e magazzino e propone con conferma di creare o confermare un ordine, e può girare pianificata. Nessuna logica dedicata di riordino né flusso di approvazione da assistere. Il reparto acquisti in AWF è solo un'etichetta: gli agenti arrivano da un catalogo esterno, non verificabile dal repository |

### Magazzino (INV)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| INV-01 | Anagrafica articolo: varianti, alternativi, barcode, codici fornitore e cliente | Core | PARTIAL | addons/prodotti/models.py Prodotto (codice, codice_barre, categoria); addons/prodotti/views.py search_fields | Un solo barcode, usato solo nella ricerca. Mancano varianti e attributi, alternativi, codici per fornitore e per cliente. Varianti fuori dall'ambito della fase 5 (specs/2026-10-28-adabox-hub-fase5-gestionale-design.md), senza esclusione a livello di prodotto |
| INV-02 | Unità di misura con categorie e conversioni; UM acquisto e vendita | Core | HAVE | addons/prodotti/models.py UnitaMisura (simbolo, nome), Prodotto.unita | Una sola UM per prodotto, senza categorie né fattori; le righe di acquisto, vendita e magazzino non hanno UM propria e la giacenza assume un'unica unità Fatto il 2026-11-09: prodotti.converti e quantita_base sulle righe. |
| INV-03 | Lotti e seriali con scadenze e tracciabilità | Core | HAVE | addons/magazzino/models.py Movimento, RigaConsegna, RigaRicevimento (nessun campo lotto o seriale) | Nessuna occorrenza funzionale: «lotto» nel codice indica solo pacchetti di dati in ai e sdi. Fuori dall'ambito della fase 5, senza esclusione a livello di prodotto | Dal 2026-11-07 addons/magazzino/lotti.py.
| INV-04 | Più magazzini con ubicazioni gerarchiche e scaffali | Core | HAVE | addons/magazzino/models.py Magazzino, Movimento.magazzino; addons/magazzino/pagine.py situazione (colonne per magazzino); addons/magazzino/collegamenti.py consegna_da_ordine (usa il predefinito) | Più magazzini piatti con giacenza per ciascuno. Mancano ubicazioni, gerarchia, scaffali e scelta del magazzino in base a regole. Ubicazioni multilivello fuori dall'ambito della fase 5, senza esclusione a livello di prodotto | Dal 2026-11-07 Ubicazione in addons/magazzino/models.py.
| INV-05 | Movimenti, trasferimenti interni, ricevimenti, consegne con stati | Core | HAVE | addons/magazzino/models.py Movimento, Consegna, Ricevimento; addons/magazzino/operazioni.py spedisci, ricevi; addons/magazzino/views.py MovimentoView (immutabile, solo rettifiche); addons/magazzino/collegamenti.py | Ricevimenti e consegne funzionano con stati bozza, fatto e annullato, DDT numerato e movimenti immutabili. Mancano trasferimenti tra magazzini (Movimento.TIPI non li ha), stati intermedi (pronto, in corso), evasioni parziali con residuo, storno di un documento già fatto; Ricevimento non ha nemmeno il bottone annulla Fatto il 2026-11-09: operazioni.segna_pronta, dividi, storna. |
| INV-06 | Liste di prelievo e documenti di imballaggio per evadere le vendite | Core | HAVE | addons/magazzino/templates/magazzino/report/ddt.html; addons/magazzino/models.py Consegna (colli, peso, aspetto_beni); addons/magazzino/collegamenti.py consegna_da_ordine | Il DDT con colli e peso fa da documento di trasporto. Mancano lista di prelievo con ubicazioni, conferma del prelevato, composizione dei colli e impegno della merce sull'ordine Fatto il 2026-11-09: addons/magazzino/prelievo.py. |
| INV-07 | Punti di riordino, min/max, proposte e giacenza prevista | Core | HAVE | addons/acquisti/riordino.py proposte; addons/magazzino/pagine.py situazione | Migliorata in questo lavoro: punto di riordino, obiettivo, proposte e giacenza prevista. Manca per magazzino; la pagina Giacenze non mostra ancora il previsto. Fatto il 2026-11-09: magazzino.ScortaMagazzino e colonne del previsto. |
| INV-08 | Inventari, conte cicliche e rettifiche | Core | HAVE | addons/magazzino/views.py MovimentoView (rettifica manuale con quantità e causale); addons/magazzino/hooks.py demo | Si rettifica solo inserendo a mano la differenza calcolata dall'utente. Mancano sessione di conta, foglio, quantità contata rispetto a teorica, generazione delle differenze, conte cicliche. Registrazione contabile esclusa per decisione dell'utente Fatto il 2026-11-09: addons/magazzino/inventari.py. |
| INV-09 | Metodi di valorizzazione (FIFO, medio, standard) con strati di costo | Core | HAVE | addons/magazzino/models.py Movimento (nessun campo costo); addons/prodotti/models.py Prodotto.costo; addons/magazzino/operazioni.py ricevi | Esiste solo il costo manuale del prodotto: non si aggiorna ai ricevimenti e i movimenti non hanno valore. Serve anche al commercialista per le rimanenze di fine anno | Dal 2026-11-07 addons/magazzino/costi.py.
| INV-10 | Report: disponibile, previsto, anzianità, storico movimenti, valore | Core | HAVE | addons/magazzino/pagine.py giacenze; addons/magazzino/views.py MovimentoView (raggruppamenti, somme); core/esporta.py; addons/grafici/motore.py | Giacenza attuale e storico movimenti con raggruppamenti ed esportazione ci sono. Mancano giacenza a una data passata, previsto, anzianità e valore Fatto il 2026-11-09: pagine giacenze (data, CSV) e anzianità. |
| INV-11 | Lettura barcode nei flussi di magazzino | Core | HAVE | addons/prodotti/models.py Prodotto.codice_barre; addons/prodotti/views.py search_fields (unico uso) | Il barcode si salva e si cerca; nessuna pagina di lettura per ricevimenti, prelievi, conte o trasferimenti e nessun uso di fotocamera o lettore Fatto il 2026-11-09: addons/magazzino/lettura.py. |
| INV-12 | Resi clienti (RMA) con rientro a magazzino e rimborso | Core | HAVE | addons/fatturazione/operazioni.py nota_di_credito, da_rimborsare; addons/magazzino/views.py MovimentoView; addons/magazzino/models.py Ricevimento (fornitore obbligatorio) | Nota di credito e rimborso ci sono lato fatture; il rientro merce si fa solo con rettifica manuale o forzando un ricevimento. Manca un documento di reso che leghi autorizzazione, DDT, rientro, ispezione e nota di credito Fatto il 2026-11-09: addons/magazzino/resi.py. |
| INV-13 | Imballi e kit (prodotti composti) | Core | HAVE | addons/prodotti/models.py Prodotto; addons/magazzino/models.py Consegna.colli, aspetto_beni (testo sul DDT) | Nessuna definizione di confezione né di kit; colli e aspetto sono solo dati del singolo DDT Fatto il 2026-11-09: prodotti.Confezione e ComponenteKit, esplosione in magazzino.operazioni.spedisci. |
| INV-14 | Strategie di stoccaggio e prelievo (FIFO, FEFO, LIFO, per rotazione) | Adv | MISSING | addons/magazzino/operazioni.py spedisci (scarico senza scelta) | Senza lotti e ubicazioni non c'è nulla da scegliere |
| INV-15 | Percorsi a più passi, prelievo a ondate e a gruppi | Adv | MISSING | addons/magazzino/operazioni.py spedisci (un passo unico) | Un solo passaggio da bozza a spedito |
| INV-16 | Integrazione corrieri: tariffe, etichette, tracciamento | Adv | MISSING | addons/magazzino/models.py Consegna.vettore (testo libero) | Il vettore è testo sul DDT: nessuna integrazione, etichetta o numero di tracciamento |
| INV-17 | Prenotazione spedizioni con colli e modelli; viaggi e percorsi | Adv | MISSING | addons/magazzino/models.py Consegna (colli, peso, trasporto_a_cura) | Solo dati descrittivi sul DDT; nessuna spedizione come oggetto, modello di collo, viaggio o percorso |
| INV-18 | Controlli qualità (ricevimento, consegna, processo) con quarantena | Adv | MISSING | addons/qualita/models.py Ambiente, CasoTest, Collaudo (collaudo di software legato a progetti); addons/magazzino/operazioni.py ricevi | L'app qualita è per i collaudi software, non controlla merce: Collaudo è legato a progetti.Progetto. La ricezione carica subito, senza controllo né quarantena |
| INV-19 | Conto deposito, cross-docking, funzioni 3PL e WMS | Adv | MISSING | addons/magazzino/models.py Consegna.CAUSALI (conto_visione, solo testo sul DDT) | Il conto visione è una causale di stampa: la merce esce dalla giacenza e non viene tracciata presso il cliente. Nessuna proprietà della merce né cross-docking |
| INV-20 | Previsione della domanda e riapprovvigionamento predittivo | Adv | PARTIAL | addons/ai/specialisti.py calcola_previsione, serie_storica, prevedi; addons/grafici/motore.py _previsione; addons/ai/__manifest__.py url_forecast | Il servizio di previsione lavora su qualunque vista (es. scarichi di magazzino per mese) dal chat o in Analisi, ma serve un servizio esterno e il modulo AI. Il risultato è un grafico: nessuna previsione per articolo in serie né legame con scorte e riordino |
| INV-21 | Agente AI per il riapprovvigionamento | Edge | PARTIAL | addons/ai/strumenti/viste.py, addons/ai/strumenti/scritture.py, addons/ai/strumenti/specialisti.py, addons/ai/pianificate.py | Solo combinazione generica: Ada legge i movimenti, prevede, propone ordini con conferma e può girare pianificata su istruzione dell'utente. Nessuna logica dedicata né memoria di decisioni di riordino |

### Produzione (MFG)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| MFG-01 | Distinte base multilivello con versioni e alternative | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione»; docs/superpowers/specs/2026-10-28-adabox-hub-fase5-gestionale-design.md «Fuori scope» (produzione) | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort L |
| MFG-02 | Cicli, centri di lavoro, operazioni con tempi standard | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort M |
| MFG-03 | Ordini di produzione: consumi, sottoprodotti, scarti, consumo a consuntivo | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione»; addons/magazzino/models.py Movimento (riutilizzabile, nessun tipo produzione) | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort L |
| MFG-04 | Fasi di lavoro con tempi di avvio e fine per operazione | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione»; addons/timesheet (ore su progetti, non su operazioni) | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort M |
| MFG-05 | MRP: fabbisogni da vendite e previsioni, generazione di acquisti e produzione | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Il riordino sul solo lato acquisti resta in PUR-06 e INV-07. Se l'esclusione cade: MISSING, effort L |
| MFG-06 | Costo di produzione (standard e reale, manodopera e costi indiretti) | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione»; addons/commesse/models.py CostoOrario (costo orario delle persone sui progetti, riutilizzabile) | Nessun codice per la produzione. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort L |
| MFG-07 | Ordini di disassemblaggio | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort S |
| MFG-08 | Pianificazione della capacità per centro di lavoro | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione»; addons/capacita/models.py Capacita (ore delle persone sui compiti, non centri di lavoro) | L'app capacita copre le persone sui progetti, non le macchine. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort M |
| MFG-09 | Conto lavoro di produzione con tracciamento dei materiali | Core | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Il lato acquisti è in PUR-11. Se l'esclusione cade: MISSING, effort L |
| MFG-10 | Piano principale di produzione (MPS) | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort M |
| MFG-11 | Terminale di reparto su tablet con stato in tempo reale | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort M |
| MFG-12 | Controlli qualità dentro le fasi di lavoro | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort S |
| MFG-13 | Manutenzione preventiva e correttiva delle attrezzature | Adv | MISSING | addons/ricorrenti/models.py Canone e addons/assistenza/models.py Contratto (manutenzione come servizio venduto ai clienti, non su attrezzature) | Nessun modello di attrezzatura o piano di manutenzione. Non rientra nell'esclusione della produzione: vale anche senza fabbrica, salvo il legame con i centri di lavoro |
| MFG-14 | Gestione del ciclo di vita e modifiche tecniche sulle distinte | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort M |
| MFG-15 | Produzione di processo (formule, lotti, rese) | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort L |
| MFG-16 | Integrazione IoT (bilance, stampanti, sensori, PLC) | Adv | MISSING | core/lavori.py e core/api (nessun connettore verso dispositivi) | Nessun collegamento a dispositivi. Non rientra nell'esclusione della produzione: bilance e stampanti di etichette servono anche in magazzino |
| MFG-17 | Report di costi e scostamenti di produzione | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort M |
| MFG-18 | Pianificazione della produzione assistita dall'AI | Edge | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md «Non previsti: ... produzione» | Nessun codice. Esclusa dalla documentazione. Se l'esclusione cade: MISSING, effort L |

### Persone e paghe (HR)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| HR-01 | Anagrafica dipendenti, organigramma, reparti, posizioni | Core | HAVE | addons/personale/models.py Posizione, Dipendente.posizione; addons/personale/organigramma.py albero, scoperte; addons/personale/pagine.py organigramma; addons/personale/tests/test_personale.py | Fatto il 2026-11-08: anagrafica delle posizioni con reparto e organico previsto (le posizioni nascono dai ruoli già scritti), pagina Organigramma disegnata dalla catena dei responsabili, filtrabile per reparto, con le posizioni da coprire; giri nella catena bloccati nel form e tollerati nella pagina |
| HR-02 | Contratti con struttura retributiva e storico | Core | HAVE | addons/personale/models.py (Dipendente.tipo_contratto, ore_settimanali, data_assunzione, data_cessazione), addons/commesse/models.py (CostoOrario con validità dal) | Il contratto è solo un paio di campi sul dipendente: lo storico è il tracciamento nel chatter. Mancano modello Contratto con date e livello, retribuzione, elementi della paga, avvisi di scadenza e rinnovo. CostoOrario è un costo industriale per le commesse, legato all'utente e non al contratto. Fatto il 2026-11-09: personale.ContrattoLavoro. |
| HR-03 | Presenze (timbratura, chiosco) e assenze con maturazione e approvazione | Core | HAVE | addons/personale/presenze.py (riconosci, timbra, giornata, mese, riepilogo, esporta); addons/personale/models.py Timbratura, Dipendente.badge e PIN; addons/personale/pagine.py chiosco, timbra_io, presenze_mese; addons/personale/saldi.py maturate, riporto; addons/personale/tests/test_presenze.py | Fatto il 2026-11-08: chiosco con badge o PIN (PIN unico per azienda, conservato come impronta, blocco dopo 5 errori) che propone entrata o uscita; timbratura dal web e da «In tasca»; correzioni a mano con motivo e autore; presenze del mese per dipendente con ore lavorate, previste dal calendario (festività comprese), assenze approvate e anomalie (uscita mancante, giorno senza timbrature); export Excel per il consulente del lavoro; saldi con ratei mensili maturati e riporto del residuo all'anno dopo, dall'anno scelto nelle impostazioni. Mancano turni pianificati (HR-13) e contratti (HR-02) |
| HR-04 | Timesheet su progetti e compiti | Core | HAVE | addons/timesheet/models.py (RigaOre, Cronometro), addons/timesheet/pagine.py (settimana, cronometro_avvia, cronometro_ferma), addons/timesheet/views.py (RigaOreView: approva, riapri, analisi) | Griglia settimanale, cronometro con arrotondamento, approvazione, blocco delle ore fatturate, controllo delle 24 ore. |
| HR-05 | Note spese con approvazione e rimborso | Core | HAVE | addons/spese/models.py (NotaSpese, RigaSpesa, CategoriaSpesa), addons/spese/flusso.py (invia, decidi, rimborsa), addons/spese/views.py (NotaView, stampa), addons/spese/pagine.py (ricevuta) | Flusso bozza, inviata, approvata o rifiutata, rimborsata con limiti, ricevuta obbligatoria e rimborso km. Il rimborso è una marcatura con data: non genera un bonifico né un movimento in addons/banca. Il riaddebito al cliente è valutato in PRJ-12. |
| HR-06 | Selezione del personale, inserimento e uscita con checklist | Core | N/A | Nessun modello; addons/personale/models.py non ha candidati; docs/superpowers/specs/2026-10-28-adabox-hub-fase7-sdi-personale-spese-design.md (Fuori scope: recruiting) | Esclusa per scelta dell'utente il 2026-11-05: la selezione del personale resta fuori dal prodotto. |
| HR-07 | Valutazioni delle prestazioni | Core | N/A | Nessun modello; fase7-sdi-personale-spese-design.md (Fuori scope: valutazioni) | Esclusa per scelta dell'utente il 2026-11-05: le valutazioni restano fuori dal prodotto. |
| HR-08 | Portale self-service del dipendente (cedolini, assenze, spese, documenti) | Core | PARTIAL | addons/personale/pagine.py (mie), addons/personale/templates/personale/mie.html, addons/spese/views.py (NotaView.get_queryset, _mio), addons/documenti/models.py (Spazio personale) | Il dipendente chiede ferie, vede il saldo e gestisce le sue note spese, ma da pagine separate nella UI interna. Mancano cedolini, documenti del rapporto di lavoro (Spazio personale è un'area file, non i documenti dati dall'azienda), modifica dei propri dati e una pagina unica. |
| HR-09 | Paghe con regole nazionali, cedolini, scritture contabili | Adv | N/A | Nessun modello; fase7-sdi-personale-spese-design.md (Fuori scope: paghe e cedolini) | Esclusa per scelta dell'utente il 2026-11-05: le paghe restano al consulente del lavoro. Le presenze gli arrivano con l'esportazione di HR-03. |
| HR-10 | Competenze, formazione online, certificazioni | Adv | MISSING | Nessun modello; ricerca su competenz, skill, certificaz, e-learning senza esiti in addons/personale, addons/capacita, addons/assistenza | Nulla sulle persone. addons/capacita/piano.py e addons/assistenza/instradamento.py assegnano senza considerare le competenze. |
| HR-11 | Obiettivi e riconoscimenti | Adv | MISSING | Nessun modello; progetti.Sprint.obiettivo è solo un testo dello sprint | Nulla per le persone: nessun obiettivo misurabile né riconoscimento. |
| HR-12 | Parco auto (veicoli, contratti, costi) | Adv | MISSING | Nessun modello; addons/spese/models.py (CategoriaSpesa.tariffa_km) copre solo il rimborso chilometrico | Nessuna anagrafica veicoli, assegnazione, contratti, scadenze o costi. |
| HR-13 | Pianificazione dei turni | Adv | MISSING | Nessun modello; addons/capacita/models.py (Capacita) dà solo ore al giorno e sabato o domenica lavorati | Nessun turno, modello di turno, copertura per reparto né pubblicazione. capacita calcola date dei compiti, non chi lavora quando. |
| HR-14 | Reception e gestione visitatori | Adv | HAVE | addons/reception (models.py Visita; servizi.py entra, esce, cancella_vecchie; pagine.py chiosco, presenti; tests/test_reception.py) | Fatto il 2026-11-08: chiosco per il tablet all'ingresso (nome, azienda, chi si incontra, informativa da accettare; uscita toccando il proprio nome, che mostra solo nome e iniziale), visite attese registrabili in anticipo, avviso a chi riceve per email e nella posta di Discuss tramite il chatter, lista dei presenti da stampare per l'evacuazione, cancellazione automatica dopo i giorni di conservazione. Niente stampa di badge né firma sul tablet |
| HR-15 | Programmi di segnalazione candidati | Adv | N/A | Nessun modello | Esclusa il 2026-11-05 insieme alla selezione, su cui si appoggia. |
| HR-16 | Agente note spese (codifica automatica e controlli sulle ricevute) | Edge | MISSING | Controlli solo deterministici in addons/spese/models.py (RigaSpesa.clean) e addons/spese/flusso.py (controlla); nessun riferimento a NotaSpese o ricevute in addons/ai; il manifest di spese non ha la chiave ai (esempio in addons/calendario/ai.py) | La ricevuta non viene letta: niente estrazione di importo e data, categoria proposta, né controlli di policy sul contenuto. Il modulo addons/ai offre i mattoni (gateway, strumenti, compiti). |

### Progetti, servizio e assistenza (PRJ)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| PRJ-01 | Progetti e compiti con kanban, Gantt, milestone, dipendenze, sottocompiti | Core | HAVE | addons/progetti/models.py (Progetto, Compito.padre, Compito.bloccato_da, crea_ciclo, Milestone, Sprint), addons/progetti/views.py (CompitoView: kanban, kanban_vietato, completa), addons/capacita/pagine.py (gantt) | Tutto presente. Il Gantt sta in capacita, è di sola lettura (derivato dal piano, 16 settimane) e mostra solo compiti con stima e assegnatario: nessun trascinamento né milestone sul diagramma. |
| PRJ-02 | Ore sui compiti e fatturazione progetto (corpo, ore, milestone) | Core | HAVE | addons/commesse/models.py (Condizioni.TIPI, TariffaPersona, OreFatturate), addons/commesse/operazioni.py (da_fatturare, fattura_ore, fattura_corpo), addons/commesse/pagine.py (da_fatturare) | Ore e a corpo funzionano, con tariffe per persona, monte ore e sblocco allo storno. Manca la fatturazione per milestone o SAL: Condizioni ha solo ore, corpo e nessuna, nessun riferimento a Milestone in commesse, e fattura_corpo emette ogni volta l'intero importo senza tranche, acconti né protezione dal doppio addebito. Fatto il 2026-11-09: commesse.Tappa, fattura_corpo con acconti. |
| PRJ-03 | Redditività di progetto (ricavi e costi, budget) | Core | HAVE | addons/commesse/operazioni.py (redditivita), addons/commesse/templates/commesse/_progetto.html, addons/progetti/models.py (Progetto.budget_ore, budget), addons/progetti/segnali.py (controlla_budget) | Ricavi, costo delle ore e margine visibili sul progetto, con avvisi all'80 e al 100% delle ore. I costi contano solo le ore: mancano note spese, acquisti e materiali. Il budget è solo in ore, non in euro né per voce, e non c'è un confronto economico preventivo e consuntivo né vista su più progetti. Fatto il 2026-11-09: commesse.costi_analitica, budget_progetto, portafoglio. |
| PRJ-04 | Ticket: team, fasi, politiche SLA configurabili, da email a ticket | Core | HAVE | addons/helpdesk/models.py (Team, FaseTicket, Ticket), addons/helpdesk/email.py (apri_ticket), core/chatter/entrata.py (leggi_casella), addons/helpdesk/lavori.py (avvisi_sla), addons/assistenza/models.py (PoliticaSLA, Contratto), addons/assistenza/sla.py, addons/assistenza/instradamento.py (meno_carico) | Completo. Limiti minori: un solo indirizzo di helpdesk per istanza, il team di default è il primo, nessuna pausa dell'SLA in attesa del cliente; due livelli di SLA (parametri per priorità di helpdesk, politiche per contratto di assistenza). |
| PRJ-05 | Base di conoscenza e wiki interna | Core | PARTIAL | addons/helpdesk/models.py (Articolo, CategoriaArticolo), addons/helpdesk/guida.py (cerca), addons/helpdesk/views.py (ArticoloView), addons/assistenza/portale.py (guida), addons/documenti/models.py (Versione, per i file) | La guida per i clienti funziona: categorie, ricerca, pubblicazione, visite, voti. Manca la wiki interna: l'articolo non pubblicato è una Bozza, non c'è visibilità solo interna per reparto o spazio, né gerarchia di pagine, testo ricco (corpo reso con linebreaks), versioni o collegamenti tra pagine. |
| PRJ-06 | Portale clienti per ticket e avanzamento progetti | Core | HAVE | addons/assistenza/portale.py (home, dettaglio, nuovo, progetti, _monte_ore), addons/assistenza/templates/assistenza/portale/progetti.html, addons/assistenza/models.py (AccessoPortale) | Ticket completi: apertura, conversazione, allegati, monte ore, guida. L'avanzamento progetti è assente: la pagina mostra solo nome, stato, fine prevista e richieste aperte, senza percentuale, compiti, milestone o rilasci, e il progetto non ha pagina di dettaglio. | **Fatto il 2026-11-07**: pagina del progetto nel portale con avanzamento, tappe, rilasci, richieste del cliente e i soli compiti segnati «visibile al cliente».
| PRJ-07 | Pianificazione di risorse e capacità | Adv | HAVE | addons/capacita/piano.py (Calendario, calcola, carico, consegna), addons/capacita/pagine.py (consegne, carico, gantt, simula), addons/capacita/models.py (Capacita) | Piano ricalcolato da stime, dipendenze, assenze approvate e festività, con carico per persona e simulazioni. Non tiene conto delle competenze (HR-10) e non fa assegnazione automatica. |
| PRJ-08 | Assistenza sul campo: pianificazione, ordini di servizio, riparazioni, contratti, garanzie, articoli in assistenza, listini servizi | Adv | PARTIAL | addons/assistenza/models.py (Contratto, PoliticaSLA, monte ore), addons/ricorrenti/operazioni.py (canoni, rinnovi, ISTAT) | Esistono solo i contratti di servizio (SLA, monte ore, canoni ricorrenti). Mancano ordini di intervento, pianificazione e assegnazione dei tecnici, app in mobilità, rapportino firmato, articoli in assistenza, listini dei servizi, materiali usati e fattura da intervento. |
| PRJ-09 | Gestione delle garanzie | Adv | MISSING | Nessun modello; ricerca su garanzi e warrant senza esiti in addons | Nessuna data di garanzia, condizione o pratica di garanzia, e manca il numero di serie su cui appoggiarle (rimandato in fase 5). |
| PRJ-10 | Manutenzione di attrezzature proprie e dei clienti | Adv | MISSING | Nessun modello; manutenzione compare solo come nome di contratto in addons/ricorrenti/models.py | Nessuna anagrafica di attrezzature o impianti, piani preventivi o richieste di manutenzione. |
| PRJ-11 | Riparazioni (preventivo, ricambi, manodopera) | Adv | MISSING | Solo la causale riparazione in addons/magazzino/models.py (Consegna.CAUSALI), senza alcun flusso | Nessun ordine di riparazione né preventivo, ricambi o manodopera collegati. |
| PRJ-12 | PSA completa: utilizzo risorse, riconoscimento ricavi di progetto, riaddebito spese | Adv | PARTIAL | addons/capacita/piano.py (carico), addons/timesheet/models.py (RigaOre.fatturabile), addons/commesse/operazioni.py (redditivita) | Carico pianificato per persona, flag fatturabile e margine ci sono. Mancano il tasso di utilizzo consuntivo (ore fatturabili su ore disponibili), il riconoscimento dei ricavi per avanzamento e il riaddebito: addons/spese non ha collegamento a progetto o cliente né a fatturazione. |
| PRJ-13 | Appuntamenti e prenotazioni | Adv | PARTIAL | addons/calendario/models.py (Evento), addons/calendario/lavori.py (invia_inviti, promemoria), addons/calendario/ics.py, addons/calendario/views.py | Eventi interni con inviti, promemoria e file .ics funzionano. Manca la prenotazione da parte del cliente: pagina pubblica, disponibilità e fasce, risorse prenotabili, conferma e cancellazione; nessuna sincronizzazione con calendari esterni. |

### Commercio e front office (COM)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| COM-01 | Portale clienti: fatture, ordini, preventivi, ticket, documenti | Core | HAVE | addons/assistenza/portale.py (home, dettaglio, nuovo, progetti, guida, invita); addons/assistenza/models.py (AccessoPortale); addons/assistenza/urls.py; core/middleware.py (esterno, PORTALE_PERCORSI); addons/documenti/condivisioni.py (link senza login) | Il portale copre solo ticket, progetti, monte ore e guida. Mancano fatture, ordini, preventivi e documenti. È anche dentro assistenza, che dipende da helpdesk e progetti: chi non ha quei moduli non ha alcun portale. Fatto il 2026-11-06: modulo «portale» con sezioni registrate dalle app (vendite, fatturazione, assistenza), accessi e inviti spostati dall'assistenza con migrazione dei dati, indirizzi aperti ai clienti registrati dalle app. Mancano i documenti condivisi nel portale. |
| COM-02 | Pagamenti online con più gateway | Core | HAVE | Nessuna occorrenza di stripe, paypal, mollie, satispay, nexi, adyen, checkout; addons/fiscale/models.py cita pagoPA solo come modalità di pagamento dell'XML; addons/fatturazione/pagine.py (incasso manuale); addons/banca (riconciliazione a posteriori) | Gli incassi si registrano a mano o dagli estratti conto. Nessun link di pagamento, gateway o webhook di esito. Parziale dal 2026-11-06: interfaccia dei fornitori con Stripe e un fornitore simulato per prove e demo; un secondo fornitore reale (PayPal, Nexi) si aggiunge in pagamenti/fornitori.py. Fatto il 2026-11-09: PayPal come secondo fornitore reale. |
| COM-03 | eCommerce integrato con giacenze, prezzi e contabilità | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md: Non previsti, website ed eCommerce (esiste sito_adabox); docs/superpowers/specs/2026-10-28-adabox-hub-fase5-gestionale-design.md: Fuori scope, e-commerce | Escluso dalle spec. Da riconfermare: la stessa lista fuori scope della fase 5 citava HR e SDI, poi realizzati in fase 7. |
| COM-04 | Costruttore di siti / CMS con pagine, blog, moduli | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md: Non previsti, website (esiste sito_adabox, esterno a questo repository) | Escluso dalle spec. La chat e il widget si incorporano in siti esterni tramite script: restano la via prevista. |
| COM-05 | Punto vendita retail (offline, scontrini, cassa) | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md: Non previsti, POS; docs/superpowers/specs/2026-10-28-adabox-hub-fase5-gestionale-design.md: Fuori scope, POS | Escluso dalle spec; nessun codice su scontrini o corrispettivi. Da riconfermare come COM-03. |
| COM-06 | Punto vendita ristorazione (tavoli, cucina, conti divisi) | Adv | N/A | Stesse esclusioni POS: spec fase 1 e spec fase 5 | Escluso dalle spec insieme al POS; nessun codice su tavoli o comande. |
| COM-07 | Fedeltà, gift card, promozioni in POS ed eCommerce | Adv | MISSING | Nessuna occorrenza di fedelt, loyalty, gift, coupon, promozion | Non escluso esplicitamente, ma i canali di cui parla sono fuori scope: ha senso solo se si riaprono COM-03 o COM-05, oppure limitato alla vendita tradizionale (CRM-17). |
| COM-08 | Connettori marketplace e piattaforme (Shopify, Amazon, POS terzi, logistica) | Adv | MISSING | Nessuna occorrenza di shopify, amazon, woocommerce; addons/magazzino/models.py (Consegna.vettore è testo libero); addons/discuss/connettori.py (solo messaggistica); core/api (API con token, base possibile) | Nessun connettore commerciale né integrazione con corrieri: niente tracking, etichette o sincronizzazione di ordini e giacenze. |
| COM-09 | Gestione self-service di account e abbonamenti | Adv | PARTIAL | addons/ricorrenti/operazioni.py (disdici, revoca_disdetta, termine_disdetta); addons/assistenza/portale.py (invita, link_password; nessuna pagina account); core/applicazioni.py e addons/rivendita (richieste moduli, solo per la vendita di adabox stessa) | La logica degli abbonamenti esiste solo lato interno. Il cliente non vede i suoi canoni né può disdire o aggiornare dati e carta dal portale; ha solo la scelta della password. Le pagine Applicazioni e Rivendita riguardano le licenze adabox, non i clienti dell'azienda. |
| COM-10 | Chat dal vivo e accesso con account social | Adv | HAVE | addons/portale/oidc.py (PKCE, verifica RS256 dell'id_token); addons/portale/accesso_social.py; addons/portale/models.py ProviderAccesso, IdentitaEsterna; addons/portale/tests/test_accesso_social.py | Fatto il 2026-11-08: «Accedi con Google» e «Accedi con Microsoft» per i clienti del portale, solo se già invitati con quella email (nessuna registrazione aperta, niente utenti interni); Google collega subito se l'email è verificata, Microsoft dopo la conferma via email; verifica in due passaggi rispettata; segreto cifrato. Provato contro un servizio OIDC simulato: manca la prova con app vere registrate su Google e Microsoft |
| COM-11 | Noleggio e biglietteria eventi | Adv | MISSING | Nessuna occorrenza di noleggio, rental, biglietti; addons/calendario/models.py (solo appuntamenti interni); addons/ricorrenti (canoni, non beni fisici) | Nessuna disponibilità di beni nel tempo, cauzioni, rientri, posti o biglietti. |

### Report e analisi (RPT)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| RPT-01 | Dashboard con KPI per modulo e per ruolo | Core | HAVE | core/dashboard.py layout_di, layout_del_ruolo; core/models.py Ruolo.dashboard; core/views.py dashboard_per_ruolo; addons/grafici/motore.py condivise, a_chi; addons/grafici/models.py Pagina.ruoli, Pagina.gruppi; addons/grafici/tests/test_condivisione_ruoli.py | Fatto il 2026-11-08: una pagina di Analisi si condivide con nessuno, con tutta l'azienda o con alcuni ruoli e gruppi; l'amministratore fa della sua dashboard quella di partenza di un ruolo, da cui parte chi ha quel ruolo e non l'ha ancora disposta (Ripristina ci torna). I dati seguono sempre i permessi di chi guarda |
| RPT-02 | Viste pivot e grafico su ogni insieme di record, con raggruppamenti e misure | Core | HAVE | core/viste/pivot.py; core/viste/interroga.py opzioni_vista; core/viste/grafico.py; addons/grafici/costruttore.py | Fatto il 2026-11-05: Pivot generica con righe, colonne e fino a tre misure, sui filtri della lista, esportabile in Excel. Non si salva ancora come widget di Analisi e le celle non aprono i record. |
| RPT-03 | Ricerche e filtri salvati e condivisi tra utenti | Core | HAVE | core/viste/salvate.py; core/models.py RicercaSalvata; core/tests/test_ricerche_pivot_registro.py | Fatto il 2026-11-05: ricerche salvate per lista, personali o condivise con l'azienda, con quella che si apre da sola. La condivisione è con tutta l'azienda, non per ruolo. |
| RPT-04 | Bilanci e prospetti finanziari con drill-down alle registrazioni | Core | N/A | Decisione dell'utente del 2026-11-03 (memoria contabilita-al-commercialista); addons/rivendita/schede.py (Banca: senza contabilità) | Fuori perimetro per decisione dell'utente: niente libro mastro in adabox-hub, la contabilità resta al commercialista. Al massimo un'esportazione per lo studio |
| RPT-05 | Esportazione in Excel e CSV da ogni lista | Core | HAVE | core/esporta.py (csv_bytes, xlsx_bytes, in_background); core/viste/esporta.py (EsportaView: filtrate o selezionate, grandi nel worker con link per email); core/viste/base.py (rotta per ogni ModelView); core/templates/core/vista/lista.html e _tabella.html | Copre tutte le liste ModelView. Le pagine su misura (giacenze in addons/magazzino/pagine.py, riconciliazione in addons/banca/pagine.py) non hanno esportazione |
| RPT-06 | Report pianificati e inviati per email | Core | HAVE | core/report_pianificati.py (esegui, esegui_dovuti, prossimo, registra_tipo); core/models.py ReportPianificato; addons/grafici/stampa.py; core/tests/test_report_pianificati.py | Fatto il 2026-11-08: dal menu «Dati» di ogni lista («Invia per email periodicamente…») o dal menu di una pagina di Analisi si pianifica l'invio ogni giorno, settimana o mese a un'ora scelta, a più destinatari: la lista con i filtri del momento in Excel o CSV, la pagina di Analisi in PDF con grafici, KPI e tabelle. Gira nel worker ogni 15 minuti con i permessi del proprietario (regole per ruolo comprese); esito registrato, errori al proprietario, «Invia ora» per provare. Provato col PDF vero |
| RPT-07 | Designer di report con layout personalizzati e report SQL o su dataset | Adv | PARTIAL | addons/grafici/costruttore.py (query guidata per grafici e KPI); core/report.py e core/viste/base.py (reports: template fissi nel codice); addons/studio/campi.py (solo colonne, filtri, form, etichette) | Il costruttore produce grafici e KPI, non report tabellari impaginati. Le stampe PDF sono template Django scritti dagli sviluppatori e Studio non le tocca. Nessun SQL personalizzato né dataset con join |
| RPT-08 | Foglio di calcolo integrato con collegamenti vivi ai dati | Adv | MISSING | Nessun riscontro; core/importa.py e core/esporta.py trattano solo file Excel; addons/ai/conoscenza.py estrae solo testo | Nessun foglio nell'interfaccia e nessuna formula o cella legata ai dati |
| RPT-09 | Connettori BI (Power BI, Looker, Metabase) e dataset o cartelle di analisi | Adv | PARTIAL | core/api/modelli.py (lista paginata con token); core/api/auth.py; addons/grafici/pagine.py (grafico_csv); addons/grafici/motore.py (csv_di) | Un BI può leggere solo l'API REST, una vista per volta, al massimo 200 righe a pagina, sulle 22 viste con api=True, oppure scaricare CSV. Nessun connettore, endpoint OData o SQL di sola lettura, dataset documentato o incrementale |
| RPT-10 | Esportazione verso data warehouse o replica in lettura | Adv | MISSING | config/settings.py (un solo database, nessun router); core/backup.py (solo backup sqlite o pg_dump) | Nessuna replica, nessun router di lettura, nessuna esportazione incrementale. Il backup non è un flusso analitico |
| RPT-11 | Sintesi narrative AI dei report | Edge | HAVE | addons/grafici/motore.py (contesto_ada); addons/grafici/templates/grafici/_widget.html (Chiedi ad Ada); addons/askada/pagine.py (dati strutturati della pagina); addons/grafici/ai.py (analisi_leggi_pagina, anche per le pianificate); core/dashboard.py (contesto_per_ada) | Copre pagine, grafici e dashboard in chat e nelle attività pianificate. La sintesi non finisce dentro le stampe PDF |

### AI e automazione (AI)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| AI-01 | Domande e risposte in linguaggio naturale sui dati, nel rispetto dei permessi | Edge | HAVE | addons/ai/strumenti/viste.py (cerca_record, leggi_record, aggrega_record); core/viste/interroga.py (viste_accessibili, campi_leggibili, aggrega); addons/ai/motore/turni.py; addons/ai/pagine.py; addons/askada | Permessi e azienda dell'utente controllati a ogni chiamata, numeri calcolati dal database, su tutte le viste accessibili. Il set di valutazione addons/ai/valutazione/domande.json ha solo 5 domande |
| AI-02 | OCR di fatture fornitore, ricevute e PDF con creazione di bozze | Edge | MISSING | grep di ocr e tesseract senza risultati nel codice; docs/idee-future.md (OCR tra le idee in sospeso); addons/ai/conoscenza.py (pypdf: solo testo già presente); addons/ai/models.py (Modello.visione mai usato dai gateway); addons/sdi/passive.py (import XML FatturaPA, non OCR); addons/spese/pagine.py (ricevuta solo archiviata) | Nessuna lettura di scansioni o immagini e nessuna estrazione verso bozze. La chat non accetta file e i gateway non inviano immagini. Le fatture passive strutturate arrivano già via XML SDI: il bisogno resta su ricevute e documenti esteri |
| AI-03 | Abbinamento bancario AI che impara dallo storico | Edge | HAVE | addons/banca/memoria.py di, firma_causale, Memoria.indizi; addons/banca/abbina.py _valuta, e_sicura; addons/banca/tests/test_memoria.py | Fatto il 2026-11-08: le proposte di riconciliazione imparano dagli abbinamenti confermati degli ultimi due anni (stesso IBAN, stessa controparte, causale che si ripete) e lo dicono nel motivo; conta l'indizio più forte, non la somma, e i punti imparati non rendono mai «sicura» una proposta: l'abbinamento automatico resta legato a numero e importo |
| AI-04 | Agenti pronti: fornitori, ordini di vendita, spese, riordino, approvazione acquisti | Edge | PARTIAL | addons/awf/fabbrica.py (catalogo: GET /api/catalog dalla fabbrica esterna); addons/awf/area.py (negozio, assumi); addons/awf/squadre.py; addons/awf/README.md; addons/ai/hooks.py (nessun assistente predefinito creato); addons/discuss/assistente_sito.py (solo sito) | Gli agenti si affittano da un catalogo esterno (Agentic Workforce): il repository contiene il canale ma non definisce agenti, e senza la fabbrica non ce n'è nessuno. Nessun agente pronto e locale per i cinque casi elencati |
| AI-05 | Costruttore di agenti con provider di modelli configurabile | Edge | PARTIAL | addons/ai/models.py (Assistente, Profilo, AnelloCatena, Modello, Provider, ChiaveAzienda); addons/ai/views.py; addons/ai/gateway/anthropic_api.py e openai_compat.py; addons/ai/assistenti.py; addons/ai/strumenti/esperti.py | Provider configurabili (Anthropic, compatibili OpenAI inclusi Gemini e Ollama, locali) e assistenti da interfaccia con istruzioni, strumenti, modelli, gruppi. Sono però assistenti di chat e di pianificazione: non partono da eventi o assegnazioni (docs/idee-future.md lo elenca tra le mancanze), Pianificata non sceglie un assistente, nessun flusso a più passi, gli esperti sono solo lettura. Le esecuzioni su assegnazione passano solo dalla fabbrica AWF |
| AI-06 | Server MCP o API per agenti esterni che leggono e scrivono con i permessi | Edge | HAVE | addons/awf/mcp.py (initialize, tools/list, tools/call, bearer in impronta, idempotenza); addons/awf/operazioni.py (OperazioneAmmessa); addons/awf/agenti.py (confina, utente agente per azienda); addons/awf/urls.py (mcp/); core/api/modelli.py e core/api/auth.py | Funziona per gli agenti del contratto attraverso Agate: un solo bearer per istanza, nessun OAuth né client MCP diretto per utente. I token REST sono negati agli utenti agente (agenti.token_negato). Nell'altro verso, dal 2026-11-05 Ada usa gli strumenti dei sistemi esterni del cliente come client MCP (addons/ai/mcp.py, ServerMCP): accesi uno per uno da un amministratore, con la conferma dell'utente salvo quelli segnati di sola lettura |
| AI-07 | Previsioni: domanda, flusso di cassa, scostamenti dal piano | Edge | PARTIAL | addons/ai/specialisti.py (serie_storica, prevedi, calcola_previsione, Timestral con quantili); addons/grafici/models.py (tipo PREVISIONE); addons/grafici/motore.py; deploy/compose.servizi-adabox.yml; addons/progetti/segnali.py (solo soglie di budget ore) | Previsione generica su una serie di una vista, solo con servizio locale configurato (ai.url_forecast). Nessuna previsione di cassa che usi scadenze e incassi, nessuna domanda per prodotto collegata al riordino, nessun rilevamento di scostamenti o anomalie. La licenza dei pesi di Timestral è da verificare per l'uso commerciale (memoria analisi-piano-fasi) |
| AI-08 | Generazione di testi: descrizioni prodotto, bozze email, riassunti di riunioni e ticket | Edge | HAVE | addons/ai/aiuto_testi.py richiesta_libera, descrivi_record, avvia_riassunto; addons/ai/static/ai/scrivi_con_ada.js; addons/ai/pagine.py scrivi_con_ada, riassumi_record; addons/ai/tests/test_scrivi_libero.py | Fatto il 2026-11-08: «Scrivi con Ada» accanto a ogni campo di testo dei form delle viste e nel composer del chatter, con istruzioni rapide (migliora, più breve, più formale, più cordiale, correggi) o scritte, il record come contesto solo se l'utente lo vede, proposta da modificare e inserimento solo su scelta (sostituisce o aggiunge in fondo); «Riassumi con Ada» nel dettaglio di ogni record (campi, chatter e letture del gestionale), da copiare o salvare come nota. Provato nel browser con il modello del server di sviluppo |
| AI-09 | Registro delle attività AI e approvazione umana per ogni azione degli agenti | Edge | HAVE | addons/ai/proposte.py e addons/ai/models.py (Proposta, conferma con permessi ricontrollati, GUARDIE); addons/ai/views.py (registro delle modifiche); addons/agate/guardia.py, addons/agate/applicazione.py, addons/agate/decisioni.py, addons/agate/models.py (Valutazione); addons/awf/models.py (Chiamata, Approvazione); addons/awf/mcp.py (_registra, _osserva) | In chat ogni scrittura è confermata da una persona. Per gli agenti la conferma è la decisione di Agate, servizio esterno, quindi l'approvazione umana dipende dalle sue regole e non scatta per forza su ogni azione. Letture e scritture degli agenti sono registrate |

### Integrazioni ed estensibilità (INT)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| INT-01 | Sincronizzazione di email e calendario (Gmail, Outlook, Exchange) | Core | PARTIAL | core/chatter/entrata.py (leggi_casella: una casella IMAP_URL di sistema); config/settings.py (IMAP_URL, EMAIL_URL); addons/calendario/ics.py e addons/calendario/lavori.py (inviti .ics, download) | Solo SMTP e una casella IMAP condivisa per le risposte. Nessun OAuth, nessuna casella per utente, nessuna API Gmail o Microsoft Graph. Calendario in una direzione soltanto: nessun feed sottoscrivibile, CalDAV o sync bidirezionale, risposte agli inviti non riportate |
| INT-02 | Integrazione con suite d'ufficio (Teams, Slack, add-in Outlook, Excel, Google Workspace) | Adv | PARTIAL | core/esporta.py e core/importa.py (solo file xlsx); grep di slack, google workspace, sharepoint, onedrive senza riscontri utili | C'è solo Excel come scambio di file. Nessuna notifica o comando su Teams e Slack, nessun add-in Outlook, nessun Google Drive o Docs. Nota: addons/discuss/demo_sito/integrazioni.md cita integrazioni, ma è il testo di un'azienda inventata per la demo |
| INT-03 | Gateway di pagamento, flussi bancari, corrieri | Core | PARTIAL | addons/banca/estratti.py (CAMT.053, MT940, CBI, CSV, Excel, solo file caricati); addons/banca/abbina.py; addons/fatturazione/models.py (metodi di incasso come semplici voci); addons/magazzino/models.py (vettore: testo libero) | Solo estratti conto caricati a mano. Nessun collegamento diretto con la banca (PSD2, CBI Globe), nessun gateway di pagamento né link di pagamento su fatture, nessuna integrazione con corrieri (etichette, tracking) |
| INT-04 | Provider di firma elettronica | Adv | MISSING | addons/vendite/operazioni.py (accetta: nome digitato, IP, impronta del preventivo) | Nessun provider di firma né firma qualificata. L'accettazione online del preventivo è un'adesione con nome e impronta, non una firma elettronica |
| INT-05 | Connettori eCommerce, marketplace, POS, logistica | Adv | MISSING | grep di shopify, woocommerce, magento, prestashop, amazon, ebay: solo addons/discuss/demo_sito/integrazioni.md, testo dimostrativo di un'azienda inventata; core/api/modelli.py (API generica) | Nessun connettore e nessuna sincronizzazione di ordini, giacenze o prezzi. Nessun POS |
| INT-06 | Agganci per piattaforme low-code (Zapier, Make, Power Automate) | Adv | PARTIAL | addons/automazioni/motore.py (AZIONI: email, attivita, nota, assegna); addons/automazioni/catalogo.py (eventi); core/api/modelli.py; addons/github/webhook.py, addons/discuss/connettori.py, addons/awf/webhook.py (webhook specifici in entrata) | Automazioni interne e CRUD REST utilizzabili come azioni generiche. Manca il lato trigger: nessun webhook in uscita, nessuna azione HTTP nelle regole, nessun app o connettore per Zapier, Make, Power Automate |
| INT-07 | Marketplace di moduli di partner e API dei moduli versionata | Adv | PARTIAL | core/registry/pacchetti.py (zip firmati, indice, chiavi fidate multiple); core/registry/sincronia.py; core/registry/collaudo.py; core/registry/manifest.py (min_core); core/applicazioni.py; addons/rivendita/models.py (ModuloVendibile, Pacchetto, Piano, Istanza); addons/awf/area.py (negozio degli agenti) | Distribuzione, firma, licenza e catalogo funzionano ma sono solo di ICHNOBYTE (README: pacchetto firmato da ICHNOBYTE; prezzi nel catalogo ancora decisione aperta). Nessun partner con invio, revisione o ripartizione ricavi. API dei moduli non versionata: solo min_core e README, nessuna politica di deprecazione né kit per sviluppatori |
| INT-08 | Documentazione API aperta, SDK, webhook, ambienti sandbox | Core | HAVE | core/api/modelli.py schema_record; core/api/sdk.py genera (/api/v1/sdk/python/); core/management/commands/sandbox.py; docs/sandbox.md; core/tests/test_api_sdk.py, test_sandbox.py | Fatto il 2026-11-08: documentazione OpenAPI con gli schemi di corpi e risposte di ogni vista, SDK Python generato dall'istanza (un file, solo libreria standard, risorse, paginazione, bottoni, errori per campo, attesa col limite), istanza di prova con SANDBOX=True (banner, email nel log, SDI simulato, webhook veri) e comando «sandbox prepara» con dati demo, utente e token a scadenza; webhook e token con ambiti dal 2026-11-05. L'istanza di prova va allestita come quella di un cliente |
| INT-09 | Edizioni preconfigurate per settore (ruoli, flussi, dati di esempio) | Adv | PARTIAL | addons/rivendita/models.py (Piano: moduli, utenti, prezzo); core/ruoli.py e chiave groups dei manifest; core/management/commands/dati_demo.py (dati generici); chiave demo dei manifest | Esistono mattoni generici: piani come elenchi di moduli, ruoli per app, dati demo. Nessuna edizione di settore che unisca moduli, ruoli, regole di Automazioni, campi e dati demo; il settore compare solo come parola nei nomi demo |

### Localizzazione e conformità (LOC)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| LOC-01 | Pacchetti di localizzazione fiscale per paese | Core | PARTIAL | addons/fiscale/data/iniziali.json; addons/fiscale/models.py NATURE, MODALITA; addons/fatturazione/models.py TIPI, REGIMI, IMPORTO_BOLLO | Esiste solo il pacchetto Italia ed è cablato nei modelli. Nessun meccanismo per altri paesi; il piano dei conti non si applica per la decisione del 2026-11-03. Per un prodotto solo italiano non è urgente |
| LOC-02 | Export delle dichiarazioni nel formato dell'Agenzia | Core | HAVE | Solo CSV in addons/fatturazione/registro.py e addons/sdi/pagine.py, non in formato ministeriale; nessun riscontro per LIPE, CU, F24 | Nessun file ufficiale. Dichiarazione annuale e CU restano naturalmente allo studio, salvo i dati di partenza | Dal 2026-11-07 c'è la LIPE (addons/iva/lipe.py); CU e F24 restano allo studio. Dal 2026-11-09 anche i dati delle ritenute per CU e F24 (addons/sdi/ritenute.py). |
| LOC-03 | Canali nazionali di fatturazione elettronica | Adv | PARTIAL | Stessi di FIN-33: addons/sdi/canali.py, addons/sdi/pec.py, addons/fatturazione/fatturapa.py | SDI operativo, via PEC o portale. Nessun altro canale: Peppol e intermediario mancano. Stesso lavoro di FIN-33, da non contare due volte |
| LOC-04 | Localizzazione delle paghe | Adv | N/A | addons/personale gestisce ferie, permessi e saldi; spec fase 7 mette paghe e cedolini fuori scope per quella fase | Esclusa per scelta dell'utente il 2026-11-05: le paghe restano al consulente del lavoro. |
| LOC-05 | IVA, Intrastat, elenchi UE, export di audit (SAF-T) | Adv | PARTIAL | Registri in addons/fatturazione/registro.py e addons/sdi/pagine.py; addons/contatti/vies.py controllo VIES; autofatture TD17-TD19 | Registri IVA e VIES ci sono. Mancano Intrastat (nessun codice nomenclatura né peso sui prodotti), elenchi delle operazioni UE e qualsiasi export di audit. SAF-T non è richiesto in Italia |
| LOC-06 | Schemi di bilancio civilistici e IFRS | Adv | N/A | Nessun mastro | Dipende dal mastro, decisione utente 2026-11-03. Nessuna esportazione richiesta |
| LOC-07 | GDPR: cancellazione, consensi, conservazione | Core | HAVE | addons/privacy (models.py Consenso, Finalita, RichiestaInteressato, Anonimizzazione, RegolaConservazione; servizi.py registra, esporta, anonimizza, applica_conservazione; conservazione.py; tests/test_privacy.py) | Fatto il 2026-11-08 nel nuovo modulo Privacy: registro dei consensi per finalità con storico e fonte; richieste degli interessati con scadenza a 30 giorni; esportazione in JSON di tutti i dati di un contatto in ogni app; anonimizzazione irreversibile che, se ci sono documenti da conservare (record legati con PROTECT), lascia solo i dati fiscali e toglie anche email e nomi copiati in opportunità e ticket, allegati, testo dei messaggi e valori precedenti nel registro delle modifiche; regole di conservazione, solo sui dati dichiarati dai moduli, eseguite ogni notte dal cron |
| LOC-08 | Predisposizione a SOC 2 e ISO 27001, residenza dati, cifratura a riposo | Adv | PARTIAL | core/cifratura.py Fernet per i segreti; core/due_fattori.py; axes e cookie sicuri in config/settings.py; core/storage.py StoragePrivato; deploy/compose.cliente.yml | Segreti cifrati, 2FA, blocco accessi e installazione presso il cliente che risolve la residenza. Mancano cifratura di database, file e backup (core/backup.py scrive in chiaro), audit log generale e qualsiasi documentazione di controlli |

### Pacchetti di settore (IND)

| ID | Funzione | Tier | Stato | Evidenza | Note sul gap |
|---|---|---|---|---|---|
| IND-01 | Verticali retail (abbigliamento, alimentari, ferramenta, arredo, libri) | Adv | MISSING | addons/ (nessun modulo di settore); addons/prodotti/models.py (senza varianti); spec fase 5: varianti, lotti, POS fuori scope | Nessun pacchetto di settore e mancano le fondamenta: POS, varianti taglia/colore, lotti e scadenze, che le spec escludono. |
| IND-02 | Verticali ospitalità (ristoranti, hotel, campeggi, pulizie, addebiti in camera) | Adv | MISSING | Nessuna occorrenza di camere o tavoli nei modelli; i termini hotel e ristorante compaiono solo nei dati finti di core/management/commands/dati_demo.py | Nulla di relativo a camere, prenotazioni, conti ospite, governo camere o ristorazione. |
| IND-03 | Verticali servizi (agenzie, consulenza, saloni e attività su prenotazione) | Adv | PARTIAL | addons/progetti, addons/timesheet, addons/commesse (operazioni.monte_ore, redditività), addons/ricorrenti, addons/assistenza, addons/capacita, addons/rivendita/schede.py | Per agenzie e consulenti i moduli coprono davvero il lavoro: ore, commesse, canoni, portale, carico di lavoro. Manca un pacchetto installabile con dati e ruoli di settore. Per saloni e attività su prenotazione manca del tutto la base (CRM-13). |
| IND-04 | Verticali istruzione, sanità, agricoltura, non-profit | Adv | MISSING | Nessun modulo o dato di settore in addons/; nessuna occorrenza applicativa di scuola, agricol, non-profit | Nessun modello specifico, inclusi studenti, pazienti, appezzamenti, donazioni. |
| IND-05 | Modelli per produzione discreta e di processo | Adv | N/A | docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md: Non previsti, produzione; docs/superpowers/specs/2026-10-28-adabox-hub-fase5-gestionale-design.md: Fuori scope, produzione; nessun modulo di produzione in addons/ | Escluso dalle spec; se si riapre dipende da tutta la sezione MFG. |

## C. Elenco delle lacune per priorità

### 1. Core MISSING (14)

**Piattaforma e architettura**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PLT-02 | Multi-valuta: tabelle cambi, aggiornamento automatico, differenze di cambio | Modello Valuta e Cambio con aggiornamento da BCE, valuta e cambio su documenti, listini, scadenze e incassi, totali in valuta aziendale, Divisa in FatturaPA, report delle differenze di cambio. | CRM-05, FIN-30 | L |

**Finanza e contabilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| FIN-10 | Sincronizzazione bancaria automatica | Connettore a un aggregatore PSD2 con consenso per conto, lettura periodica nel cron e movimenti passati dalla stessa deduplica. | FIN-09 | M |
| FIN-13 | Casse e piccola cassa con saldo di apertura e chiusura | Conto di tipo cassa senza IBAN, movimenti manuali, apertura e chiusura con quadratura, collegamento a incassi e rimborsi in contanti. | - | M |
| FIN-25 | Link di pagamento e pagamento online delle fatture | Pagina pubblica con token per fattura, connettore a un provider di pagamento con webhook che registra l'Incasso, link nelle email di invio e sollecito. | - | M |

**Magazzino**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INV-03 | Lotti e seriali con scadenze e tracciabilità | Modelli Lotto e Seriale con scadenza, obbligo di indicazione su ricevimenti e consegne per i prodotti tracciati, giacenza per lotto e report di tracciabilità a monte e a valle. | INV-05 | L |
| INV-09 | Metodi di valorizzazione (FIFO, medio, standard) con strati di costo | Costo unitario su ogni movimento, strati di costo per FIFO e medio ponderato, standard opzionale, rivalutazione e valore di magazzino a una data; nessuna scrittura contabile, solo esportazione. | INV-05 | L |
| INV-11 | Lettura barcode nei flussi di magazzino | Interfaccia mobile di lettura (lettore o fotocamera) che guida ricevimento, prelievo, conta e trasferimento, confermando le quantità sui documenti aperti. | INV-01, INV-05, INV-06, INV-08 | M |
| INV-13 | Imballi e kit (prodotti composti) | Confezioni per prodotto (pezzi per scatola o pallet) e kit con componenti, esplosi in consegna con scarico dei componenti e disponibilità calcolata. | INV-01, INV-02 | M |

**Persone e paghe**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|

**Commercio e front office**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| COM-02 | Pagamenti online con più gateway | Interfaccia gateway con almeno due fornitori (es. Stripe, PayPal o Nexi), link di pagamento su fatture e preventivi, webhook firmato che registra l'incasso via incassa_fattura. | COM-01, FIN-25, INT-03 | M |

**Report e analisi**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|

**Localizzazione e conformità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| LOC-02 | Export delle dichiarazioni nel formato dell'Agenzia | File XML LIPE trimestrale dalla liquidazione, validato con lo schema. Export delle ritenute per la CU allo studio. | FIN-16 | M |

### 2. Core PARTIAL (56)

**Piattaforma e architettura**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PLT-01 | Multi-azienda e filiali in un solo database, con report consolidati | Selettore multi-azienda nelle interrogazioni e nei grafici con totali consolidati, livello filiale opzionale. | FIN-30 | M |
| PLT-05 | Numerazioni per azienda e tipo documento; esercizi, periodi, date di blocco | Pagina front per le sequenze, modello Esercizio o Periodo per azienda con data di blocco controllata da un servizio del kernel in save, azioni e API di fatturazione, sdi, banca e magazzino. | - | M |
| PLT-06 | Campi, form, liste e menu configurabili senza codice | ProprietaMixin esteso a righe e modelli restanti, campo collegamento a record, editor delle voci di menu interne, personalizzazioni per ruolo e azienda. | - | M |
| PLT-08 | Regole di automazione e lavori pianificati (creazione, modifica, tempo, azioni server) | Eventi generici su qualsiasi ModelView, azioni di modifica campo, esecuzione di bottoni, chiamata webhook, e pagina front per le pianificazioni. | PLT-14 | M |
| PLT-13 | Import CSV e XLSX con mappatura, validazione e varianti per riga; export di massa | Import a testata e righe sulle viste con inlines, risoluzione della variante per riga quando INV-01 esiste, import_key sulle anagrafiche principali. | INV-01 | M |
| PLT-17 | Ricerca globale, filtri salvati e preferiti; viste kanban, lista, pivot, grafico, calendario, Gantt | Attributo Gantt nella ModelView: ricerca trasversale, ricerche salvate e pivot fatte il 2026-11-05. | - | M |

**Finanza e contabilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| FIN-05 | Fatture fornitore proposte da ordini o ricevimenti (3-way match) | Confronto per riga leggendo CodiceArticolo dall'XML e abbinandolo al codice fornitore del listino; blocco facoltativo alla registrazione oltre la tolleranza. | - | M |
| FIN-11 | Riconciliazione con suggerimenti e modelli di abbinamento | Regole configurabili per causale, controparte e importo che classificano i movimenti senza fattura e li rendono esportabili allo studio. | - | M |
| FIN-12 | Pagamenti parziali, eccedenze, abbuoni e crediti da allocare | Credito cliente non allocato e riutilizzabile sulle scadenze. Registro dei pagamenti su ScadenzaPassiva, simmetrico a Incasso, con parziali e abbuoni. | - | M |
| FIN-14 | Stampa assegni e pagamenti a lotti | Distinta di pagamento come lotto di scadenze, con totale, stato e file bancario. Stampa assegni solo se richiesta. | FIN-32 | S |
| FIN-15 | Motore fiscale: gruppi, IVA inclusa, posizioni fiscali, ritenute | Posizioni fiscali su contatto e paese che mappano le aliquote in automatico, prezzi IVA inclusa, dichiarazioni d'intento con plafond, lettura delle ritenute passive. | - | M |
| FIN-16 | Report IVA di periodo con export per l'Agenzia | Pagina di liquidazione IVA mensile o trimestrale dai due registri, con credito riportato e detraibilità, ed export dati per lo studio; il file ufficiale è LOC-02. | FIN-15 | M |
| FIN-19 | Budget con confronto budget e consuntivo | Budget economico per commessa e periodo, a voci, con consuntivo da ore, fatture passive e note spese imputate. | FIN-20 | M |
| FIN-20 | Contabilità analitica a dimensioni | Dimensioni analitiche configurabili (commessa, centro di costo) sulle righe di documento, con ripartizioni percentuali, modifica massiva e report per asse. | - | M |

**Vendite, CRM e marketing**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| CRM-03 | Flusso lead, preventivo, ordine, consegna, fattura con documenti collegati | FK opzionale da OrdineVendita a Opportunita, pulsante Crea preventivo sull'opportunità, sezione documenti collegati e opportunità vinta alla conferma dell'ordine; fatturazione parziale per consegnato da valutare a parte. | - | S |
| CRM-04 | Modelli di preventivo, prodotti opzionali, date di validità | Modello ModelloPreventivo con righe e testi precompilati; righe marcate opzionali, escluse dal totale finché il cliente non le sceglie dalla pagina online, con impronta ricalcolata sulla scelta. | CRM-09 | M |
| CRM-05 | Listini e regole di sconto per cliente, quantità, data, valuta | Listino predefinito sul contatto, date di validità sulle voci, regole di sconto per cliente, categoria e quantità in prezzi.py, valuta del listino quando esiste la multivaluta. | PLT-02 | M |
| CRM-06 | Contatti: aziende e persone, più indirizzi, tag, gerarchia | Modello IndirizzoContatto tipizzato (fatturazione, consegna, sede) con scelta su ordine e consegna e riporto in DDT e FatturaPA; società madre opzionale tra aziende. | - | S |
| CRM-07 | Team di vendita, obiettivi, report pipeline e vinte/perse | Modelli TeamVendita e ObiettivoVendita per persona, team e periodo, riassegnazione per team; report consuntivo su obiettivo, tasso di vittoria, durata media e motivi di perdita. | - | M |
| CRM-08 | Sincronizzazione email su contatti e opportunità (IMAP, Gmail, Exchange) | Caselle per utente con OAuth Gmail e Microsoft Graph oltre a IMAP, abbinamento automatico per mittente a contatto e opportunità aperta, invio al cliente dal chatter del record. | INT-01, PLT-10 | L |
| CRM-09 | Portale clienti: preventivi, accetta/firma, ordini e fatture | Sezioni Preventivi, Ordini e Fatture nel portale filtrate su AccessoPortale.contatti(), con PDF scaricabili e riuso di operazioni.accetta per i preventivi aperti. | COM-01, CRM-16 | M |

**Magazzino**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INV-01 | Anagrafica articolo: varianti, alternativi, barcode, codici fornitore e cliente | Modello attributi e varianti con generazione degli articoli, più barcode per articolo, tabella alternativi e codici per cliente, adeguando le righe documento. | PUR-02 | L |
| INV-02 | Unità di misura con categorie e conversioni; UM acquisto e vendita | Categorie e fattori di conversione, UM di acquisto e di vendita sul prodotto, UM sulle righe con conversione alla UM base nei movimenti. | - | M |
| INV-04 | Più magazzini con ubicazioni gerarchiche e scaffali | Modello Ubicazione ad albero sotto Magazzino, ubicazione su movimenti e righe documento, giacenza per ubicazione, con migrazione verso un'ubicazione predefinita. | INV-05 | L |
| INV-05 | Movimenti, trasferimenti interni, ricevimenti, consegne con stati | Documento di trasferimento a doppio movimento, stato «pronto», evasione parziale con documento di residuo legato alla riga d'ordine e storno controllato dei documenti fatti. | - | M |
| INV-06 | Liste di prelievo e documenti di imballaggio per evadere le vendite | Stampa e pagina di prelievo per consegna con percorso per ubicazione, quantità prelevata confermata e colli con contenuto, prima dell'emissione del DDT. | INV-04, INV-05 | M |
| INV-07 | Punti di riordino, min/max, proposte e giacenza prevista | Regole per magazzino e colonna del previsto nella pagina Giacenze, riusando acquisti.riordino. | INV-05 | M |
| INV-08 | Inventari, conte cicliche e rettifiche | Documento di inventario con fotografia del teorico, inserimento o importazione del contato, approvazione che genera le rettifiche; pianificazione delle conte cicliche; esportazione del valore delle differenze per il commercialista. | INV-04 | M |
| INV-10 | Report: disponibile, previsto, anzianità, storico movimenti, valore | Pagine di giacenza a data, prevista, anzianità per fasce e valore di magazzino, con esportazione. | INV-07, INV-09 | M |
| INV-12 | Resi clienti (RMA) con rientro a magazzino e rimborso | Modello Reso da consegna o fattura con autorizzazione, motivo, rientro con carico o scarto e nota di credito parziale precompilata sulle righe rese. | INV-05 | M |

**Persone e paghe**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| HR-02 | Contratti con struttura retributiva e storico | Modello Contratto con validità, CCNL e livello, retribuzione e voci, storico per dipendente, avvisi di scadenza; spostare ore e ferie annue sul contratto in vigore. | HR-01 | M |
| HR-08 | Portale self-service del dipendente (cedolini, assenze, spese, documenti) | Pagina Il mio profilo che riunisce assenze, spese, ore, contratto, cedolini e documenti HR riservati, con richiesta di modifica dei dati anagrafici. | HR-02, HR-09 | M |

**Progetti, servizio e assistenza**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PRJ-02 | Ore sui compiti e fatturazione progetto (corpo, ore, milestone) | Tipo di fatturazione a milestone con percentuale o importo per tappa, fattura in bozza al completamento, acconti e controllo del residuo a corpo. | PRJ-01 | M |
| PRJ-03 | Redditività di progetto (ricavi e costi, budget) | Budget economico per voce, costi da spese, acquisti e magazzino collegati al progetto, confronto preventivo e consuntivo con proiezione a finire e vista portafoglio. | PRJ-02, PRJ-12 | M |
| PRJ-05 | Base di conoscenza e wiki interna | App di pagine gerarchiche in markdown con permessi per spazio, versioni, ricerca e collegamenti ai record, indicizzate dalla conoscenza di addons/ai. | - | M |
| PRJ-06 | Portale clienti per ticket e avanzamento progetti | Pagina di dettaglio del progetto nel portale con avanzamento (Progetto.riepilogo_compiti), milestone e rilasci, e un flag sui compiti visibili al cliente. | PRJ-01 | S |

**Commercio e front office**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| COM-01 | Portale clienti: fatture, ordini, preventivi, ticket, documenti | Spostare AccessoPortale e l'involucro del portale in un modulo proprio, con sezioni registrate dalle app (vendite, fatturazione, documenti, assistenza) tramite hook e filtro unico sul cliente. | PRJ-06 | M |

**Report e analisi**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|

**Integrazioni ed estensibilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INT-01 | Sincronizzazione di email e calendario (Gmail, Outlook, Exchange) | OAuth per utente con Google e Microsoft: posta collegata ai record per mittente e sync bidirezionale degli eventi, più un feed ICS privato come primo passo. | - | L |
| INT-03 | Gateway di pagamento, flussi bancari, corrieri | Link di pagamento su fatture e scadenze (Stripe o Nexi) con incasso automatico da webhook, feed bancario PSD2 tramite aggregatore, spedizioni e tracking con uno o due corrieri. | - | L |

**Localizzazione e conformità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| LOC-01 | Pacchetti di localizzazione fiscale per paese | Separare le regole italiane in un pacchetto caricabile per paese (aliquote, tipi documento, formato elettronico). Da fare solo se si vende all'estero. | FIN-15 | L |

### 3. Adv MISSING (40)

**Finanza e contabilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| FIN-31 | Automazione delle operazioni tra aziende del gruppo | Regola per coppie di aziende che, alla conferma di un ordine di vendita, crea l'ordine d'acquisto speculare e collega le fatture. | FIN-05 | M |
| FIN-32 | File di pagamento SEPA, SDD e RiBa | Distinte da scadenze aperte con pain.001 per i bonifici, pain.008 e mandati per gli SDD, RiBa in formato CBI; ritorno dell'esito sugli incassi. | - | M |
| FIN-34 | Finanziamenti, spese indeducibili, report ESG | Registro dei finanziamenti con piano delle rate che genera scadenze da pagare. ESG solo su richiesta. | - | M |

**Vendite, CRM e marketing**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| CRM-12 | Email marketing, SMS, sondaggi, gestione eventi | Campagne email con liste e disiscrizione, gateway SMS, sondaggi con link pubblico e risultati, eventi con iscrizioni e partecipanti: da spezzare in rilasci separati. | CRM-11 | L |
| CRM-13 | Prenotazione online di appuntamenti collegata ai calendari | Tipi di appuntamento con durata e operatori, fasce di disponibilità al netto degli eventi, pagina pubblica di prenotazione con conferma e .ics, contatto od opportunità creati in automatico. | INT-01 | M |
| CRM-14 | Punteggio predittivo dei lead | Punteggio salvato sull'opportunità con ricalcolo periodico nel worker da storico vinte/perse, attività e dati del contatto, spiegazione dei fattori e ordinamento in kanban. | CRM-07 | M |
| CRM-18 | Configuratore di prodotto / CPQ | Attributi e valori con regole di compatibilità e sovrapprezzi, configuratore in riga di preventivo che genera descrizione e prezzo, approvazione degli sconti oltre soglia. | INV-01, CRM-05 | L |

**Acquisti**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PUR-09 | Costi accessori di acquisto ripartiti sul valore di magazzino | Documento di costi accessori legato a ricevimenti, ripartizione per valore, peso o quantità con aggiornamento degli strati di costo. | INV-09, PUR-03 | M |
| PUR-10 | Triangolazione: il fornitore spedisce al cliente | Riga di vendita marcata «in triangolazione» che genera l'ordine al fornitore con il destinatario del cliente; conferma di spedizione senza movimentare la giacenza propria. | PUR-03, INV-05 | M |
| PUR-11 | Conto lavoro in acquisto (invio componenti, rientro del finito) | Ordine di conto lavoro con elenco componenti, DDT di invio verso un magazzino del terzista, rientro del finito con consumo dei componenti e costo della lavorazione. | MFG-01, INV-04, INV-05 | L |
| PUR-12 | Portale fornitori (conferma ordini, caricamento fatture) | Link firmato o accesso fornitore per confermare ordine e data di consegna, comunicare ritardi e caricare DDT o fattura, sul modello di assistenza/portale.py. | PUR-03 | M |

**Magazzino**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INV-14 | Strategie di stoccaggio e prelievo (FIFO, FEFO, LIFO, per rotazione) | Regole di stoccaggio per prodotto e categoria che suggeriscono l'ubicazione, regole di prelievo che ordinano lotti e ubicazioni nella lista di prelievo. | INV-03, INV-04, INV-06 | L |
| INV-15 | Percorsi a più passi, prelievo a ondate e a gruppi | Percorsi configurabili per magazzino con documenti concatenati, raggruppamento di più consegne in un'ondata di prelievo. | INV-04, INV-06 | L |
| INV-16 | Integrazione corrieri: tariffe, etichette, tracciamento | Connettori verso corrieri italiani e aggregatori, con preventivo, creazione spedizione, stampa etichetta e aggiornamento dello stato. | INV-05 | L |
| INV-17 | Prenotazione spedizioni con colli e modelli; viaggi e percorsi | Modello Spedizione con colli e modelli di imballo, viaggi di consegna con mezzo, autista e ordine delle tappe. | INV-16 | M |
| INV-18 | Controlli qualità (ricevimento, consegna, processo) con quarantena | Punti di controllo per prodotto e fase con esito superato o respinto, blocco in quarantena e non conformità legata al fornitore, tenendo separata l'app qualita. | INV-04, INV-05 | M |
| INV-19 | Conto deposito, cross-docking, funzioni 3PL e WMS | Proprietario della giacenza su movimenti e ubicazioni, magazzini presso terzi per il conto deposito, passaggio diretto da ricevimento a consegna. | INV-04, INV-05 | L |

**Produzione**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| MFG-13 | Manutenzione preventiva e correttiva delle attrezzature | Anagrafica attrezzature, piani periodici che generano interventi, interventi correttivi con ricambi e ore; legame opzionale ai centri di lavoro. | - | M |
| MFG-16 | Integrazione IoT (bilance, stampanti, sensori, PLC) | Agente locale che collega bilance, stampanti e sensori via API, con eventi che si traducono in operazioni di magazzino. | INV-11 | L |

**Persone e paghe**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| HR-10 | Competenze, formazione online, certificazioni | Catalogo competenze con livelli per dipendente, certificazioni con scadenza e avviso; corsi con lezioni e quiz in un secondo passo. | HR-01 | L |
| HR-11 | Obiettivi e riconoscimenti | Obiettivi per dipendente o reparto con misura, avanzamento; riconoscimenti pubblicati in Discuss. | - | M |
| HR-12 | Parco auto (veicoli, contratti, costi) | Veicoli assegnati ai dipendenti, contratti di leasing e assicurazione, scadenze (revisione, bollo), costi e chilometri, con avvisi. | HR-01 | M |
| HR-13 | Pianificazione dei turni | Modelli di turno, griglia settimanale per reparto con trascinamento, controllo su assenze e sovrapposizioni, pubblicazione e scambio; le ore pianificate alimentano capacita. | HR-01, HR-03 | M |

**Progetti, servizio e assistenza**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PRJ-09 | Gestione delle garanzie | Termini di garanzia per prodotto, scadenza calcolata dalla consegna per seriale, pratica con esito e addebito o copertura, con recupero dal fornitore. | INV-03, PRJ-08 | M |
| PRJ-10 | Manutenzione di attrezzature proprie e dei clienti | Registro attrezzature per sede o cliente, piani preventivi a calendario o a contatore che generano interventi, storico guasti e costi. | INV-03 | L |
| PRJ-11 | Riparazioni (preventivo, ricambi, manodopera) | Ordine di riparazione con ingresso del bene, preventivo, ricambi scaricati da magazzino, ore da timesheet, riconsegna e fattura. | INV-03, PRJ-10 | M |

**Commercio e front office**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| COM-07 | Fedeltà, gift card, promozioni in POS ed eCommerce | Riuso del motore promozioni e saldi di CRM-17 sui canali POS ed eCommerce, se riaperti. | CRM-17, COM-03, COM-05 | M |
| COM-08 | Connettori marketplace e piattaforme (Shopify, Amazon, POS terzi, logistica) | Quadro di connettori con mappature, coda e riprova sul modello di discuss/connettori.py; primi: un corriere (etichette e tracking) e uno store (ordini e giacenze). | INT-05, PLT-14, INT-03 | L |
| COM-11 | Noleggio e biglietteria eventi | Noleggi con disponibilità per periodo, ritiro, rientro, cauzione e fatturazione; biglietti con tipologie, posti, QR e check-in, in un modulo eventi separato. | CRM-13, CRM-12, COM-02 | L |

**Report e analisi**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| RPT-08 | Foglio di calcolo integrato con collegamenti vivi ai dati | Foglio web con componente esistente, salvato nei Documenti, con funzioni che leggono da core/viste/interroga.py con i permessi di chi apre. | RPT-02 | L |
| RPT-10 | Esportazione verso data warehouse o replica in lettura | Esportazione pianificata e incrementale (Parquet o CSV su storage esterno, per azienda) e supporto a una replica Postgres per letture pesanti e analisi. | - | M |

**Integrazioni ed estensibilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INT-04 | Provider di firma elettronica | Connettore astratto con un provider (Namirial o Yousign): invio dagli allegati, firmatari, webhook di stato e documento firmato archiviato nel record. | - | M |
| INT-05 | Connettori eCommerce, marketplace, POS, logistica | Base comune di sincronizzazione (mappature, code, riprova) e primo connettore Shopify o WooCommerce per ordini, giacenze e prezzi. | INT-06, INT-08 | L |

**Localizzazione e conformità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|

**Pacchetti di settore**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| IND-01 | Verticali retail (abbigliamento, alimentari, ferramenta, arredo, libri) | Dopo aver riaperto POS e varianti: pacchetti con dati iniziali, ruoli e automazioni per tipo di negozio. | COM-05, INV-01, CRM-17 | L |
| IND-02 | Verticali ospitalità (ristoranti, hotel, campeggi, pulizie, addebiti in camera) | Modulo con camere, tariffe, prenotazioni, conto ospite con addebiti e pulizie; la ristorazione dipende da COM-06. | COM-06, CRM-13, COM-02 | L |
| IND-04 | Verticali istruzione, sanità, agricoltura, non-profit | Moduli separati da scegliere in base al mercato, sopra il meccanismo dei modelli di settore: nessuno ha senso prima di una richiesta concreta. | IND-03 | L |

### 4. Adv PARTIAL (34)

**Piattaforma e architettura**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PLT-20 | Marketplace di moduli: installare moduli di terzi senza toccare il kernel | Registrazione degli editori con le loro chiavi, flusso di invio e revisione con modulo collauda automatico, scheda pubblica con recensioni, permessi dichiarati nel manifest. | - | M |
| PLT-21 | Costruttore low-code di app (modelli, viste, automazioni dalla UI) | Modelli definiti da UI, in tabelle generiche con JSON o migrazioni generate, che producono una ModelView con liste, form, permessi, chatter e API. | PLT-06, PLT-08 | L |
| PLT-22 | Opzioni di installazione: SaaS multi-tenant e on-premise | Provisioning automatico per istanza dal portale (stack, database, dominio, TLS, token), aggiornamenti controllati e monitoraggio della flotta. | - | M |
| PLT-23 | SSO (OAuth2, SAML), due fattori, LDAP o AD | Accesso OIDC e SAML configurabile da UI con creazione utente e mappatura di gruppi su ruoli, backend LDAP facoltativo. | - | M |
| PLT-24 | Firma elettronica integrata sui documenti | Richieste di firma su ogni PDF con più firmatari in ordine, verifica via email o SMS, firma apposta sul PDF con pagina di evidenze e impronta, archiviata nei documenti. | PLT-09, PLT-12 | M |
| PLT-25 | Foglio di calcolo o BI integrati con collegamenti vivi ai dati | Foglio integrato con formule che leggono da interroga.py con i permessi dell'utente, oppure connettore live per Excel come OData. | PLT-17 | L |
| PLT-26 | Ambienti sandbox o staging e anonimizzazione dei dati di prova | Comando clona in staging da backup, con anonimizzazione dichiarata per campo, blocco di email e canali esterni e banner di ambiente di prova. | - | M |

**Finanza e contabilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| FIN-28 | Abbonamenti: ricorrenza, consumo, pro-rata, cambi piano | Righe a consumo con misuratore, cambi piano con data di effetto e conguaglio pro-rata in fattura. | - | M |
| FIN-29 | FP&A: piani, modelli, allocazioni, versioni di forecast | Modulo di pianificazione con versioni di budget e forecast per dimensione, driver semplici e confronto con il consuntivo. | FIN-19, FIN-20 | L |
| FIN-33 | Fatturazione elettronica: SDI, Peppol, attiva e passiva con stati | Canale verso un intermediario accreditato con conservazione a norma nell'interfaccia di canali.py. Peppol tramite access point solo se servono clienti esteri. | - | M |

**Vendite, CRM e marketing**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| CRM-10 | Automazione marketing: campagne a gocce e trigger | Campagne a passi con attese e condizioni di uscita su un segmento di contatti, costruite sopra motore e modelli email, con registro consensi, disiscrizione e tracciamento. | CRM-11, CRM-12 | L |
| CRM-11 | Segmentazione clienti: profilazione, ABC, tag, liste dinamiche | Modello Segmento con regole salvate e ricalcolate, classe ABC periodica dal fatturato, uso del segmento in liste, automazioni e campagne. | - | M |
| CRM-15 | Provvigioni, quote e previsione delle vendite | Piani provvigionali per venditore e prodotto maturati su ordine o incasso con estratto; quote legate agli obiettivi; vista previsione per periodo da pipeline ponderata con rettifica manuale. | CRM-07 | M |
| CRM-16 | Firma elettronica su preventivi e contratti | Servizio di firma riusabile sui documenti: richiesta con OTP via email o SMS, PDF con pagina di attestazione e hash conservato, opzione verso provider qualificato; applicato a preventivi e contratti. | PLT-24 | M |
| CRM-17 | Abbonamenti, noleggio, fedeltà, promozioni, gift card, coupon | Regole promozionali e coupon applicati alle righe di vendita, carte regalo e punti come saldo del contatto con registro movimenti; il noleggio segue COM-11. | COM-07, COM-11 | L |

**Acquisti**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PUR-13 | Valutazione fornitori (puntualità, qualità, prezzo) | Aggiungere alla pagella l'andamento dei prezzi rispetto al listino e agli altri fornitori; legare la qualità ai controlli in ingresso quando esisteranno (INV-18). | PUR-03, INV-18 | M |

**Magazzino**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INV-20 | Previsione della domanda e riapprovvigionamento predittivo | Lavoro periodico che calcola la domanda per articolo e aggiorna scorta di sicurezza e punto di riordino consigliati, con un'alternativa locale quando il servizio manca. | INV-07 | M |

**Progetti, servizio e assistenza**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PRJ-08 | Assistenza sul campo: pianificazione, ordini di servizio, riparazioni, contratti, garanzie, articoli in assistenza, listini servizi | App con ordine di intervento da ticket o contratto, pianificazione su calendario dei tecnici, rapportino da mobile con firma, ore e materiali, e fatturazione tramite commesse. | PRJ-10, PRJ-11, INV-03, PLT-16 | L |
| PRJ-12 | PSA completa: utilizzo risorse, riconoscimento ricavi di progetto, riaddebito spese | Report di utilizzo per persona e reparto; progetto e flag riaddebitabile su RigaSpesa con riga in fattura; ricavi maturati per avanzamento, come esportazione per il commercialista. | PRJ-02, PRJ-03, HR-05, FIN-18 | L |
| PRJ-13 | Appuntamenti e prenotazioni | Tipi di appuntamento con durata e orari, pagina pubblica che propone fasce libere dalle agende, conferma con .ics, cancellazione e promemoria. | - | M |

**Commercio e front office**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| COM-09 | Gestione self-service di account e abbonamenti | Sezione portale con contratti, scadenze, fatture e disdetta entro i termini, modifica dei dati anagrafici e di pagamento con revisione interna. | COM-01, COM-02 | M |

**Report e analisi**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| RPT-07 | Designer di report con layout personalizzati e report SQL o su dataset | Editor di layout per stampe e report su dataset definiti da viste e campi collegati, resi con WeasyPrint. Un eventuale SQL solo in sola lettura e su viste autorizzate. | RPT-02 | L |
| RPT-09 | Connettori BI (Power BI, Looker, Metabase) e dataset o cartelle di analisi | Dataset analitici documentati con estrazione incrementale, feed OData o schema SQL di sola lettura per azienda, con guide per Power BI e Metabase. | INT-08, RPT-10 | M |

**Integrazioni ed estensibilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INT-02 | Integrazione con suite d'ufficio (Teams, Slack, add-in Outlook, Excel, Google Workspace) | Prima notifiche e comandi su Slack e Teams via webhook, poi add-in Outlook collegato ai contatti e collegamento ai file di Drive e OneDrive dai Documenti. | INT-01, INT-06 | L |
| INT-06 | Agganci per piattaforme low-code (Zapier, Make, Power Automate) | Azione webhook firmata nelle regole, sottoscrizioni via API con ritentativi e registro, poi connettore pubblicato su una piattaforma. | INT-08 | M |
| INT-07 | Marketplace di moduli di partner e API dei moduli versionata | Pubblicare un contratto del modulo versionato con politica di compatibilità e aggiungere al portale registrazione dei partner, chiavi di firma, revisione e pagamenti. | INT-08 | L |
| INT-09 | Edizioni preconfigurate per settore (ruoli, flussi, dati di esempio) | Formato dichiarativo di edizione (moduli, ruoli, automazioni, campi personalizzati, cruscotti, dati demo) applicabile a un'istanza, con una prima edizione di settore di prova. | - | M |

**Localizzazione e conformità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| LOC-03 | Canali nazionali di fatturazione elettronica | Vedi FIN-33. | FIN-33 | M |
| LOC-05 | IVA, Intrastat, elenchi UE, export di audit (SAF-T) | Dati Intrastat su prodotti e righe, modelli INTRA 1 e 2 dalle operazioni con nature N3.2 e autofatture TD18, export per lo studio. | FIN-16 | M |
| LOC-08 | Predisposizione a SOC 2 e ISO 27001, residenza dati, cifratura a riposo | Cifrare backup e file privati, documentare la cifratura del disco nel deploy, aggiungere un audit log immutabile e la raccolta dei controlli ISO 27001. | - | L |

**Pacchetti di settore**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| IND-03 | Verticali servizi (agenzie, consulenza, saloni e attività su prenotazione) | Meccanismo di modelli di settore (moduli da attivare, ruoli, ricette di automazione, dati iniziali) e primo modello agenzia/consulenza; modulo agenda risorse per i saloni. | CRM-13 | M |

### 5. Edge (13)

**Finanza e contabilità**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| FIN-36 | OCR e AI su fatture e ricevute in bozza | Estrazione con modello visione da foto e PDF in bozza di riga spesa e di fattura passiva, sempre da confermare, sul gateway addons/ai/gateway. | FIN-05 | M |
| FIN-37 | Abbinamento bancario AI che impara dallo storico | Punteggio aggiuntivo da abbinamenti confermati (controparte, IBAN, causale), con spiegazione nel motivo e conferma umana. | FIN-11 | M |
| FIN-38 | Agente contabilità fornitori che prepara le fatture per l'approvazione | Agente pianificato che controlla ogni fattura ricevuta contro ordine e storico, segnala le anomalie e propone registrazione o contestazione all'approvatore. | FIN-05, FIN-36 | M |

**Vendite, CRM e marketing**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| CRM-20 | Agente che prepara ordini dalle email dei clienti | Gestore delle email dedicate che classifica la richiesta, abbina mittente e prodotti, estrae le righe anche dal PDF e prepara un preventivo in bozza da approvare, con i dubbi segnalati al commerciale. | CRM-08, AI-04 | M |

**Acquisti**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| PUR-14 | Agente AI per approvazioni e proposte di riapprovvigionamento | Strumento dedicato che calcola il fabbisogno e propone gli ordini con la motivazione, e assiste la decisione sulle approvazioni, sopra le proposte con conferma già esistenti. | PUR-04, PUR-06 | M |

**Magazzino**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| INV-21 | Agente AI per il riapprovvigionamento | Agente dedicato che incrocia previsione, scorte e fornitori e propone i riordini da confermare, spiegando il perché e imparando dalle proposte respinte. | INV-07, INV-20, PUR-06 | M |

**Persone e paghe**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| HR-16 | Agente note spese (codifica automatica e controlli sulle ricevute) | Lavoro in background che legge la ricevuta col modulo ai, propone data, importo e categoria, e segnala all'approvatore duplicati e incoerenze con la policy. | HR-05, FIN-36 | M |

**AI e automazione**

| ID | Funzione | Cosa costruire | Dipende da | Effort |
|---|---|---|---|---|
| AI-02 | OCR di fatture fornitore, ricevute e PDF con creazione di bozze | Pipeline allegato, OCR o modello con visione, campi estratti con punteggio di confidenza, bozza di FatturaPassiva o riga spesa confermata da una persona. | AI-09 | M |
| AI-04 | Agenti pronti: fornitori, ordini di vendita, spese, riordino, approvazione acquisti | Definire e collaudare i cinque agenti come offerta del catalogo o come pacchetti locali, ciascuno con operazioni ammesse, domande d'oro e casi di prova. | AI-05, AI-09, AI-02 | L |
| AI-05 | Costruttore di agenti con provider di modelli configurabile | Trigger per evento e assegnazione sugli assistenti (anche come azione di Automazioni), con budget e operazioni ammesse per agente ed esecuzione nel worker. | AI-09 | M |
| AI-07 | Previsioni: domanda, flusso di cassa, scostamenti dal piano | Previsione di cassa da scadenze attive e passive più storico, domanda per prodotto con proposta di riordino, rilevamento degli scostamenti dalla previsione con avvisi. | - | M |

## D. Osservazioni sull'architettura

In ordine di gravità. Il punto 1 è risolto; gli altri bloccano o rallentano funzioni Core quando i clienti crescono.

1. **Isolamento tra aziende: falla corretta il 2026-11-05.** Un utente senza aziende attive, o con la sola azienda disattivata, riceveva i record di tutte le aziende, perché `core/viste/base.py` filtrava solo se esisteva un'azienda corrente. Lo stesso accadeva nei menu dei filtri, nel kanban e nelle scelte dei form. Ora in quel caso le liste sono vuote, i dettagli danno 404, non si crea nulla, anche per il superuser e dall'API; i test sono in `core/tests/test_isolamento_aziende.py`. Resta da controllare il codice che filtra per conto suo fuori da `ModelView`. Un secondo controllo dello stesso giorno, sul codice e con una scansione di tutti gli URL, ha trovato altri casi, tutti corretti e coperti da test: viste su righe figlie (scadenze, incassi, valutazioni, notifiche, scadenze passive), XML delle trasmissioni, invito al portale, compito da ticket, collaudi, compiti nel form delle ore, pagine di Analisi condivise. `request.azienda` ora è None davvero, non un oggetto lazy, così i controlli scattano e le pagine non vanno in errore. La scansione ha provato gli id da 1 a 12 con POST vuote e ha saltato `awf`, `agate`, `ai` e `github`, controllati solo sul codice. Restano senza azienda canali e chat di Comunicazioni, utenti e ruoli, e la guida pubblica.
2. **Permessi.** Le regole di riga sono scritte nel codice di ogni vista e non esistono permessi per campo (PLT-03). I nuovi utenti ricevono per default tutte le aziende attive (`core/signals.py`, `crea_profilo`).
3. **Storico delle modifiche.** È legato a `save_model` e al chatter, non ai modelli: copre 25 viste su 87 e non vede le modifiche fatte da API, lavori e shell (PLT-04).
4. **Valuta cablata.** Euro in `addons/fatturazione/fatturapa.py` (`Divisa`), «€» nelle etichette in oltre 200 punti, nessun campo valuta (PLT-02). Ogni modello nuovo, compresi quelli di acquisti, aggiunge debito.
5. **Lingua cablata.** Nessun `gettext` nel codice: tutto il testo è in italiano (PLT-15).
6. **Regole fiscali nei modelli.** `AliquotaIva` e `TerminePagamento` sono globali e non per azienda; le righe ripiegano sul codice «22» nel `save()` (FIN-15, LOC-01).
7. **Approvazioni per app.** `personale/flusso.py`, `spese/flusso.py` e ora `acquisti/operazioni.py` hanno ciascuno il proprio flusso. Acquisti è il primo con più livelli e il suo schema è il punto di partenza per un motore comune nel kernel (PLT-07).
8. **Magazzino.** `Movimento` non ha costo né ubicazione, quindi niente valorizzazione (INV-09) né scaffali (INV-04). Le righe dei documenti non puntano alla riga d'ordine: il riscontro di acquisti lavora per prodotto. `magazzino.operazioni.spedisci` non blocca le righe durante il controllo della giacenza: due spedizioni contemporanee possono superarla.
9. **API.** 22 viste su 87 con `api=True`, solo CRUD, senza azioni né webhook in uscita; `TokenApi` senza ambiti né scadenza (PLT-14, INT-08).
10. **Portale dentro assistenza.** `addons/assistenza/portale.py` dipende da helpdesk e progetti, con i percorsi in `config/settings.py`: va estratto prima di aggiungere fatture e ordini (COM-01).
11. **Duplicazioni.** Calendario lavorativo in `addons/personale/calendario_lavoro.py` e `addons/capacita/piano.py`; due livelli di SLA in `addons/helpdesk` e `addons/assistenza/sla.py`; `Dipendente` e `User` separati, con timesheet e capacità legati a `User`.
12. **Dati e rete.** `Pagina` di Analisi non ha un campo azienda (i dati dei grafici restano comunque filtrati); un solo database senza repliche di lettura (RPT-10); backup non cifrati (`core/backup.py`, LOC-08); catalogo agenti esterno alla piattaforma (`addons/awf/fabbrica.py`).

## E. Intervento sull'app acquisti

**Perché acquisti.** È l'unica sezione nel perimetro senza alcuna voce completa, ha 7 lacune Core, è piccola e ogni lacuna si può chiudere senza decisioni aperte. Magazzino ha più lacune, ma le più importanti (costi, lotti, ubicazioni) sono lavori lunghi da concordare prima.

| Voce | Prima | Dopo | Che cosa fa ora |
|---|---|---|---|
| PUR-01 Gare | PARTIAL | HAVE | Una richiesta per fornitore, invio a tutti, confronto dei prezzi, aggiudicazione che annulla le altre |
| PUR-02 Listini | MISSING | HAVE | Scaglioni, minimi, codice del fornitore, tempi, validità, preferito; il prezzo si propone sulla riga e il codice va in stampa |
| PUR-03 Riscontro | PARTIAL | HAVE | Ordinato, ricevuto, reso e fatturato sull'ordine; residuo con un clic; la fattura SDI trova da sola l'ordine |
| PUR-04 Approvazioni | MISSING | HAVE | Regole per soglia e categoria, più livelli, chi compra non si approva, Ada non può approvare |
| PUR-05 Contratti quadro | MISSING | HAVE | Prezzi concordati, ordini di richiamo, residuo non superabile, validità |
| PUR-06 Riordino | MISSING | HAVE | Proposte su giacenza, in arrivo e impegni; richieste in bozza, da pagina o col lavoro del mattino per le regole che lo chiedono |
| PUR-07 Scheda fornitore | PARTIAL | HAVE | Pagamento, IVA, IBAN validato e tempi, proposti sui nuovi ordini |
| PUR-08 Resi | PARTIAL | HAVE | Reso con DDT e scarico; la nota di credito rientra nel riscontro |
| PUR-13 Valutazione | MISSING | PARTIAL | Puntualità, completezza, tempi, resi, fatture coerenti; manca la misura diretta del prezzo |
| FIN-05, INV-07 | PARTIAL | HAVE | Chiuse il 2026-11-09 (vedi sezione B) |

Scelte da conoscere: nulla parte da solo verso i fornitori, nemmeno il riordino automatico, che crea solo bozze. Lo scostamento della fattura si segnala e non blocca la registrazione. Con regole attive, confermare un ordine sopra soglia lo porta in «Da approvare»: senza regole non cambia nulla.

Restano aperte in acquisti: PUR-09 costi accessori (richiede la valorizzazione INV-09), PUR-10 spedizione diretta al cliente, PUR-11 conto lavoro, PUR-12 portale fornitori, PUR-14 agente AI.

