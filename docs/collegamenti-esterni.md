# Collegare Salesforce, Zoho, Google e Microsoft

Come registrare le app sui servizi esterni per i moduli **Connettori** (Salesforce, Zoho CRM) e **Posta e calendario** (Google, Microsoft 365). Servono anche per la prima prova con account veri: finora i connettori sono stati provati solo contro servizi simulati con il loro formato.

## Account di prova, tutti gratuiti

| Servizio | Account | Note |
|---|---|---|
| Salesforce | Developer Edition (developer.salesforce.com/signup) | Organizzazione completa, con le fasi standard delle opportunità |
| Zoho CRM | Piano gratuito o prova di 15 giorni, data center EU | Il piano gratuito ha le API con limiti bassi: bastano per la prova |
| Google | Un account Gmail o Workspace | L'app OAuth in modalità «test» accetta fino a 100 utenti senza la verifica di Google |
| Microsoft | Un account Outlook.com personale, o un tenant Microsoft 365 | Con tenant «common» vanno bene entrambi |

## Salesforce (modulo Connettori)

1. Setup → App Manager → **New Connected App** (o External Client App).
2. Abilita OAuth; callback URL qualunque (non si usa), ambiti «Manage user data via APIs (api)».
3. In «Client Credentials Flow» spunta l'abilitazione; poi Manage → Edit Policies → **Run As**: un utente con accesso in lettura e scrittura a Contact, Account, Opportunity (meglio un utente di integrazione dedicato).
4. Copia Consumer Key e Consumer Secret.
5. In adabox, Connettori → Collegamenti: sistema Salesforce, modalità Vera, **indirizzo** = il My Domain (`azienda.my.salesforce.com`), client id = Consumer Key, client secret = Consumer Secret. «Verifica il collegamento».

Da controllare alla prima prova: che `OpportunityStage.ApiName` si legga (se no il connettore usa l'etichetta) e che le fasi abbinate siano quelle attese.

## Zoho CRM (modulo Connettori)

1. api-console.zoho.eu (o il data center dell'account) → **Self Client** → Client ID e Client Secret.
2. «Generate Code» con gli ambiti:
   `ZohoCRM.modules.contacts.ALL,ZohoCRM.modules.accounts.ALL,ZohoCRM.modules.deals.ALL,ZohoCRM.settings.fields.READ,ZohoSearch.securesearch.READ`
3. Scambia il codice con un refresh token entro la sua durata (POST a `https://accounts.zoho.eu/oauth/v2/token` con `grant_type=authorization_code`, `client_id`, `client_secret`, `code`).
4. In adabox: sistema Zoho CRM, modalità Vera, **indirizzo** = il data center (`eu`, `com`, `in`, `com.au`, `jp`, `ca`, `sa`, `com.cn`), client id, client secret e refresh token.

Da controllare alla prima prova: se il picklist Stage dei Deals porta la probabilità e il tipo (vinta, persa); se manca il campo Pipeline obbligatorio quando le pipeline sono attive.

## Odoo (modulo Connettori)

Odoo 19 (API JSON-2). Su Odoo Online l'API esterna c'è solo con il piano Custom; su Odoo.sh e installato in casa
sempre. Helpdesk è solo nella versione Enterprise (il connettore per ora copre contatti e CRM).

1. In adabox, Connettori → Collegamenti: sistema Odoo, modalità Vera, **indirizzo** = l'indirizzo https di Odoo, **database**
   = il nome del database (serve se l'indirizzo ne ha più d'uno).
2. Scegli come leggere:
   - **ogni utente con la sua chiave** (consigliato): ogni utente apre «I miei account esterni» dal menu del profilo e
     incolla la sua chiave API (in Odoo: Preferenze → Sicurezza dell'account → Nuova chiave API). In adabox arriva, e
     ciascuno vede, solo ciò che Odoo mostra a lui; chi ha il permesso «Vede anche i dati esterni che il sistema mostra ad
     altri utenti» vede tutto;
   - **un utente tecnico**: la sua chiave API nel collegamento; tutti i dati arrivano una volta, e chi li vede lo decidono
     le regole sulle righe di adabox.
3. Il venditore di un'opportunità diventa il commerciale in adabox se ha collegato il suo account.
4. Con «le modifiche fatte in adabox tornano lì» (solo con «ogni utente con la sua chiave»), contatti e opportunità
   salvati in adabox si scrivono in Odoo con la chiave di chi li salva, quindi con i suoi permessi: se Odoo rifiuta,
   sul record compare una nota. Chi non ha collegato il suo account e i lavori di sistema non scrivono in Odoo. Se lo
   stesso record cambia nei due posti tra un giro e l'altro, vale l'ultima scrittura.

Da controllare alla prima prova: le fasi del CRM (si abbinano per nome, se no per probabilità, che in Odoo non è nella
fase e si stima dall'ordine); le aziende si agganciano per partita IVA, poi per nome; gli utenti di Odoo e l'azienda
dell'istanza non si importano come clienti.

## Google (modulo Posta e calendario)

1. console.cloud.google.com → nuovo progetto → abilita **Gmail API** e **Google Calendar API**.
2. Schermata di consenso OAuth: tipo «Esterno» (o «Interno» con Workspace), in modalità **test** aggiungi gli utenti di prova.
3. Credenziali → ID client OAuth → **Applicazione web**; URI di reindirizzamento autorizzato: `https://<istanza>/posta/ritorno/` (lo mostra anche la pagina Posta e calendario all'amministratore).
4. In adabox: Servizi di posta → Google, client ID e segreto client.

Gli ambiti `gmail.readonly` e `gmail.send` sono «riservati»: per account fuori dalla propria organizzazione, fuori dalla modalità test, Google chiede la verifica dell'app.

## Microsoft (modulo Posta e calendario)

1. entra.microsoft.com → Registrazioni app → **Nuova registrazione**; tipi di account: «qualsiasi directory e account Microsoft personali» (tenant `common`) o solo la propria organizzazione.
2. Piattaforma **Web**, URI di reindirizzamento `https://<istanza>/posta/ritorno/`.
3. Autorizzazioni API delegate di Microsoft Graph: `User.Read`, `Mail.Read`, `Mail.Send`, `Calendars.ReadWrite`, `offline_access`.
4. Certificati e segreti → nuovo segreto client.
5. In adabox: Servizi di posta → Microsoft, client ID (ID applicazione), segreto e tenant (`common`, `organizations` o l'ID del tenant).

## La prova

- Connettori: un collegamento per sistema in modalità «comanda l'esterno», poi «comanda adabox»; controllare persone, aziende, opportunità e fasi nei due versi.
- Posta e calendario: collegare la casella, scrivere e ricevere un'email con un contatto, creare un appuntamento da tutte e due le parti, scrivere a un cliente dal chatter e rispondere dalla sua casella.
