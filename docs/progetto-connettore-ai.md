# Progetto tecnico: adabox dentro Claude e ChatGPT

Come far usare i dati di adabox dalle chat di Claude e ChatGPT con gli abbonamenti che i clienti hanno già, più due funzioni collegate: la chiave API personale dentro Ada e l'importazione delle chat fatte altrove. Verificato sulle fonti ufficiali il 2026-11-11 (elenco in fondo); dove una fonte non era raggiungibile è segnato **da verificare**.

## In sintesi

| Parte | Cosa | Stato delle fonti |
|---|---|---|
| A. Connettore MCP | Ogni istanza di adabox espone un server MCP con OAuth: l'utente lo aggiunge come connettore personalizzato in Claude o ChatGPT e chatta lì, con il suo abbonamento, sui dati che può vedere in adabox | Claude: chiaro. ChatGPT: piani da verificare |
| B. Chiave personale | Nella chat di Ada l'utente sceglie anche il proprio account API Anthropic o OpenAI | Nessun vincolo esterno |
| C. Importazione | L'utente carica l'esportazione di ChatGPT o Claude e ritrova le chat in Ada | Formati non documentati |

**Cosa non si fa, e perché.** Usare dentro adabox l'abbonamento Claude o ChatGPT dell'utente (sessioni, cookie, token di accesso dell'abbonamento) è vietato: Anthropic scrive che terze parti non possono offrire l'accesso con Claude.ai, instradare richieste con le credenziali dei piani Free, Pro, Max o Ultra, né raccogliere, conservare o fare da intermediario a credenziali o token di sessione di Claude.ai; chi sviluppa deve usare le chiavi API. OpenAI vieta di condividere le credenziali o rendere l'account disponibile ad altri. Il connettore va nel verso opposto (è Claude che chiama adabox) e non tocca credenziali dei fornitori.

**Decisioni da prendere prima di iniziare** (sezione 8): libreria o codice nostro per il server OAuth; scritture eseguite subito o confermate in adabox; mascheramento dei dati attivo di default o no; quali clienti hanno piani che ammettono i connettori.

---

## A. Il connettore MCP

### A1. Come lo vede l'utente

1. In adabox, nella pagina del profilo «Claude e ChatGPT», trova l'indirizzo del connettore della sua istanza (`https://<istanza>/mcp/`) e le istruzioni.
2. In Claude (Impostazioni → Connettori → Aggiungi connettore personalizzato) o in ChatGPT (Plugin → «+» → server MCP personalizzato) incolla l'indirizzo.
3. Il fornitore lo manda alla pagina di accesso di adabox (con la verifica in due passaggi se attiva), poi a una pagina di consenso: quale azienda, quali app, sola lettura o anche scritture. Conferma.
4. Da quel momento, nelle sue chat di Claude o ChatGPT, il modello può cercare in adabox con i suoi permessi. Le chat restano nella cronologia del fornitore.
5. In adabox vede i collegamenti attivi, l'ultimo uso e le chiamate fatte, e può revocarli.

Vincoli dei fornitori:
- **Claude**: connettori personalizzati su Free (uno solo), Pro, Max, Ultra, Team ed Enterprise. In Team li aggiungono solo i proprietari (Owner), in Enterprise i proprietari e i ruoli abilitati; poi ogni membro si collega da sé. Ogni chiamata a uno strumento chiede l'approvazione, con «consenti sempre».
- **ChatGPT**: si chiamano «Plugin». I piani che ammettono server MCP personalizzati con lettura e scrittura **sono da verificare** (fonti secondarie: beta per Business, Enterprise ed Edu con la modalità sviluppatore attivata dall'amministratore; Pro forse solo lettura; Plus non chiaro; Free escluso).
- Ogni istanza di adabox è un server diverso: per un cliente il connettore è sempre «personalizzato». La pubblicazione nelle directory dei fornitori ha senso solo per un'eventuale demo pubblica (sezione A9).

### A2. Componenti

```
Claude / ChatGPT ──HTTPS──▶ /mcp/            server MCP (Streamable HTTP)
        │                     │  verifica il token (audience = /mcp/ di questa istanza)
        │                     ▼
        │               catalogo strumenti ──▶ strumenti di Ada (ai.strumenti), come l'utente, nell'azienda scelta
        │                     │
        │                     ▼
        │               mascheramento (ai.protezione) ── facoltativo, per azienda
        │
        └──OAuth──────▶ /oauth/…             server di autorizzazione (accesso, consenso, token)
                        /.well-known/oauth-protected-resource/mcp
                        /.well-known/oauth-authorization-server
```

Nuovo modulo `connettore_ai` («Claude e ChatGPT»), che dipende da `ai`. Riusa:
- `ai.strumenti` (registro con rischio, permesso, anteprima, schema) e il motore delle viste del kernel: gli strumenti sono gli stessi di Ada, con gli stessi controlli;
- `awf/operazioni.py`: la costruzione di `tools/list` con le annotazioni MCP e l'argomento `vista` ristretto, già scritta per Agate;
- `awf/mcp.py`: il trasporto JSON-RPC su POST, già senza sessione;
- `ai.protezione`: mascheramento con segnaposto stabili e ripristino robusto;
- `core.licenza` / `core.funzioni`: il connettore come funzione attivabile dalla licenza.

### A3. Protocollo

- **Versioni**: la specifica più recente è la **2026-07-28**, senza stato (niente `initialize`, niente `Mcp-Session-Id`, nuovo `server/discover`, intestazioni `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` obbligatorie). Claude documenta il supporto fino alla **2025-11-25**. Il server deve servire entrambe: un nucleo senza stato (come già `awf/mcp.py`) con due «facce», `initialize` + sessione facoltativa per la 2025-11-25, `server/discover` + controllo delle intestazioni per la 2026-07-28. La versione si legge da `MCP-Protocol-Version` o dal corpo.
- **Trasporto**: Streamable HTTP, un solo endpoint, POST; risposte JSON (lo stream SSE per singola risposta è facoltativo e all'inizio non serve). GET e DELETE: 405 nella 2026-07-28.
- **Origin**: va controllato (obbligo della specifica): ammessi solo i domini dei fornitori e l'istanza stessa.
- **Limiti di Claude**: risultato di uno strumento fino a circa 150.000 caratteri, timeout di 240 secondi. Gli strumenti di Ada troncano già a 20.000 caratteri.

### A4. Autorizzazione (OAuth 2.1)

Requisiti comuni della specifica MCP, di Claude e di ChatGPT:

| Requisito | Dettaglio |
|---|---|
| Protected Resource Metadata (RFC 9728) | `/.well-known/oauth-protected-resource/mcp` con `authorization_servers`; sul 401 `WWW-Authenticate: Bearer resource_metadata="…"`. Claude usa solo il primo server dell'elenco e parte solo da un 401 |
| Metadati del server (RFC 8414) | `/.well-known/oauth-authorization-server` con `code_challenge_methods_supported: ["S256"]` (senza, i client si fermano), `client_id_metadata_document_supported: true`, `token_endpoint_auth_methods_supported` con `none` |
| Registrazione del client | **CIMD** (Client ID Metadata Documents, preferito da entrambi: il `client_id` è un URL, es. `https://chatgpt.com/oauth/client.json`, che il server scarica e controlla) e **DCR** (RFC 7591, deprecato nella specifica 2026 ma ancora usato da Claude se manca CIMD o manca `none`) |
| PKCE | S256 obbligatorio |
| Resource Indicators (RFC 8707) | `resource` nella richiesta di autorizzazione e di token; il token vale solo per `https://<istanza>/mcp/` e il server controlla l'audience |
| Redirect | Claude: `https://claude.ai/api/mcp/auth_callback` (web, Desktop, mobile); Claude Code: loopback su qualsiasi porta. ChatGPT: `https://chatgpt.com/connector_platform_oauth_redirect` (con `iss` RFC 9207) oppure `https://chatgpt.com/connector/oauth/{callback_id}` |
| `iss` (RFC 9207) | Nel ritorno dell'autorizzazione: richiesto da ChatGPT per il primo redirect |
| Token endpoint | Corpo form-urlencoded; risposta entro 10 secondi (Claude), refresh entro 30 |
| Refresh token | Ruotati a ogni uso (client pubblici) |
| Non supportati | `client_credentials`, chiavi API statiche lato ChatGPT |
| Token passthrough | Vietato: il server accetta solo i propri token e non li inoltra |

Scelte per adabox:
- **Accesso**: la pagina di login di adabox con la verifica in due passaggi; il consenso è una pagina nostra: azienda (se l'utente ne ha più d'una), app comprese (come `TokenApi.moduli`), sola lettura o scritture, durata.
- **Token**: di accesso brevi (un'ora), opachi, salvati solo come impronta come `TokenApi`; refresh ruotati con scadenza (90 giorni senza uso), revocabili dalla pagina del profilo e dall'amministratore. Il token porta utente, azienda, app, sola lettura, client (Claude o ChatGPT, dal `client_id`).
- **Client ammessi**: di default solo i documenti CIMD dei due fornitori e i redirect sopra; la DCR crea client solo con quei redirect. Un'impostazione dell'istanza permette di aggiungerne altri (es. Claude Code in loopback).
- **Utenti disattivati, cambi di permessi**: ogni chiamata ricontrolla l'utente e i permessi del momento, come gli strumenti di Ada; il token non congela i permessi.
- **Libreria**: django-oauth-toolkit copre PKCE, refresh, revoca, ma non CIMD né RFC 9728 né RFC 9207: andrebbero aggiunti sopra. In alternativa un server minimo nostro, con test sulle RFC. Da decidere dopo uno spike (sezione 7, fase 0).

### A5. Strumenti esposti

Dal registro di Ada, con un elenco chiuso come le «Operazioni ammesse» di Agate:

| Strumento MCP | Da Ada | Annotazioni |
|---|---|---|
| `elenca_viste`, `descrivi_vista` | strumenti delle viste | `readOnlyHint: true` |
| `cerca_record`, `leggi_record`, `aggrega` | strumenti delle viste | `readOnlyHint: true` |
| `cerca_conoscenza`, `leggi_documento` | conoscenza (wiki per sezioni, documenti, note) | `readOnlyHint: true` |
| `proponi_modifica` (fase 3) | scritture con anteprima | `readOnlyHint: false`, `destructiveHint: false` |

- Ogni strumento con `title` e annotazioni **esplicite** (lo chiedono le regole di entrambe le directory; per la specifica un'annotazione assente vale «distruttiva»). Letture e scritture in strumenti separati. Nomi entro 64 caratteri.
- `outputSchema` e `structuredContent` per i risultati strutturati, con lo stesso JSON anche come testo.
- Esclusi gli strumenti che non hanno senso fuori da Ada: chiamate ad altri modelli, ricerca web, memoria e documenti della chat, pianificazioni (stessa lista di esclusione di Agate).
- Descrizioni senza istruzioni rivolte al modello oltre all'uso dello strumento (revisione anti prompt injection delle directory).

**Scritture.** Claude e ChatGPT chiedono già conferma per gli strumenti non di sola lettura, ma la conferma avviene nella loro interfaccia e non mostra l'anteprima di adabox. Proposta: nella fase 3 `proponi_modifica` crea una `Proposta` di adabox (anteprima validata con i form, nessuna modifica) e restituisce il link per confermarla in adabox. Doppio passaggio, ma nessuna scrittura parte da una chat esterna senza che l'utente veda l'anteprima vera. L'esecuzione diretta potrà essere un'opzione per azienda, solo per operazioni non irreversibili.

### A6. Mascheramento dei dati

Opzione per azienda «Proteggi i dati personali verso Claude e ChatGPT»:
- i risultati degli strumenti passano da `ai.protezione` prima di uscire: nomi, codici fiscali, IBAN, email diventano segnaposto stabili (`[FULLNAME_1]`);
- gli argomenti delle chiamate successive vengono smascherati in ingresso: se il modello cerca «fatture di [FULLNAME_1]», adabox cerca il nome vero;
- la mappa dei segnaposto sta sul server, per collegamento, con scadenza (es. 24 ore senza uso), perché il protocollo non ha più sessioni;
- **limite**: nell'interfaccia del fornitore l'utente legge i segnaposto, adabox non può riscrivere le risposte. Per questo l'opzione va spiegata e non attivata di default senza una decisione dell'azienda.

### A7. Permessi, multi-azienda, registro

- Tutto gira come l'utente, nell'azienda scelta al consenso, con le regole delle viste (queryset, permessi, campi per ruolo) e i dati sensibili esclusi come per Ada (`SENSIBILE`).
- Un utente con più aziende: un collegamento per azienda, oppure l'azienda come argomento ristretto a quelle del token (decisione: la prima è più semplice e più chiara nel registro).
- Registro di ogni chiamata (strumento, vista, esito, durata, client, senza i valori) come `awf.Chiamata`; limiti di frequenza per collegamento come l'API (`API_LIMITE`).
- Pagina dell'amministratore: collegamenti attivi per utente, revoca, interruttore generale e per app.

### A8. Rete

- Il connettore richiede un'istanza raggiungibile da internet in HTTPS. Le istanze dietro VPN o firewall: elenco IP facoltativo (Claude esce da `160.79.104.0/21`, anche verso il server di autorizzazione; OpenAI pubblica i suoi IP e offre certificati mTLS).
- Le chiamate ai metadati e ai documenti CIMD in uscita passano dai controlli di `core.rete` (solo https pubblici, niente redirect).

### A9. Directory dei fornitori (facoltativo)

Pubblicare un connettore «adabox» nelle directory ha senso solo per una demo pubblica o un servizio SaaS centrale. Requisiti principali: verifica dell'organizzazione, informativa privacy e contatti, account di prova popolato senza 2FA, documentazione pubblica, annotazioni esplicite, niente trasferimenti di denaro, minimizzazione dei dati (ChatGPT esclude credenziali, dati di carte, dati sanitari e documenti d'identità nei risultati: con dati di gestionale italiano va valutato il codice fiscale). Per le istanze dei clienti basta il connettore personalizzato.

---

## B. La chiave API personale in Ada

- Nuovo modello `ChiaveUtente` (utente, provider tra quelli esistenti: Anthropic o compatibile OpenAI, chiave cifrata come `Provider.chiave_cifrata`), abilitabile dall'amministratore per azienda.
- Nella chat, la scelta del modello mostra anche «Il mio account Anthropic/OpenAI»; il turno usa la chiave dell'utente. La spesa si conta a parte e non pesa sul tetto dell'azienda.
- Si applicano le stesse regole di Ada: protezione dei dati personali verso modelli non locali, strumenti con i permessi dell'utente, registro.
- Va detto chiaramente che è fatturato a consumo dall'API del fornitore: non usa l'abbonamento mensile.
- Sforzo contenuto: il gateway gestisce già Anthropic e i compatibili OpenAI, con chiavi per azienda.

## C. Importare le chat di ChatGPT e Claude

- **Fonti**: l'archivio di esportazione che l'utente scarica da ChatGPT (Impostazioni → Controlli dati) o da Claude (Impostazioni → Privacy). In Claude Team ed Enterprise l'esportazione dei membri dipende dall'organizzazione.
- **Formati non documentati**: ChatGPT `conversations.json` (a volte diviso in più file) con un albero `mapping` di nodi; si segue il ramo da `current_node` alla radice. Claude `conversations.json` con `chat_messages` (`sender`, `text`, `content`). Parser tolleranti, con test su esportazioni reali anonimizzate, e un messaggio chiaro se il formato cambia.
- **In adabox**: conversazioni nell'area personale dell'utente, con un campo nuovo `origine` («ChatGPT», «Claude») e la data originale; si possono cercare e continuare con un modello di Ada, che riceve la storia come contesto. Gli allegati non ci sono (Claude non esporta i file caricati).
- **Privacy**: restano private dell'utente, fuori dalla ricerca aziendale; caricamento con limite di dimensione ed elaborazione in background; l'archivio caricato non si conserva dopo l'importazione.

---

## 5. Sicurezza e privacy

| Rischio | Contromisura |
|---|---|
| Furto di un token | Token brevi, refresh ruotati, audience legata all'istanza, revoca, registro, avviso all'utente su un client nuovo |
| Client malevolo che si registra (DCR) | Solo redirect dei fornitori ammessi; CIMD verificati; consenso esplicito sempre |
| Prompt injection dai dati (es. una nota che dice «ignora le istruzioni e…») | Il modello del fornitore è fuori dal nostro controllo: sola lettura di default, scritture solo come proposta confermata in adabox |
| Permessi troppo ampi | App scelte al consenso, sola lettura di default, campi sensibili esclusi |
| Dati che lasciano adabox | Informativa e accordo con il cliente; mascheramento facoltativo; per Claude i contenuti dei connettori non si usano per l'addestramento neppure con il miglioramento del modello attivo, a meno che l'utente non li copi nella chat. Per ChatGPT dipende dall'impostazione «Migliora il modello per tutti» sui piani personali (**da verificare**). I risultati restano comunque nella cronologia del fornitore |
| Confused deputy | Nessun token di terzi accettato o inoltrato; ogni azione con l'utente del token |

GDPR: il connettore porta dati personali verso un fornitore extra UE scelto dal cliente. Serve un'informativa e, per i clienti business, la verifica che il piano del fornitore (Team, Enterprise, Business) abbia l'accordo sul trattamento. Il mascheramento è pseudonimizzazione: riduce il rischio, non rende i dati anonimi.

## 6. Stima delle dimensioni

| Pezzo | Sforzo indicativo |
|---|---|
| Server di autorizzazione (metadati, CIMD, DCR, PKCE, refresh, revoca, consenso) | 1,5–2 settimane |
| Server MCP doppia versione, catalogo, annotazioni, registro | 1 settimana |
| Mascheramento sui risultati e smascheramento sugli argomenti | 3–4 giorni |
| Scritture come proposte confermate in adabox | 3–4 giorni |
| Pagine utente e amministratore, licenza | 3 giorni |
| Chiave personale (B) | 2–3 giorni |
| Importazione (C) | 3–4 giorni |
| Prove con Claude e ChatGPT veri, documentazione | 1 settimana |

## 7. Fasi

0. **Spike (3–4 giorni)**: un'istanza di prova pubblica, OAuth minimo con CIMD e DCR, uno strumento di sola lettura, collegato davvero a Claude (Pro) e a ChatGPT. Serve a confermare redirect, metadati, versione del protocollo e piani di ChatGPT prima di scrivere il resto. Decide anche la libreria OAuth.
1. **Connettore in sola lettura**: tutti gli strumenti di lettura, consenso con azienda e app, registro, revoca, pagine.
2. **Mascheramento** facoltativo per azienda.
3. **Scritture** come proposte confermate in adabox.
4. **Chiave personale** in Ada.
5. **Importazione** delle chat.

Le fasi 4 e 5 non dipendono dalle altre e si possono anticipare.

## 8. Decisioni e punti aperti

1. **Libreria OAuth**: django-oauth-toolkit esteso o server nostro (dopo lo spike).
2. **Scritture**: solo proposte confermate in adabox (proposta) o anche esecuzione diretta per azienda.
3. **Mascheramento**: spento di default con spiegazione (proposta) o acceso.
4. **Clienti**: quali hanno piani che ammettono connettori personalizzati, soprattutto su ChatGPT (piani da verificare); per i clienti Claude Team serve un proprietario che aggiunga il connettore.
5. **Multi-azienda**: un collegamento per azienda (proposta) o azienda come argomento.
6. **Licenza**: il connettore come funzione a pagamento del modulo AI?
7. **Versione 2026-07-28**: quando Claude e ChatGPT la supporteranno, la faccia 2025-11-25 si potrà togliere.

## Fonti

- Specifica MCP 2026-07-28: changelog, trasporto, autorizzazione, strumenti — https://modelcontextprotocol.io/specification/2026-07-28/changelog, …/basic/transports/streamable-http, …/basic/authorization, …/server/tools
- Claude, connettori personalizzati: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- Claude, autenticazione e requisiti del server: https://claude.com/docs/connectors/building/authentication, https://claude.com/docs/connectors/building
- Claude, criteri della directory: https://claude.com/docs/connectors/building/review-criteria, https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy
- Claude, IP in uscita: https://platform.claude.com/docs/en/api/ip-addresses
- Anthropic, uso delle credenziali dell'abbonamento: https://code.claude.com/docs/en/legal-and-compliance
- Claude, addestramento e conservazione: https://privacy.claude.com/en/articles/10023580, https://privacy.claude.com/en/articles/10023548
- Claude, esportazione dei dati: https://support.claude.com/en/articles/9450526
- ChatGPT, autenticazione delle app: https://developers.openai.com/apps-sdk/build/auth
- ChatGPT, collegare un server MCP: https://developers.openai.com/apps-sdk/deploy/connect-chatgpt
- ChatGPT, linee guida per la pubblicazione: https://developers.openai.com/apps-sdk/app-submission-guidelines
- OpenAI, condizioni d'uso: https://openai.com/policies/row-terms-of-use/
