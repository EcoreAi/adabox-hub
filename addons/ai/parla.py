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
from django.views.decorators.http import require_POST

from core import parametri

from . import aree, funzioni, motore, voce
from .models import Conversazione, Turno

NOTA_VOCE = (
    "L'utente si chiama {nome}: quando saluti o rispondi a un saluto chiamalo per nome, senza formule fatte come «come "
    "posso aiutarti oggi?». L'utente ti parla a voce dal telefono e ascolta la risposta letta ad alta voce. Rispondi in poche frasi brevi e "
    "parlate, come in una telefonata: niente tabelle, elenchi puntati, titoli, emoji, codice o link. Numeri, importi, "
    "date e orari scrivili in cifre (13:30, 1.250 €, 16/11): la lettura li pronuncia da sola. Se i risultati sono più di tre o quattro, dai il totale e i più importanti e chiedi se "
    "vuole il dettaglio. Per agenda, scadenze e attività parti da quello che deve ancora succedere; di quello già "
    "passato di' solo quanti sono e chiedi se vuole sentirli. Prima di creare o modificare qualcosa ripeti in una "
    "frase cosa farai e chiedi conferma.")
NOTA_INTERROTTA = ("Nel turno precedente l'utente ti ha interrotto mentre parlavi: ha sentito solo fin qui: «{sentito}». "
                   "Tienine conto e non ripetere quello che ha già sentito, a meno che lo chieda.")
# A voce solo gli strumenti utili al telefono: da 39 a 18, circa il 40% di attesa in meno sul primo passo e meno token.
# Fuori quelli visivi (grafici, tabelle, Analisi), i documenti lunghi, le pianificazioni, gli agenti e l'eliminazione.
STRUMENTI_VOCE = frozenset({
    "data_e_ora", "calendario_agenda", "cerca_record", "leggi_record", "aggrega_record", "elenco_viste", "descrivi_vista",
    "cerca_conoscenza", "leggi_documento", "comunicazioni_cerca", "comunicazioni_leggi", "comunicazioni_scrivi",
    "crea_record", "modifica_record", "pianifica_attivita", "esegui_bottone", "ricorda", "previsione"})
# Frasi d'attesa: lette quando parte uno strumento, prima della risposta (Kokoro le prepara una volta, poi in cache)
FRASI = {"calendario": "Guardo il calendario.", "dati": "Controllo nei dati.", "documenti": "Cerco nei documenti.",
         "comunicazioni": "Guardo le comunicazioni.", "attimo": "Un attimo."}
FRASE_PER_STRUMENTO = {"calendario_agenda": "calendario", "cerca_record": "dati", "leggi_record": "dati",
                       "aggrega_record": "dati", "previsione": "dati", "cerca_conoscenza": "documenti",
                       "leggi_documento": "documenti", "comunicazioni_cerca": "comunicazioni",
                       "comunicazioni_leggi": "comunicazioni"}
CARATTERI_PEZZO = 600                    # un pezzo da leggere: il browser li fa di 110-300 caratteri
SENTITO_MASSIMO = 500


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def frase(request, chiave):
    """L'audio di una frase d'attesa: solo quelle dell'elenco, mai un testo del browser."""
    servizio = voce.servizio_per(getattr(request, "azienda", None))
    if servizio is None or chiave not in FRASI:
        raise Http404
    try:
        dati, tipo = voce.audio_di(servizio, FRASI[chiave], "it")
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


@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def pagina(request, pk=None):
    azienda = getattr(request, "azienda", None)
    conversazione = get_object_or_404(Conversazione, pk=pk, utente=request.user, nascosta=False) if pk else None
    return render(request, "ai/parla.html", {
        "disponibile": disponibile(azienda), "conversazione": conversazione, "impostazioni": impostazioni(azienda),
        "frasi": FRASE_PER_STRUMENTO,
        "url_chat": reverse("ai:conversazione", args=[conversazione.pk]) if conversazione else reverse("ai:chat")})


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def ascolta(request):
    """L'audio di un turno di parola in testo (Whisper, in italiano: i clienti sono italiani)."""
    azienda = getattr(request, "azienda", None)
    file = request.FILES.get("audio")
    if not disponibile(azienda) or file is None:
        return JsonResponse({"errore": "La voce non è attiva."}, status=400)
    try:
        testo = voce.trascrivi(file, "it", azienda=azienda, parole=voce.parole_note(request.user, azienda))
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)
    return JsonResponse({"testo": " ".join(testo.split())})


@require_POST
@login_required
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
    if pk.isdigit():
        conversazione = get_object_or_404(Conversazione, pk=int(pk), utente=request.user, nascosta=False)
    else:
        conversazione = Conversazione.objects.create(utente=request.user, progetto=aree.corrente(request.user, azienda),
                                                     titolo=testo[:60] + ("…" if len(testo) > 60 else ""))
    note = [NOTA_VOCE.format(nome=request.user.first_name or request.user.get_full_name() or request.user.username)]
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
    servizio = voce.servizio_per(getattr(request, "azienda", None))
    if servizio is None or not 0 <= inizio < fine <= len(turno.testo) or fine - inizio > CARATTERI_PEZZO:
        raise Http404
    testo = voce.da_leggere(turno.testo[inizio:fine])
    if not testo.strip():
        return HttpResponse(status=204)
    try:
        # la lingua si decide sulla risposta intera: un pezzo breve non deve cambiare voce a metà
        dati, tipo = voce.audio_di(servizio, testo, voce.lingua_di(voce.da_leggere(turno.testo)))
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)
    risposta = HttpResponse(dati, content_type=tipo)
    risposta["Cache-Control"] = "private, max-age=3600"
    return risposta

