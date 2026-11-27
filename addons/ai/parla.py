"""«Parla con Ada»: la conversazione a voce, a schermo intero, pensata per il telefono.

Il browser ascolta e capisce da solo quando l'utente ha finito di parlare; l'audio va a Whisper (voce.trascrivi), la
domanda al motore della chat come un messaggio qualsiasi (la conversazione resta una chat normale, nella cronologia)
con una nota che chiede risposte brevi e parlate. Mentre la risposta si scrive il browser chiede l'audio un pezzo alla
volta, indicando il tratto del testo del turno: il server legge solo il testo della risposta, mai un testo mandato dal
browser, così il servizio di lettura (magari a pagamento) non legge altro."""
from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.decoratori import post_con_accesso
from core import parametri

from . import apertura, aree, funzioni, limiti, motore, voce
from .models import Apertura, Conversazione, Turno

NOTA_VOCE = (
    "L'utente si chiama {nome}. L'utente ti parla a voce dal telefono e ascolta la risposta letta ad alta voce. Rispondi in poche frasi brevi e "
    "parlate, come in una telefonata: niente tabelle, elenchi puntati, titoli, emoji, codice o link. Numeri, importi, "
    "date e orari scrivili in cifre (13:30, 1.250 €, 16/11): la lettura li pronuncia da sola. Se i risultati sono più di tre o quattro, dai il totale e i più importanti e chiedi se "
    "vuole il dettaglio. Per agenda, scadenze e attività parti da quello che deve ancora succedere; di quello già "
    "passato di' solo quanti sono e chiedi se vuole sentirli. Prima di creare o modificare qualcosa ripeti in una "
    "frase cosa farai e chiedi conferma. Se ti chiedono qualcosa che a voce non puoi fare (grafici, tabelle, documenti "
    "lunghi, attività pianificate), dillo in una frase e suggerisci di aprire la chat con «Apri nella chat».")
# il saluto: la prima volta come in una telefonata, poi niente formule ripetute
NOTA_PRIMO_TURNO = ("È l'inizio della conversazione: se l'utente ti saluta soltanto, rispondi «Ciao {nome}, come posso "
                    "aiutarti?»; se chiede già qualcosa, rispondi subito chiamandolo per nome.")
NOTA_TURNI_DOPO = "Vi siete già salutati: non salutare di nuovo e non usare formule fatte come «come posso aiutarti?»."
NOTA_INTERROTTA = ("Nel turno precedente l'utente ti ha interrotto mentre parlavi: ha sentito solo fin qui: «{sentito}». "
                   "Tienine conto e non ripetere quello che ha già sentito, a meno che lo chieda.")
# A voce solo gli strumenti utili al telefono: da 39 a 18, circa il 40% di attesa in meno sul primo passo e meno token.
# Fuori quelli visivi (grafici, tabelle, Analisi), i documenti lunghi, le pianificazioni, gli agenti e l'eliminazione.
STRUMENTI_VOCE = frozenset({
    "data_e_ora", "calendario_agenda", "cerca_record", "leggi_record", "aggrega_record", "elenco_viste", "descrivi_vista",
    "cerca_conoscenza", "leggi_documento", "comunicazioni_cerca", "comunicazioni_leggi", "comunicazioni_scrivi",
    "crea_record", "modifica_record", "pianifica_attivita", "esegui_bottone", "ricorda", "previsione", "notifiche_leggi"})
# Frasi d'attesa: «attimo» se la risposta tarda, le altre quando parte uno strumento, prima della risposta. Più
# varianti per non ripetere sempre la stessa; la pagina ne sceglie una a caso (audio preparato una volta, poi in cache).
FRASI = {"calendario": ["Ok, guardo il calendario.", "Vediamo l'agenda.", "Controllo gli appuntamenti."],
         "dati": ["Ok, ora controllo.", "Ora vedo i dati.", "Controllo nei dati."],
         "documenti": ["Cerco nei documenti.", "Ok, guardo nei documenti.", "Vediamo nei documenti."],
         "comunicazioni": ["Guardo le comunicazioni.", "Ok, controllo i messaggi.", "Vediamo i messaggi."],
         "attimo": ["Ok, un attimo.", "Va bene, ci penso.", "Ok, vediamo."]}
FRASE_PER_STRUMENTO = {"calendario_agenda": "calendario", "cerca_record": "dati", "leggi_record": "dati",
                       "aggrega_record": "dati", "previsione": "dati", "cerca_conoscenza": "documenti",
                       "leggi_documento": "documenti", "comunicazioni_cerca": "comunicazioni",
                       "comunicazioni_leggi": "comunicazioni", "notifiche_leggi": "comunicazioni"}
CARATTERI_PEZZO = 600                    # un pezzo da leggere: il browser li fa di 110-300 caratteri
SENTITO_MASSIMO = 500


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def frase(request, chiave):
    """L'audio di una frase d'attesa: solo quelle dell'elenco, mai un testo del browser."""
    servizio = voce.servizio_per(getattr(request, "azienda", None))
    gruppo, trattino, numero = chiave.partition("-")      # «calendario» è la prima variante, «calendario-2» la terza
    varianti = FRASI.get(gruppo, [])
    indice = int(numero) if numero.isdigit() else (-1 if trattino else 0)
    if servizio is None or not 0 <= indice < len(varianti):
        raise Http404
    if (motivo := voce.blocco(request.user, getattr(request, "azienda", None))):
        return JsonResponse({"errore": motivo}, status=429)
    try:
        dati, tipo = voce.leggi(servizio, varianti[indice], "it", request.user, getattr(request, "azienda", None))
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)
    risposta = HttpResponse(dati, content_type=tipo)
    risposta["Cache-Control"] = "private, max-age=86400"
    return risposta


def disponibile(azienda):
    """La pagina serve se ci sono sia la dettatura sia la lettura."""
    return voce.dettatura_disponibile(azienda) and voce.servizio_per(azienda) is not None


def impostazioni(azienda):
    def secondi(chiave, minimo, massimo, predefinito):
        try:
            valore = float(parametri.leggi(chiave, azienda))
        except (KeyError, TypeError, ValueError):
            return predefinito
        return min(max(valore, minimo), massimo)
    return {"silenzio_ms": int(secondi("ai.voce_silenzio", 0.6, 4, 1.3) * 1000),
            "ascolto_dopo_ms": int(secondi("ai.voce_ascolto_dopo", 0, 15, 6) * 1000)}


def apri_sul_telefono(azienda):
    try:
        return disponibile(azienda) and bool(parametri.leggi("ai.voce_telefono", azienda))
    except KeyError:
        return False


def _app(utente):
    """Le app a cui limitare la conversazione (menu in alto): quelle che la persona vede, tranne l'assistente."""
    from .pagine import app_selezionabili
    return [{"slug": a["slug"], "label": a["label"]} for a in app_selezionabili(utente)]


def _notifiche(utente):
    """Le notifiche non lette delle Comunicazioni, per la campanella; None se la persona non le usa."""
    return apertura.notifiche_non_lette(utente)


@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def pagina(request, pk=None):
    azienda = getattr(request, "azienda", None)
    conversazione = get_object_or_404(Conversazione.objects.select_related("progetto__azienda"), pk=pk, utente=request.user,
                                      nascosta=False) if pk else None
    if conversazione is not None and (altra := aree.da_passare(request.user, azienda, conversazione)):
        from .pagine import passa_ad_altra_azienda             # come la chat: prima si passa alla sua azienda
        return passa_ad_altra_azienda(request, altra)
    if conversazione is not None and aree.senza_chat(request.user, azienda, conversazione):
        raise Http404                                          # lì l'app Chat non c'è: niente da proporre
    app = _app(request.user)
    scelta = conversazione.ambito if conversazione else request.GET.get("app", "")
    ambito = scelta if scelta in {a["slug"] for a in app} else ""
    attiva = disponibile(azienda)
    # Ada apre lei la conversazione (ai.apertura): solo in una conversazione nuova e non limitata a un'app, dove
    # l'agenda che propone non si potrebbe leggere. «?da_capo=1», per le demo, la fa salutare come la prima volta.
    saluto = None
    if attiva and conversazione is None and not ambito:
        saluto = apertura.componi(request, da_capo=request.GET.get("da_capo") == "1")
    # la modifica in sospeso si conferma nella chat dov'è nata: «Chiudi» porta lì
    da_aprire = saluto.conversazione if saluto is not None and saluto.tipo == Apertura.SOSPESO else conversazione
    return render(request, "ai/parla.html", {
        "disponibile": attiva, "conversazione": conversazione, "impostazioni": impostazioni(azienda),
        "frasi": {"strumenti": FRASE_PER_STRUMENTO, "varianti": {k: len(v) for k, v in FRASI.items()}}, "app": app, "ambito": ambito,
        "notifiche": _notifiche(request.user), "nome": request.user.first_name, "apertura": saluto,
        "avviso_voce": limiti.avviso_voce() if attiva else "",
        "gia_qui": attiva and saluto is None and conversazione is None and apertura.presente_oggi(request.user, azienda),
        "url_chat": reverse("ai:conversazione", args=[da_aprire.pk]) if da_aprire else reverse("ai:chat")})


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def apertura_audio(request, pk):
    """L'audio dell'apertura: come per le risposte, il server legge solo un testo suo, mai uno mandato dal browser."""
    saluto = get_object_or_404(Apertura, pk=pk, utente=request.user)
    servizio = voce.servizio_per(getattr(request, "azienda", None))
    if servizio is None:
        raise Http404
    if (motivo := voce.blocco(request.user, getattr(request, "azienda", None))):
        return JsonResponse({"errore": motivo}, status=429)
    try:
        dati, tipo = voce.leggi(servizio, voce.da_leggere(saluto.testo), "it", request.user, getattr(request, "azienda", None))
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)
    risposta = HttpResponse(dati, content_type=tipo)
    risposta["Cache-Control"] = "private, max-age=3600"
    return risposta


@post_con_accesso
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def apertura_detta(request, pk):
    """Al primo tocco, quando Ada comincia a dirla: da qui l'apertura conta come sentita e non si ripete."""
    apertura.segna_detta(get_object_or_404(Apertura, pk=pk, utente=request.user))
    return HttpResponse(status=204)


def in_chat_riservata(request):
    """Se l'audio da trascrivere è detto in una chat riservata dell'utente (il campo «conversazione» della richiesta):
    lì la trascrizione resta sui nostri server, come la lettura delle risposte."""
    pk = request.POST.get("conversazione", "")
    return pk.isdigit() and Conversazione.objects.filter(pk=int(pk), utente=request.user, riservata=True).exists()


@post_con_accesso
@permission_required("ai.add_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def ascolta(request):
    """L'audio di un turno di parola in testo (Whisper, in italiano: i clienti sono italiani)."""
    azienda = getattr(request, "azienda", None)
    file = request.FILES.get("audio")
    if not disponibile(azienda) or file is None:
        return JsonResponse({"errore": "La voce non è attiva."}, status=400)
    if (motivo := voce.blocco(request.user, azienda)):
        return JsonResponse({"errore": motivo}, status=429)
    try:
        testo = voce.trascrivi(file, "it", azienda=azienda, parole=voce.parole_note(request.user, azienda),
                               solo_locale=in_chat_riservata(request), utente=request.user)
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)
    return JsonResponse({"testo": " ".join(testo.split())})


def _risposta_ancora_in_corso(conversazione):
    """Prima di una domanda nuova in una conversazione che ha ancora una risposta in corso: con quella in corso
    `motore.avvia` restituirebbe il turno vecchio, la domanda andrebbe persa e la pagina rileggerebbe la risposta di
    prima. A voce una domanda nuova è un'interruzione (lo stop mandato dalla pagina può non essere ancora stato visto,
    o la lettura si è fermata ai 30 secondi mentre la risposta continuava): il turno a voce si ferma e si aspetta che
    si chiuda. Una risposta avviata dalla chat scritta (una ricerca lunga) non si tocca. "" se si può procedere,
    altrimenti la frase per l'utente."""
    motore.segna_interrotti(conversazione)
    in_corso = motore.in_corso_di(conversazione)
    if in_corso is None:
        return ""
    if not in_corso.voce:
        return "In questa conversazione c'è già una risposta in corso nella chat: aspetta che finisca."
    if motore.ferma_e_attendi(in_corso):
        return ""
    return "Sto ancora chiudendo la risposta di prima: riprova tra qualche secondo."


@post_con_accesso
@permission_required("ai.add_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def chiedi(request):
    """La domanda detta va al motore della chat con la nota della voce; torna il turno da seguire."""
    azienda = getattr(request, "azienda", None)
    if not disponibile(azienda):
        return JsonResponse({"errore": "La voce non è attiva."}, status=400)
    testo = " ".join(request.POST.get("testo", "").split())
    if not testo:
        return JsonResponse({"errore": "Non ho sentito la domanda."}, status=400)
    pk = request.POST.get("conversazione", "")
    nuova = not pk.isdigit()
    # la prima cosa detta dopo l'apertura: il modello deve sapere che cosa Ada ha appena proposto
    saluto, numero = None, request.POST.get("apertura", "")
    if nuova and numero.isdigit():
        saluto = Apertura.objects.filter(pk=int(numero), utente=request.user).select_related("conversazione").first()
    accettata = saluto is not None and apertura.accetta(testo)
    ripresa = accettata and saluto.tipo == Apertura.RIPRENDI and saluto.conversazione is not None and not saluto.conversazione.nascosta
    if saluto is not None:
        apertura.segna_detta(saluto)                          # con la voce spenta è la risposta a dire che l'ha letta
    conversazione = None
    if not nuova:
        conversazione = get_object_or_404(Conversazione.objects.select_related("progetto__azienda"), pk=int(pk),
                                          utente=request.user, nascosta=False)
    elif ripresa:
        conversazione = saluto.conversazione                  # «sì, riprendiamo»: si continua in quella di prima
    if conversazione is not None:
        # una chat di un'altra azienda, scelta o da riprendere: come in chat, Ada non risponde con i dati di quella
        # corrente. Prima della risposta in corso, che lì non si ferma: la chat non è di questa azienda
        if (motivo := aree.rifiuto(request.user, azienda, conversazione)):
            return JsonResponse({"errore": motivo}, status=400)
        if (occupata := _risposta_ancora_in_corso(conversazione)):
            return JsonResponse({"errore": occupata}, status=409)
    else:
        app = request.POST.get("app", "")                     # la conversazione limitata all'app scelta in alto
        titolo = (apertura.titolo(saluto) if accettata else "") or testo[:60] + ("…" if len(testo) > 60 else "")
        conversazione = Conversazione.objects.create(utente=request.user, progetto=aree.corrente(request.user, azienda),
                                                     titolo=titolo,
                                                     ambito=app if app in {a["slug"] for a in _app(request.user)} else "")
    nome = apertura.nome_di(request.user)
    if saluto is not None:
        note = [NOTA_VOCE.format(nome=nome), apertura.nota(saluto, ripresa)]
    else:
        note = [NOTA_VOCE.format(nome=nome), NOTA_PRIMO_TURNO.format(nome=nome) if nuova else NOTA_TURNI_DOPO]
    if nuova and not ripresa and (oggi := apertura.nota_oggi(request.user, azienda)):
        note.append(oggi)                                     # la memoria della giornata, solo al primo turno
    sentito = " ".join(request.POST.get("sentito", "").split())[-SENTITO_MASSIMO:]
    if sentito:
        note.append(NOTA_INTERROTTA.format(sentito=sentito))
    turno = motore.avvia(conversazione, testo, request.user, azienda, web=False, nota="\n".join(note), voce=True)
    conversazione.save(update_fields=["aggiornata"])
    return JsonResponse({"conversazione": conversazione.pk, "turno": turno.pk,
                         "flusso": reverse("ai:flusso", args=[turno.pk]), "stop": reverse("ai:stop", args=[turno.pk]),
                         "chat": reverse("ai:conversazione", args=[conversazione.pk]),
                         "parla": reverse("ai:parla_conversazione", args=[conversazione.pk])})


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def audio(request, pk, inizio, fine):
    """L'audio di un tratto della risposta del turno (posizioni nel testo, come le dà lo streaming)."""
    turno = get_object_or_404(Turno, pk=pk, conversazione__utente=request.user)
    servizio = voce.servizio_per(getattr(request, "azienda", None), solo_locale=turno.conversazione.riservata)
    if servizio is None or not 0 <= inizio < fine <= len(turno.testo) or fine - inizio > CARATTERI_PEZZO:
        raise Http404
    testo = voce.da_leggere(turno.testo[inizio:fine])
    if not testo.strip():
        return HttpResponse(status=204)
    if (motivo := voce.blocco(request.user, getattr(request, "azienda", None))):
        return JsonResponse({"errore": motivo}, status=429)
    try:
        # la lingua si decide sulla risposta intera: un pezzo breve non deve cambiare voce a metà
        dati, tipo = voce.leggi(servizio, testo, voce.lingua_di(voce.da_leggere(turno.testo)), request.user,
                                getattr(request, "azienda", None))
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)
    risposta = HttpResponse(dati, content_type=tipo)
    risposta["Cache-Control"] = "private, max-age=3600"
    return risposta

