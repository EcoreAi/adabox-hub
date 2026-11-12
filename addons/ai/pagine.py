"""Chat con l'assistente: pagina a tutto schermo a tre colonne (pannelli laterali chiusi di default)."""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.text import get_valid_filename
from django.views.decorators.http import require_POST

from core import allegati as core_allegati
from core.allegati import AllegatoNonValido
from core.models import Allegato
from core import barra
from core.registry import modules

from . import allegati_chat, aree, catalogo, collegamenti, documenti_chat, funzioni, motore, ricerca, suggerimenti, voce
from .strumenti.registro import ErroreStrumento
from .models import Artifact, CollegamentoProgetto, Conversazione, DocumentoChat, VersioneDocumento, MessaggioChat, ProgettoChat, Proposta, Turno, ValutazioneRisposta

IN_VISTA_ALBERO = 8
PANNELLI_SINISTRA = [("storico", "Cronologia chat", "ai-storico"), ("preferite", "Preferiti: chat, documenti, grafici e tabelle", "ai-stella"),
                     ("progetti", "Aree di lavoro", "ai-cartella")]


def _mie(request):
    return Conversazione.objects.filter(utente=request.user, nascosta=False).select_related("progetto")


VOCI_PER_SOTTOCARTELLA = 8


def _progetti_con_recenti(request, azienda):
    """Le aree di lavoro che l'utente vede (sue e condivise con lui) per la colonna di sinistra: le sottocartelle si
    caricano quando se ne apre una."""
    from django.db.models import Count
    if azienda is not None:
        aree.personale(request.user, azienda)                   # ognuno ha sempre almeno la sua area
    return list(aree.visibili(request.user, azienda).select_related("utente").annotate(n_membri=Count("membri", distinct=True))
                .order_by("-personale", "nome", "pk"))


def _contenuti_progetto(request, progetto):
    """Ciò che è nato nelle chat del progetto, per tipo: compare da solo, senza salvarlo a mano."""
    from . import archivio
    chat = aree.chat_visibili(request.user, progetto).order_by("-aggiornata")
    radice = archivio.cartella(request.user, progetto.azienda, progetto.cartella_documenti) if archivio.attivo() else None
    documenti = archivio.documenti_in(request.user, progetto.azienda, radice) if radice else []
    return {
        "archivio_attivo": archivio.attivo(), "cartella_progetto": radice,
        "url_cartella_progetto": archivio.url_cartella(radice) if radice else "",
        "documenti_cartella": [(d, archivio.url_documento(d)) for d in documenti[:60]], "documenti_cartella_totale": len(documenti),
        "cartella_scrivibile": bool(radice and archivio.cartella(request.user, progetto.azienda, radice.pk, scrittura=True)),
        "chat_progetto": chat[:100],
        "documenti_progetto": DocumentoChat.objects.filter(conversazione__in=chat.values("pk")).select_related("utente").order_by("-aggiornato")[:50],
        "artifact_progetto": Artifact.objects.filter(conversazione__in=chat.values("pk")).select_related("utente").order_by("-pk")[:50],
    }


def _fornitore_immagini(azienda):
    """Il nome del modello cloud che riceverebbe un'immagine, per il riquadro di conferma."""
    try:
        catena = catalogo.automatico(catalogo.profilo_per("chat", azienda), azienda)
    except catalogo.NessunModello:
        return "un modello cloud"
    return next((m.etichetta for m, _ in catena if m.visione and not m.provider.locale), "un modello cloud")


def livelli_modello(azienda):
    """[(livello, modello)] della scelta in chat: «standard» è Veloce, «max» è Avanzato. Valgono i modelli con il
    livello assegnato; se nessuno ne ha uno, Veloce è il più economico dei sceglibili e Avanzato il più caro.
    Con Automatico: Veloce, poi Avanzato, poi la catena del profilo della chat (catalogo.automatico).
    Senza la funzione «piu_modelli» niente scelta: risponde il modello degli amministratori."""
    if not funzioni.attiva("piu_modelli"):
        return []
    disponibili = [m for m, _ in catalogo.sceglibili(azienda)]
    assegnati = {m.livello_chat: m for m in disponibili if m.livello_chat}
    if assegnati:
        return [(livello, assegnati[nome]) for livello, nome in (("standard", "veloce"), ("max", "avanzato")) if nome in assegnati]
    modelli = sorted((m for m, _ in catalogo.sceglibili(azienda)),
                     key=lambda m: (m.prezzo_output or 0, m.prezzo_input or 0, m.pk))   # senza prezzo conta come gratuito
    if not modelli:
        return []
    return [("standard", modelli[0])] + ([("max", modelli[-1])] if len(modelli) > 1 else [])


def app_selezionabili(user):
    """Le app che l'utente vede (tranne l'assistente stesso): la chat si può limitare a una di queste."""
    return [a for a in modules.app_visibili(user) if a["slug"] != "ai"]


def _avviso_spesa(request):
    """Testo dell'avviso quando la spesa del mese si avvicina al tetto (o l'assistente non è attivo)."""
    from core import parametri

    from . import licenza, limiti
    stato = licenza.attuale()
    if not stato.valida:
        return f"L'assistente non è attivo: {stato.motivo}"
    if avviso := limiti.avviso_quota(request.user, stato):
        return avviso
    azienda = getattr(request, "azienda", None)
    if azienda is None or limiti.tetto(azienda) <= 0:
        return ""
    spesa, tetto = limiti.spesa_mese(azienda), limiti.tetto(azienda)
    soglia = tetto * (parametri.leggi("ai.avviso_percentuale", azienda) or 80) / 100
    if spesa >= tetto:
        return "Raggiunto il tetto di spesa mensile: l'assistente riprenderà il mese prossimo."
    if spesa >= soglia:
        return f"Spesa del mese a {spesa:.2f} $ su {tetto} $."
    return ""


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def chat(request, pk=None, progetto=None):
    """La chat: una conversazione, una chat nuova, oppure la pagina di un progetto (le sue chat, documenti, grafici,
    file e la casella per una chat nuova nel progetto)."""
    if progetto is not None and not funzioni.attiva("aree_di_lavoro"):
        raise Http404("Aree di lavoro non comprese nella licenza.")
    azienda = getattr(request, "azienda", None)
    sola_lettura = False
    conversazione = _mie(request).filter(pk=pk).first() if pk else None
    if pk and conversazione is None:                 # una chat condivisa da un altro membro di un'area: si legge soltanto
        if not funzioni.attiva("aree_di_lavoro"):
            raise Http404
        conversazione = get_object_or_404(Conversazione.objects.filter(condivisa=True, nascosta=False, progetto__in=aree.visibili(request.user, azienda))
                                          .select_related("progetto", "utente"), pk=pk)
        sola_lettura = True
    mie = _mie(request)
    con_aree = funzioni.attiva("aree_di_lavoro")             # senza: le chat stanno nell'area personale, che non si vede
    progetti = _progetti_con_recenti(request, azienda) if con_aree else []
    progetto_aperto = None
    if progetto is not None:
        progetto_aperto = _mio_progetto(request, progetto)
        if progetto_aperto is None:
            raise Http404
        aree.imposta_corrente(request.user, progetto_aperto)       # aprire un'area è lavorarci
    area_corrente = conversazione.progetto if conversazione is not None and conversazione.progetto_id else aree.corrente(request.user, azienda)
    app = app_selezionabili(request.user)
    ambito = next((a for a in app if conversazione and a["slug"] == conversazione.ambito), None)
    if conversazione is not None and not sola_lettura:
        motore.segna_interrotti(conversazione)
    in_corso = motore.in_corso_di(conversazione) if conversazione and not sola_lettura else None
    aperto = _mio_documento(request, request.GET.get("documento"), conversazione) if conversazione and not sola_lettura else None
    progetto_nuova = (progetto_aperto or _mio_progetto(request, request.GET.get("progetto")) or area_corrente) if conversazione is None else None
    return render(request, "ai/chat.html", {
        "sola_lettura": sola_lettura, "autore_chat": aree.nome(conversazione.utente) if sola_lettura else "",
        "puo_condividere": bool(con_aree and conversazione and not sola_lettura and conversazione.progetto_id),
        "documento": aperto, "versioni": aperto.versioni.all()[:20] if aperto else [],
        "conversazione": conversazione, "ambito": ambito, "turno": in_corso, "avviso_spesa": _avviso_spesa(request),
        "messaggi": conversazione.messaggi.all() if conversazione else [],
        "storico": mie[:50], "preferite": mie.filter(preferita=True)[:50],
        "salvati": _salvati(request), "ricevuti": _ricevuti(request),
        "pannelli_sinistra": [p for p in PANNELLI_SINISTRA if con_aree or p[0] != "progetti"],
        "app": app, "suggerimenti": suggerimenti.per(), "suggerimenti_per_app": suggerimenti.tutti(),
        "progetti": progetti, "progetto_aperto": progetto_aperto, "area_corrente": area_corrente,
        "gestisco_area": bool(progetto_aperto and progetto_aperto.utente_id == request.user.pk),
        "url_dashboard_area": _url_dashboard(request, progetto_aperto),
        "membri_area": [aree.nome(m.utente) for m in progetto_aperto.membri.select_related("utente")] if progetto_aperto else [],
        "collegamenti_progetto": collegamenti.del_progetto(request, progetto_aperto) if progetto_aperto else [],
        **(_lavoro_del_progetto(request, progetto_aperto) if progetto_aperto else {}),
        "progetto_nuova": progetto_nuova,
        # chat nuova in un progetto con un'app predefinita: parte limitata a quell'app (se l'utente la vede ancora)
        "ambito_nuova": progetto_nuova.ambito if progetto_nuova and progetto_nuova.ambito in {a["slug"] for a in app} else "",
        "livelli_modello": livelli_modello(azienda),
        "app_gruppi": barra.gruppi([{**a, "categoria": a.get("category", "")} for a in app]),
        "ricerca_disponibile": ricerca.disponibile(azienda),
        "conferma_immagini": _fornitore_immagini(azienda) if allegati_chat.serve_conferma(azienda) else "",
        "dettatura": voce.dettatura_disponibile(azienda), "lettura": voce.servizio_per(azienda) is not None,
        **_salva_nei_documenti(request, azienda, conversazione, progetto_aperto),
    })


def _lavoro_del_progetto(request, progetto):
    """Attività pianificate del progetto e link per mettere una sessione di lavoro nel calendario."""
    from urllib.parse import urlencode

    from django.conf import settings
    voci = {"pianificate_progetto": list(progetto.pianificate.filter(utente=request.user)) if request.user.has_perm("ai.view_pianificata") else []}
    if "calendario" in settings.ADDONS_ATTIVI and request.user.has_perm("calendario.add_evento"):
        try:
            nuovo = reverse("calendario:eventi_nuovo")
        except Exception:                                           # noqa: BLE001 - vista del calendario cambiata
            nuovo = ""
        if nuovo:
            indirizzo = request.build_absolute_uri(reverse("ai:progetto", args=[progetto.pk]))
            voci["url_sessione"] = nuovo + "?" + urlencode({"titolo": f"Lavoro su «{progetto.nome}»",
                                                             "descrizione": f"Area di lavoro di Ada: {indirizzo}"})
    return voci


def _salva_nei_documenti(request, azienda, conversazione, progetto_aperto):
    """Per il riquadro «Salva nei Documenti»: le cartelle in cui l'utente scrive, con quella del progetto già scelta."""
    from . import archivio
    scrivibili = archivio.cartelle(request.user, azienda, scrittura=True)
    if not scrivibili:
        return {}
    progetto = progetto_aperto or (conversazione.progetto if conversazione and conversazione.progetto_id else None)
    return {"cartelle_scrivibili": scrivibili, "cartella_predefinita": getattr(progetto, "cartella_documenti", None)}


def _ricevuti(request):
    from . import condivisione
    documenti, artifact = condivisione.ricevuti(request.user)
    documenti, artifact = list(documenti), list(artifact)
    return {"documenti": documenti, "artifact": artifact, "totale": len(documenti) + len(artifact)}


def _url_dashboard(request, area):
    """La dashboard dell'area in Analisi, se il modulo c'è e l'utente lo usa (ai non dipende da Analisi)."""
    from django.apps import apps as django_apps
    if area is None or not django_apps.is_installed("grafici") or not request.user.has_perm("grafici.view_pagina"):
        return ""
    return reverse("grafici:pagina_area", args=[area.pk])


def _salvati(request):
    """I preferiti oltre alle chat: documenti e grafici e tabelle con la stella, di tutte le chat."""
    return {"grafici_tabelle": Artifact.objects.filter(utente=request.user, salvato=True).order_by("-pk")[:100],
            "documenti": DocumentoChat.objects.filter(utente=request.user, salvato=True, conversazione__nascosta=False).order_by("-pk")[:100]}


def _mio_progetto(request, pk):
    """Un'area di lavoro che l'utente vede (sua o condivisa con lui) nell'azienda corrente, o None."""
    return aree.visibile(request.user, getattr(request, "azienda", None), pk)


def _area_gestita(request, pk):
    """Un'area di lavoro creata dall'utente (solo lui ne cambia le impostazioni), o None."""
    return aree.gestita(request.user, getattr(request, "azienda", None), pk)


def _errore_invio(request, testo, pk):
    """Il file rifiutato: col messaggio scritto ancora nel campo, se si invia dalla chat."""
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204, headers={"HX-Trigger": json.dumps({"ai-errore": testo})})
    messages.error(request, testo)
    return redirect(reverse("ai:conversazione", args=[pk]) if pk else reverse("ai:chat"))


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
def invia(request, pk=None):
    testo = request.POST.get("testo", "").strip()
    conversazione = get_object_or_404(_mie(request), pk=pk) if pk else None
    file = request.FILES.getlist("allegati")
    confermate = request.POST.get("conferma_immagini") == "1"
    try:
        allegati_chat.controlla(file, getattr(request, "azienda", None), confermate)
    except AllegatoNonValido as e:
        return _errore_invio(request, str(e), pk)
    if file and not testo:
        testo = "Guarda l'allegato."
    if not testo:
        return HttpResponse(status=204) if request.headers.get("HX-Request") else redirect(
            reverse("ai:conversazione", args=[pk]) if pk else reverse("ai:chat"))
    nuova = conversazione is None
    ammessi = {a["slug"] for a in app_selezionabili(request.user)}
    ambito = request.POST.get("ambito", "")
    ambito = ambito if ambito in ammessi else ""
    if nuova:
        titolo = " ".join(testo.split())
        area = _mio_progetto(request, request.POST.get("progetto")) or aree.corrente(request.user, getattr(request, "azienda", None))
        conversazione = Conversazione.objects.create(utente=request.user, ambito=ambito, progetto=area,
                                                     titolo=titolo[:60] + ("…" if len(titolo) > 60 else ""))
    elif "ambito" in request.POST and ambito != conversazione.ambito:     # app cambiata dal bottone «App»
        conversazione.ambito = ambito
        conversazione.save(update_fields=["ambito"])
    if "modello" in request.POST and funzioni.attiva("piu_modelli"):   # vuoto = quello degli amministratori
        ammessi_modelli = {str(m.pk): m for m, _ in catalogo.sceglibili(getattr(request, "azienda", None))}
        scelto = ammessi_modelli.get(request.POST["modello"])
        if conversazione.modello_id != getattr(scelto, "pk", None):
            conversazione.modello = scelto
            conversazione.save(update_fields=["modello"])
    primo = conversazione.messaggi.order_by("-pk").values_list("pk", flat=True).first() or 0
    aperto = _mio_documento(request, request.POST.get("documento"), conversazione) if not nuova else None
    # ricerca sul web scelta per questo messaggio: nessuna (predefinita), sul web, approfondita
    scelta = request.POST.get("ricerca", "")
    web_accesa = ricerca.disponibile(getattr(request, "azienda", None))
    approfondita = scelta in ("approfondita", "1") and web_accesa
    sul_web = scelta == "web" and web_accesa
    nota_web = "Per questo messaggio l'utente ha acceso la ricerca sul web: usala se serve e cita i link delle fonti." if sul_web else ""
    turno = motore.avvia(conversazione, testo, request.user, getattr(request, "azienda", None), file=file,
                         compito=ricerca.COMPITO if approfondita else "chat", web=approfondita or sul_web,
                         immagini_confermate=confermate and allegati_chat.serve_conferma(getattr(request, "azienda", None)),
                         nota="\n".join(n for n in (documenti_chat.nota(aperto), ricerca.ISTRUZIONI if approfondita else "", nota_web) if n))
    conversazione.save(update_fields=["aggiornata"])
    url = reverse("ai:conversazione", args=[conversazione.pk])
    if request.headers.get("HX-Request"):
        if nuova:                                        # nuova chat: si carica la pagina della conversazione
            return HttpResponse(status=204, headers={"HX-Redirect": url})
        turno.refresh_from_db()
        return render(request, "ai/_messaggi.html", {
            "messaggi": conversazione.messaggi.filter(pk__gt=primo), "turno": None if turno.concluso else turno})
    return redirect(url)


def _ripartenza(request, conversazione, messaggio, testo):
    try:
        motore.riparti(conversazione, messaggio, testo, request.user, getattr(request, "azienda", None))
    except motore.NonSiPuoRipartire as e:
        messages.error(request, str(e))
    return redirect("ai:conversazione", pk=conversazione.pk)


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
def rigenera(request, pk):
    """Di nuovo l'ultima risposta: l'ultima domanda resta com'è."""
    conversazione = get_object_or_404(_mie(request), pk=pk)
    domanda = conversazione.messaggi.filter(ruolo=MessaggioChat.UTENTE).order_by("-pk").first()
    if domanda is None:
        return redirect("ai:conversazione", pk=pk)
    return _ripartenza(request, conversazione, domanda, domanda.testo)


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
def modifica_messaggio(request, pk):
    """Il messaggio cambia e tutto ciò che veniva dopo sparisce: la chat è una sola, non si ramifica."""
    messaggio = get_object_or_404(MessaggioChat.objects.select_related("conversazione"), pk=pk, ruolo=MessaggioChat.UTENTE,
                                  conversazione__in=_mie(request))
    testo = request.POST.get("testo", "").strip()
    if not testo:
        messages.error(request, "Il messaggio non può essere vuoto.")
        return redirect("ai:conversazione", pk=messaggio.conversazione_id)
    return _ripartenza(request, messaggio.conversazione, messaggio, testo)


@require_POST
@login_required
@funzioni.richiede("aree_di_lavoro")
def sposta(request, pk):
    """In un progetto o fuori. Vale dal messaggio successivo."""
    c = get_object_or_404(_mie(request), pk=pk)
    area = _mio_progetto(request, request.POST.get("progetto")) or aree.personale(request.user, getattr(request, "azienda", None))
    if area is not None and area.pk != c.progetto_id:
        c.progetto, c.condivisa = area, c.condivisa and not area.personale
        c.save(update_fields=["progetto", "condivisa"])
        aree.imposta_corrente(request.user, area)
    return redirect("ai:conversazione", pk=c.pk)


@require_POST
@login_required
@funzioni.richiede("aree_di_lavoro")
def area_corrente(request):
    """Cambia l'area su cui si lavora (dalla tendina sopra la chat nuova o dalla colonna di sinistra)."""
    area = _mio_progetto(request, request.POST.get("area"))
    if area is not None:
        aree.imposta_corrente(request.user, area)
    prossimo = request.POST.get("da", "")
    return redirect(prossimo if prossimo.startswith("/") and not prossimo.startswith("//") else "ai:chat")


@require_POST
@login_required
def rinomina(request, pk):
    c = get_object_or_404(_mie(request), pk=pk)
    titolo = " ".join(request.POST.get("titolo", "").split())[:120]
    if titolo:                                           # scelto da una persona: il titolo automatico non lo tocca più
        c.titolo, c.titolo_generato = titolo, True
        c.save(update_fields=["titolo", "titolo_generato"])
    return redirect("ai:conversazione", pk=c.pk)


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def cerca_chat(request):
    """Nelle proprie chat: titolo e testo dei messaggi."""
    testo = request.GET.get("q", "").strip()[:100]
    chat = _mie(request)
    if testo:
        chat = chat.filter(Q(titolo__icontains=testo) | Q(pk__in=MessaggioChat.objects.filter(testo__icontains=testo).values("conversazione_id")))
    return render(request, "ai/_elenco_chat.html", {"chat": chat[:50], "vuoto": "Nessuna chat trovata." if testo else "Nessuna conversazione ancora."})


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def esporta(request, pk):
    """La conversazione in Markdown, come si legge a video."""
    c = get_object_or_404(_mie(request), pk=pk)
    righe = [f"# {c.titolo}", "", f"Esportata il {timezone.localtime():%d/%m/%Y %H:%M}", ""]
    for m in c.messaggi.all():
        righe += [f"## {'Tu' if m.ruolo == MessaggioChat.UTENTE else 'Assistente'} · {timezone.localtime(m.creato):%d/%m/%Y %H:%M}", "", m.testo, ""]
        righe += [f"Allegato: {a.nome}" for a in allegati_chat.di(m)]
    risposta = HttpResponse("\n".join(righe), content_type="text/markdown; charset=utf-8")
    risposta["Content-Disposition"] = content_disposition_header(True, f"{get_valid_filename(c.titolo) or 'chat'}.md")
    return risposta


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def allegato(request, pk):
    """Un file allegato a una delle proprie chat."""
    voce = get_object_or_404(Allegato, pk=pk, content_type=ContentType.objects.get_for_model(MessaggioChat),
                             object_id__in=MessaggioChat.objects.filter(conversazione__in=_mie(request)).values("pk"))
    return core_allegati.risposta(voce)


@require_POST
@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def voto(request, pk):
    """Pollice su o giù, ripremerlo lo toglie. Con la risposta passa agli amministratori anche il commento."""
    m = get_object_or_404(MessaggioChat, pk=pk, ruolo=MessaggioChat.ASSISTENTE, conversazione__in=_mie(request))
    attuale = ValutazioneRisposta.objects.filter(messaggio=m).first()
    if "commento" in request.POST:
        if attuale:
            attuale.commento = request.POST["commento"].strip()[:500]
            attuale.save(update_fields=["commento", "creata"])
        return render(request, "ai/_voto.html", {"m": m, "v": attuale, "grazie": True})
    valore = {"1": 1, "-1": -1}.get(request.POST.get("voto"))
    if valore is None:
        return HttpResponse(status=400)
    if attuale and attuale.voto == valore:
        attuale.delete()
        attuale = None
    else:
        attuale, _ = ValutazioneRisposta.objects.update_or_create(messaggio=m, defaults={
            "voto": valore, "utente": request.user, "azienda": getattr(request, "azienda", None)})
    return render(request, "ai/_voto.html", {"m": m, "v": attuale})


@require_POST
@login_required
def preferita(request, pk):
    c = get_object_or_404(_mie(request), pk=pk)
    c.preferita = not c.preferita
    c.save(update_fields=["preferita"])
    return redirect("ai:conversazione", pk=c.pk)


@require_POST
@login_required
@permission_required("ai.delete_conversazione", raise_exception=True)
def elimina(request, pk):
    c = get_object_or_404(_mie(request), pk=pk)
    c.delete()
    messages.success(request, "Conversazione eliminata.")
    return redirect("ai:chat")


@require_POST
@login_required
def stop(request, pk):
    turno = get_object_or_404(Turno, pk=pk, conversazione__utente=request.user)
    motore.ferma(turno)
    return HttpResponse(status=204)


@login_required
@permission_required("ai.change_licenza", raise_exception=True)
def pagina_licenza(request):
    """Stato della licenza e caricamento di un nuovo file."""
    from . import licenza, limiti
    from .models import Licenza
    if request.method == "POST":
        file = request.FILES.get("file")
        testo = file.read().decode("utf-8", errors="replace") if file else request.POST.get("testo", "")
        stato = licenza.leggi(testo)
        if stato.valida:
            Licenza.objects.create(testo=testo, caricata_da=request.user)
            messages.success(request, f"Licenza di {stato.cliente} caricata: valida fino al {stato.scadenza:%d/%m/%Y}.")
        else:
            messages.error(request, f"Licenza non caricata: {stato.motivo}")
        return redirect("ai:licenza")
    from core import funzioni as core_funzioni
    from .models import Provider
    azienda = getattr(request, "azienda", None)
    stato = licenza.attuale()
    a_formula = stato.valida and stato.formula != licenza.PROPRIA
    return render(request, "ai/licenza.html", {
        "stato": stato, "funzioni_licenza": [{**f, "compresa": stato.funzioni is None or f["chiave"] in stato.funzioni}
                                             for f in core_funzioni.catalogo("ai")],
        "spesa": limiti.spesa_mese(azienda) if azienda else None,
        "tetto": limiti.tetto(azienda) if azienda else None, "utenti_mese": len(limiti.utenti_del_mese()),
        "a_formula": a_formula, "consumo_fornito": limiti.consumo_fornito(),
        "senza_fornito": a_formula and not Provider.objects.filter(gestito=True, attivo=True).exists(),
        "consumo_per_utente": limiti.consumo_per_utente() if stato.valida and stato.formula == licenza.INCLUSA else []})


def _scheda(request, proposta, errore=""):
    if request.headers.get("HX-Request"):
        return render(request, "ai/_proposta.html", {"p": proposta, "errore": errore})
    if errore:
        messages.error(request, errore)
    return redirect("ai:conversazione", pk=proposta.conversazione_id)


@require_POST
@login_required
def conferma_proposta(request, pk):
    from . import proposte
    from .strumenti import ErroreStrumento
    proposta = get_object_or_404(Proposta, pk=pk, utente=request.user, conversazione__utente=request.user)
    if proposta.irreversibile and proposta.in_attesa and not request.POST.get("consapevole"):
        return _scheda(request, proposta, "Spunta la casella per confermare un'operazione irreversibile.")
    try:
        proposte.conferma(proposta, request.user, getattr(request, "azienda", None))
    except ErroreStrumento as e:
        return _scheda(request, proposta, str(e))
    return _scheda(request, proposta)


@require_POST
@login_required
def annulla_proposta(request, pk):
    from . import proposte
    proposta = get_object_or_404(Proposta, pk=pk, utente=request.user, conversazione__utente=request.user)
    return _scheda(request, proposte.annulla(proposta))


def _mio_artifact(request, pk):
    return get_object_or_404(Artifact, pk=pk, utente=request.user)


@login_required
def pagina_artifact(request, pk):
    """L'artifact con i dati di oggi (stessi permessi e azienda di quando è stato chiesto)."""
    from django.utils import timezone
    from django.utils.safestring import mark_safe

    from . import artifact
    from .strumenti import ErroreStrumento
    a = _artifact_leggibile(request, pk)
    dati, errore = {}, ""
    try:
        dati = _dati_di_oggi(request, a)
    except ErroreStrumento as e:
        errore = f"Non si può ricalcolare: {e}"
    disegno = mark_safe(artifact.svg_di(a, dati)) if dati and a.tipo == Artifact.GRAFICO else ""
    mio = a.utente_id == request.user.pk
    return render(request, "ai/artifact.html", {"a": a, "dati": dati, "disegno": disegno, "errore": errore, "mio": mio,
                                                "adesso": timezone.localtime()})


def _artifact_leggibile(request, pk):
    """Il grafico o la tabella se è dell'utente o condiviso con lui."""
    from . import condivisione
    a = condivisione.leggibile(Artifact, request.user, pk)
    if a is None:
        raise Http404
    return a


def _dati_di_oggi(request, a):
    """I dati di oggi: del proprietario con i suoi permessi; di chi l'ha ricevuto con i permessi di chi guarda."""
    from . import artifact
    from .strumenti import Contesto
    if a.utente_id == request.user.pk:
        return artifact.ricalcola(a)
    return artifact.calcola(a.spec, Contesto(utente=request.user, azienda=getattr(request, "azienda", None)))


@login_required
def csv_artifact(request, pk):
    """CSV dell'istantanea mostrata in chat, o dei dati di oggi con ?oggi=1."""
    from django.utils.text import slugify

    from . import artifact
    from .strumenti import ErroreStrumento
    a = _artifact_leggibile(request, pk)
    dati = a.dati if a.utente_id == request.user.pk else None        # l'istantanea è del proprietario: agli altri i loro dati
    if request.GET.get("oggi") or dati is None:
        try:
            dati = _dati_di_oggi(request, a)
        except ErroreStrumento as e:
            return HttpResponse(str(e), status=409, content_type="text/plain; charset=utf-8")
    risposta = HttpResponse(artifact.csv_di(a, dati), content_type="text/csv; charset=utf-8")
    risposta["Content-Disposition"] = f'attachment; filename="{slugify(a.titolo) or "artifact"}.csv"'
    return risposta


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def documento_condiviso(request, pk):
    """Un documento scritto con Ada, da leggere e scaricare: per chi l'ha ricevuto (e per chi l'ha scritto)."""
    from . import condivisione
    d = condivisione.leggibile(DocumentoChat, request.user, pk)
    if d is None:
        raise Http404
    return render(request, "ai/documento_condiviso.html", {"d": d, "mio": d.utente_id == request.user.pk})


@require_POST
@login_required
def condividi(request, tipo, pk):
    """Con chi è condiviso un mio documento, grafico o tabella; risponde con il riquadro aggiornato."""
    from . import condivisione
    modello = condivisione.TIPI.get(tipo)
    if modello is None:
        raise Http404
    filtro = {"conversazione__nascosta": False} if modello is DocumentoChat else {}
    oggetto = get_object_or_404(modello, pk=pk, utente=request.user, **filtro)
    quanti, _ = condivisione.condividi(request, oggetto, request.POST.getlist("persone"))
    esito = (f"Condiviso con {quanti} person{'a' if quanti == 1 else 'e'}." if quanti else "Non è più condiviso.")
    if not request.headers.get("HX-Request"):
        messages.success(request, esito)
        return redirect(request.META.get("HTTP_REFERER") or condivisione.url_di(oggetto))
    return render(request, "ai/_condividi.html", {"oggetto": oggetto, "tipo": tipo, "esito": esito, "aperto": True})


@require_POST
@login_required
def salva_artifact(request, pk):
    a = _mio_artifact(request, pk)
    a.salvato = not a.salvato
    a.save(update_fields=["salvato"])
    if request.headers.get("HX-Request"):
        return render(request, "ai/_artifact.html", {"a": a})
    return redirect("ai:conversazione", pk=a.conversazione_id) if a.conversazione_id else redirect("ai:chat")


@require_POST
@login_required
@permission_required("ai.change_servermcp", raise_exception=True)
@funzioni.richiede("mcp")
def strumenti_mcp(request, pk):
    """Quali strumenti del server sono accesi, e quali sono di sola lettura (senza conferma dell'utente)."""
    from .models import ServerMCP
    azienda = getattr(request, "azienda", None)
    server = get_object_or_404(ServerMCP, pk=pk, azienda=azienda) if azienda else None
    if server is None:
        return redirect("ai:mcp_lista")
    accesi, lettura = set(request.POST.getlist("acceso")), set(request.POST.getlist("lettura"))
    server.strumenti = [{**v, "abilitato": v["nome"] in accesi, "lettura": v["nome"] in accesi and v["nome"] in lettura} for v in server.strumenti]
    server.save(update_fields=["strumenti"])
    messages.success(request, f"Strumenti accesi: {sum(v['abilitato'] for v in server.strumenti)}.")
    return redirect("ai:mcp_dettaglio", pk=pk)


def _mio_documento(request, pk, conversazione=None):
    """Un documento dell'utente (della conversazione, se data), o None."""
    if not str(pk or "").isdigit():
        return None
    qs = DocumentoChat.objects.filter(pk=pk, utente=request.user, conversazione__nascosta=False)
    return qs.filter(conversazione=conversazione).first() if conversazione is not None else qs.first()


def _tela(request, d, **extra):
    return render(request, "ai/_tela.html", {"documento": d, "versioni": d.versioni.all()[:20], **extra})


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def documento(request, pk):
    """L'editor accanto alla chat (anche ricaricato dopo una risposta di Ada); fuori da HTMX porta alla chat."""
    d = _mio_documento(request, pk)
    if d is None:
        raise Http404
    if not request.headers.get("HX-Request"):
        return redirect(f"{reverse('ai:conversazione', args=[d.conversazione_id])}?documento={d.pk}")
    return _tela(request, d)


@require_POST
@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def salva_documento(request, pk):
    d = _mio_documento(request, pk)
    if d is None:
        raise Http404
    try:
        vista = int(request.POST.get("versione", ""))
    except ValueError:
        vista = -1
    try:
        d = documenti_chat.nuova_versione(d, request.POST.get("testo", "").replace("\r\n", "\n"), VersioneDocumento.UTENTE, versione_vista=vista)
    except documenti_chat.Conflitto:
        d.refresh_from_db()
        return _tela(request, d, avviso="Nel frattempo il documento è cambiato: le tue modifiche non sono salvate. Eccole qui sotto, da ricopiare.",
                     non_salvato=request.POST.get("testo", ""))
    except ErroreStrumento as e:
        return _tela(request, d, avviso=str(e), non_salvato=request.POST.get("testo", ""))
    return _tela(request, d, salvato=True)


@require_POST
@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def ripristina_documento(request, pk, numero):
    d = _mio_documento(request, pk)
    if d is None:
        raise Http404
    versione = get_object_or_404(VersioneDocumento, documento=d, numero=numero)
    d = documenti_chat.nuova_versione(d, versione.testo, VersioneDocumento.UTENTE)
    return _tela(request, d, avviso=f"Ripristinata la versione {numero}: è diventata la versione {d.versione}.")


@require_POST
@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def stella_documento(request, pk):
    d = _mio_documento(request, pk)
    if d is None:
        raise Http404
    d.salvato = not d.salvato
    d.save(update_fields=["salvato"])
    return _tela(request, d)


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def scarica_documento(request, pk, formato):
    from . import condivisione
    d = condivisione.leggibile(DocumentoChat, request.user, pk)
    if d is None or formato not in ("md", "docx", "pdf"):
        raise Http404
    nome = get_valid_filename(d.titolo) or "documento"
    if formato == "md":
        risposta = HttpResponse(f"# {d.titolo}\n\n{d.testo}", content_type="text/markdown; charset=utf-8")
    elif formato == "pdf":
        from core import report
        try:
            risposta = HttpResponse(documenti_chat.in_pdf(d), content_type="application/pdf")
        except report.ReportNonDisponibile as e:
            return HttpResponse(str(e), status=503, content_type="text/plain; charset=utf-8")
    else:
        risposta = HttpResponse(documenti_chat.in_word(d), content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    risposta["Content-Disposition"] = content_disposition_header(True, f"{nome}.{formato}")
    return risposta


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def trascrivi_voce(request):
    """L'audio del microfono in testo, con Whisper sui nostri server: il testo torna nel campo, da rileggere."""
    azienda = getattr(request, "azienda", None)
    file = request.FILES.get("audio")
    if not voce.dettatura_disponibile(azienda) or file is None:
        return JsonResponse({"errore": "La dettatura non è attiva."}, status=400)
    try:
        return JsonResponse({"testo": voce.trascrivi(file, request.POST.get("lingua", ""))})
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)


def _messaggio_da_leggere(request, pk):
    return get_object_or_404(MessaggioChat, pk=pk, ruolo=MessaggioChat.ASSISTENTE, conversazione__utente=request.user,
                             conversazione__nascosta=False)


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def parti_voce(request, pk):
    m = _messaggio_da_leggere(request, pk)
    if voce.servizio_per(getattr(request, "azienda", None)) is None:
        return JsonResponse({"errore": "La lettura delle risposte non è attiva."}, status=400)
    return JsonResponse({"parti": len(voce.parti(voce.da_leggere(m.testo)))})


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("voce")
def audio_voce(request, pk, parte):
    m = _messaggio_da_leggere(request, pk)
    servizio = voce.servizio_per(getattr(request, "azienda", None))
    if servizio is None:
        raise Http404
    testo = voce.da_leggere(m.testo)
    pezzi = voce.parti(testo)
    if not 0 <= parte < len(pezzi):
        raise Http404
    try:
        audio, tipo = voce.audio_di(servizio, pezzi[parte], voce.lingua_di(testo))
    except voce.ErroreVoce as e:
        return JsonResponse({"errore": str(e)}, status=502)
    risposta = HttpResponse(audio, content_type=tipo)
    risposta["Cache-Control"] = "private, max-age=3600"
    return risposta


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
def scrivi_con_ada(request, campo):
    """Avvia la bozza di un campo di istruzioni; il browser chiede l'esito finché Ada non ha finito."""
    from . import aiuto_testi
    voce = aiuto_testi.CAMPI.get(campo)
    if voce is None:
        raise Http404
    if not request.user.has_perm(voce["permesso"]):
        return JsonResponse({"errore": "Non hai il permesso di scrivere questo campo."}, status=403)
    try:
        risposte = json.loads(request.POST.get("risposte") or "{}")
    except ValueError:
        risposte = {}
    azienda = getattr(request, "azienda", None)
    if campo == aiuto_testi.LIBERO:
        turno = aiuto_testi.avvia_libero(request.user, azienda, request.POST.get("testo", ""), request.POST.get("istruzione", ""),
                                         request.POST.get("etichetta", ""), _record_per_ada(request, request.POST.get("record", "")))
    else:
        turno = aiuto_testi.avvia(request.user, azienda, campo, request.POST.get("testo", ""),
                                  risposte if isinstance(risposte, dict) else {})
    return JsonResponse({"esito": reverse("ai:esito_scrittura", args=[turno.pk])})


def _record_per_ada(request, valore):
    """«ct:pk» (o solo «ct» per un record nuovo) → il record in parole, solo se l'utente lo vede; altrimenti niente."""
    from django.contrib.contenttypes.models import ContentType
    from django.core.exceptions import PermissionDenied

    from core.generici import vista_e_oggetto
    from core.viste import registry

    from . import aiuto_testi
    ct, _, pk = (valore or "").partition(":")
    if not ct.isdigit():
        return ""
    try:
        if pk.isdigit():
            vista, obj = vista_e_oggetto(request, int(ct), int(pk), "view")
            return aiuto_testi.descrivi_record(vista, obj, messaggi=10, massimo=4000)
        modello = ContentType.objects.get_for_id(int(ct)).model_class()
        vista = registry.per_modello(modello) if modello else None
        return f"Un nuovo record di tipo {vista.verbose_name}" if vista and vista.has_add_permission(request) else ""
    except (Http404, PermissionDenied, ContentType.DoesNotExist):
        return ""


@require_POST
@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
def riassumi_record(request, ct, pk):
    """Riassunto del record con un clic: lo scrive Ada con i permessi di chi guarda; il browser chiede l'esito."""
    from core.generici import vista_e_oggetto

    from . import aiuto_testi
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    turno = aiuto_testi.avvia_riassunto(request.user, getattr(request, "azienda", None), vista, obj)
    return JsonResponse({"esito": reverse("ai:esito_scrittura", args=[turno.pk])})


@login_required
@permission_required("ai.add_conversazione", raise_exception=True)
def esito_scrittura(request, pk):
    from . import aiuto_testi
    turno = get_object_or_404(Turno, pk=pk, utente=request.user, compito=aiuto_testi.COMPITO)
    risultato = aiuto_testi.esito(turno)
    return JsonResponse(risultato if risultato is not None else {"in_corso": True})


@require_POST
@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def carica_archivio(request, pk):
    """File o una cartella intera dal PC, dall'albero del progetto: nella cartella dei Documenti collegata (sottocartelle
    comprese) se c'è, altrimenti tra i file del progetto."""
    from . import archivio
    progetto = _mio_progetto(request, pk)
    if progetto is None:
        raise Http404
    file, percorsi = request.FILES.getlist("file"), request.POST.getlist("percorso")
    if progetto.cartella_documenti and archivio.attivo():
        radice = archivio.cartella(request.user, progetto.azienda, progetto.cartella_documenti, scrittura=True)
        if radice is None:
            return JsonResponse({"errore": "Non puoi caricare file nella cartella dei Documenti di quest'area di lavoro."}, status=403)
        caricati, errori = archivio.carica_cartella(request.user, progetto.azienda, radice, file, percorsi)
        return JsonResponse({"caricati": len(caricati), "errori": errori[:10]}, status=400 if errori and not caricati else 200)
    if not request.user.has_perm("ai.change_progettochat"):
        return JsonResponse({"errore": "Non puoi aggiungere file a quest'area di lavoro."}, status=403)
    caricati, errori = 0, []
    for f in file[:archivio.MASSIMI_FILE_CARICAMENTO]:
        try:
            core_allegati.salva(progetto, f, request.user)
            caricati += 1
        except AllegatoNonValido as e:
            errori.append(str(e))
    return JsonResponse({"caricati": caricati, "errori": errori[:10]}, status=400 if errori and not caricati else 200)


@require_POST
@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def salva_documenti(request, tipo, pk):
    """Un documento scritto con Ada (Word), un grafico (PDF con i valori) o una tabella (CSV) nell'archivio Documenti.
    Se nella cartella c'è già un file con quel nome diventa la sua versione nuova."""
    from django.utils.text import slugify

    from . import archivio, artifact
    azienda = getattr(request, "azienda", None)
    if tipo == "documento":
        d = _mio_documento(request, pk)
        if d is None:
            raise Http404
        nome, contenuto = f"{d.titolo}.docx", documenti_chat.in_word(d)
    elif tipo == "artifact":
        a = _mio_artifact(request, pk)
        try:
            dati = artifact.ricalcola(a)                   # i dati di oggi, con i permessi di oggi
        except Exception:                                  # noqa: BLE001 - vista o permessi cambiati: la fotografia
            dati = a.dati
        if a.tipo == Artifact.GRAFICO:
            if not artifact.svg_di(a, dati):
                return JsonResponse({"errore": "Questo grafico non ha dati da salvare."}, status=400)
            from core import report
            try:
                nome, contenuto = f"{a.titolo}.pdf", artifact.pdf_di(a, dati)
            except report.ReportNonDisponibile as e:
                return JsonResponse({"errore": str(e)}, status=503)
        else:
            nome, contenuto = f"{a.titolo}.csv", artifact.csv_di(a, dati).encode()
    else:
        raise Http404
    nome = nome.replace("/", "-").replace("\\", "-").strip() or f"{slugify(tipo)}.bin"
    try:
        documento = archivio.salva(request.user, azienda, request.POST.get("cartella"), nome, contenuto)
    except archivio.ArchivioNonDisponibile as e:
        return JsonResponse({"errore": str(e)}, status=403)
    except core_allegati.AllegatoNonValido as e:
        return JsonResponse({"errore": str(e)}, status=400)
    versione = f" (versione {documento.versione})" if documento.versione > 1 else ""
    return JsonResponse({"messaggio": f"Salvato in «{documento.cartella.percorso()}» come «{documento.nome}»{versione}.",
                         "url": archivio.url_documento(documento)})


@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def albero_progetto(request, pk):
    """Le sottocartelle di un progetto nella colonna di sinistra: chat, documenti, grafici e tabelle, file, con i comandi
    per caricare ed eliminare."""
    from django.contrib.contenttypes.models import ContentType

    from . import archivio
    progetto = _mio_progetto(request, pk)
    if progetto is None:
        raise Http404
    contenuti = _contenuti_progetto(request, progetto)
    radice = contenuti["cartella_progetto"]
    allegati = list(Allegato.objects.filter(content_type=ContentType.objects.get_for_model(ProgettoChat), object_id=progetto.pk).order_by("-pk"))
    corrente = int(request.GET["chat"]) if request.GET.get("chat", "").isdigit() else None
    io = request.user.pk
    puo_eliminare_chat = request.user.has_perm("ai.delete_conversazione")
    # i file solo dell'area li elimina chi la gestisce; caricarli possono tutti i membri
    puo_modificare = request.user.has_perm("ai.change_progettochat") and progetto.utente_id == io

    def voce(nome, url, nota="", attiva=False, elimina="", conferma=""):
        return {"nome": nome, "url": url, "nota": nota, "attiva": attiva, "elimina": elimina, "conferma": conferma}

    def di_altri(oggetto):                               # di un altro membro, da una chat che ha condiviso: si legge e basta
        return oggetto.utente_id != io
    chat = [voce(c.titolo, reverse("ai:conversazione", args=[c.pk]), aree.nome(c.utente) if di_altri(c) else ("condivisa" if c.condivisa else ""),
                 attiva=c.pk == corrente,
                 elimina=reverse("ai:elimina", args=[c.pk]) if puo_eliminare_chat and not di_altri(c) else "",
                 conferma=f"Eliminare la chat «{c.titolo}»?") for c in contenuti["chat_progetto"]]
    documenti = [voce(d.titolo, reverse("ai:conversazione", args=[d.conversazione_id]) + ("" if di_altri(d) else f"?documento={d.pk}"),
                      aree.nome(d.utente) if di_altri(d) else "",
                      elimina="" if di_altri(d) else reverse("ai:elimina_elemento", args=["documento", d.pk]),
                      conferma=f"Eliminare il documento «{d.titolo}» con tutte le sue versioni?") for d in contenuti["documenti_progetto"]]
    grafici = [voce(("★ " if a.salvato and not di_altri(a) else "") + a.titolo,
                    reverse("ai:conversazione", args=[a.conversazione_id]) if di_altri(a) else reverse("ai:artifact", args=[a.pk]),
                    aree.nome(a.utente) if di_altri(a) else a.get_tipo_display(),
                    elimina="" if di_altri(a) else reverse("ai:elimina_elemento", args=["artifact", a.pk]), conferma=f"Eliminare «{a.titolo}»?")
               for a in contenuti["artifact_progetto"]]
    file = [voce(d.nome, url, d.cartella.nome if d.cartella_id != radice.pk else "",
                 elimina=reverse("ai:elimina_elemento", args=["archivio", d.pk]) if contenuti["cartella_scrivibile"] else "",
                 conferma=f"Spostare «{d.nome}» nel cestino dei Documenti? Si può recuperare.") for d, url in contenuti["documenti_cartella"]]
    file += [voce(a.nome, reverse("core:allegato_scarica", args=[a.pk]), "solo dell'area",
                  elimina=reverse("core:allegato_elimina", args=[a.pk]) if puo_modificare else "",
                  conferma=f"Eliminare definitivamente «{a.nome}»?") for a in allegati]
    destinazione = (radice.percorso() if contenuti["cartella_scrivibile"] else "") if radice else (
        "i file dell'area" if request.user.has_perm("ai.change_progettochat") else "")
    gruppi = [
        ("chat", "Chat", len(contenuti["chat_progetto"]), chat),
        ("documenti", "Documenti", len(contenuti["documenti_progetto"]), documenti),
        ("artifact", "Grafici e tabelle", len(contenuti["artifact_progetto"]), grafici),
        ("file", "File", contenuti["documenti_cartella_totale"] + len(allegati), file[:archivio.MASSIMO_ELENCO * 3]),
    ]
    # i primi in vista, gli altri dietro «Mostra altre N» (aperto se c'è la chat corrente): niente barre dentro l'albero
    gruppi = [(chiave, titolo, totale, voci[:IN_VISTA_ALBERO], voci[IN_VISTA_ALBERO:], any(v["attiva"] for v in voci[IN_VISTA_ALBERO:]))
              for chiave, titolo, totale, voci in gruppi]
    return render(request, "ai/_albero_progetto.html", {"progetto": progetto, "gruppi": gruppi, "corrente": corrente,
                                                        "carica_in": destinazione, "url_dashboard": _url_dashboard(request, progetto)})


@require_POST
@login_required
@permission_required("ai.view_conversazione", raise_exception=True)
def elimina_elemento(request, tipo, pk):
    """Dall'albero del progetto: un documento scritto con Ada, un grafico o una tabella (definitivo), oppure un file
    dei Documenti (nel cestino dei Documenti, recuperabile, se l'utente può modificarlo)."""
    if tipo == "documento":
        d = _mio_documento(request, pk)
        if d is None:
            raise Http404
        d.delete()
    elif tipo == "artifact":
        _mio_artifact(request, pk).delete()
    elif tipo == "archivio":
        from . import archivio
        if not archivio.attivo():
            raise Http404
        from documenti import accesso, servizi
        documento = accesso.documenti(request.user, getattr(request, "azienda", None)).filter(pk=pk, cestinato_il__isnull=True).first()
        if documento is None:
            raise Http404
        if not accesso.puo_modificare(request.user, documento):
            return JsonResponse({"errore": "Non puoi eliminare questo file."}, status=403)
        servizi.cestina([documento])
    else:
        raise Http404
    return JsonResponse({"ok": True})


@login_required
@permission_required("ai.change_progettochat", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def cerca_collegamento(request, pk):
    """I record che l'utente vede, da collegare al progetto (come «Cerca ovunque»)."""
    progetto = _area_gestita(request, pk)
    if progetto is None:
        raise Http404
    testo = request.GET.get("q", "").strip()[:100]
    risultati = collegamenti.cerca(request, testo) if len(testo) >= 2 else []
    return render(request, "ai/_cerca_collegamento.html", {"progetto": progetto, "risultati": risultati, "testo": testo})


@require_POST
@login_required
@permission_required("ai.change_progettochat", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def collega(request, pk):
    """Collega un record al progetto, se l'utente lo vede. Da dove si è partiti (progetto o record) si torna lì."""
    progetto = _area_gestita(request, pk)
    if progetto is None:
        raise Http404
    ct, record = request.POST.get("ct", ""), request.POST.get("record", "")
    trovato = collegamenti.risolvi(request, ct, record) if ct.isdigit() and record.isdigit() else None
    if trovato is None:
        messages.error(request, "Record non trovato o non visibile.")
    else:
        CollegamentoProgetto.objects.get_or_create(progetto=progetto, content_type_id=int(ct), object_id=int(record))
        messages.success(request, f"«{trovato[1]}» collegato all'area di lavoro «{progetto.nome}».")
    indietro = request.POST.get("indietro", "")
    return redirect(indietro if indietro.startswith("/") and not indietro.startswith("//") else reverse("ai:progetto", args=[progetto.pk]))


@require_POST
@login_required
@permission_required("ai.change_progettochat", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def scollega(request, pk, collegamento):
    progetto = _area_gestita(request, pk)
    if progetto is None:
        raise Http404
    CollegamentoProgetto.objects.filter(pk=collegamento, progetto=progetto).delete()
    indietro = request.POST.get("indietro", "")
    return redirect(indietro if indietro.startswith("/") and not indietro.startswith("//") else reverse("ai:progetto", args=[progetto.pk]))


@require_POST
@login_required
@permission_required("ai.change_conversazione", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def condividi_chat(request, pk):
    """Una propria chat di un'area di lavoro: condivisa con gli altri membri (in sola lettura) o di nuovo privata."""
    c = get_object_or_404(_mie(request), pk=pk, progetto__isnull=False)
    c.condivisa = not c.condivisa
    c.save(update_fields=["condivisa"])
    messages.success(request, "Chat condivisa con l'area di lavoro: gli altri membri la leggono." if c.condivisa else "Chat di nuovo privata.")
    return redirect("ai:conversazione", pk=c.pk)


@login_required
@permission_required("ai.add_modello", raise_exception=True)
def catalogo_provider(request, pk):
    """Il catalogo dei modelli del provider: si spuntano quelli da aggiungere (gli altri restano fuori)."""
    from . import catalogo_remoto
    from .models import Provider
    provider = get_object_or_404(Provider, pk=pk)
    if provider.gestito and not request.user.is_superuser:      # fornito con il piano: i suoi modelli li decide il Global Admin
        raise PermissionDenied
    try:
        voci = catalogo_remoto.leggi(provider)
    except catalogo_remoto.CatalogoNonDisponibile as e:
        messages.error(request, str(e))
        return redirect("ai:provider_dettaglio", provider.pk)
    if request.method == "POST":
        nuovi, aggiornati = catalogo_remoto.importa(provider, voci, set(request.POST.getlist("scelti")))
        messages.success(request, f"Modelli aggiunti: {nuovi}" + (f", aggiornati: {aggiornati}" if aggiornati else "")
                         + ". Controlla i prezzi e mettili nella catena di un profilo per usarli in chat.")
        return redirect(f"{reverse('ai:modelli_lista')}?f_provider={provider.pk}")
    return render(request, "ai/catalogo_provider.html", {"provider": provider, "voci": voci})


@require_POST
@login_required
@permission_required("ai.add_progettochat", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def area_da_record(request, ct, pk):
    """Un'area di lavoro nuova per un record (un progetto, un cliente…): collegata al record, con i colleghi che il
    record cita (responsabile, membri) già dentro; chi l'ha creata li cambia quando vuole."""
    from core.generici import vista_e_oggetto
    vista, obj = vista_e_oggetto(request, ct, pk, "view")
    azienda = getattr(request, "azienda", None)
    area = ProgettoChat.objects.create(utente=request.user, azienda=azienda, nome=str(obj)[:80])
    CollegamentoProgetto.objects.create(progetto=area, content_type_id=ct, object_id=obj.pk)
    candidati = set(aree.candidati(azienda, request.user).values_list("pk", flat=True))
    persone = [u for u in collegamenti.persone_del_record(obj) if u.pk in candidati]
    aree.imposta_membri(area, persone)
    aree.imposta_corrente(request.user, area)
    from django.contrib import messages
    messages.success(request, f"Area di lavoro «{area.nome}» creata e collegata" + (
        f", condivisa con {', '.join(aree.nome(u) for u in persone)}." if persone else ". Aggiungi i colleghi dalle impostazioni dell'area."))
    return redirect(reverse("ai:progetto", args=[area.pk]))


def _aree_dell_app(request, slug):
    """Le aree che l'utente vede collegate all'app (la lista è piccola: si filtra in Python, vale su ogni database)."""
    return [a for a in aree.visibili(request.user, getattr(request, "azienda", None)).select_related("utente")
            if slug in (a.app_collegate or [])]


def mostra_aree_nell_app(request, slug):
    """La voce c'è per chi usa le aree di lavoro: da lì si collega anche la prima."""
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.has_perm("ai.view_progettochat")) and funzioni.attiva("aree_di_lavoro")


@login_required
@permission_required("ai.view_progettochat", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def aree_dell_app(request):
    """«Aree di lavoro» dentro un'app (CRM, Progetti…): le aree collegate a quell'app con quello che ci è nato."""
    from django.apps import apps as django_apps

    from core.registry import modules
    slug = request.resolver_match.namespace.split(":")[0]
    manifest = modules.manifests_attivi().get(slug)
    dashboard = django_apps.is_installed("grafici") and request.user.has_perm("grafici.view_pagina")
    voci = [{"area": a, **collegamenti.contenuto(request.user, a), "dashboard": reverse("grafici:pagina_area", args=[a.pk]) if dashboard else ""}
            for a in _aree_dell_app(request, slug)]
    gestite = [a for a in aree.visibili(request.user, getattr(request, "azienda", None)) if a.utente_id == request.user.pk]
    return render(request, "ai/aree_app.html", {"voci": voci, "nome_app": manifest.name if manifest else slug, "slug": slug,
                                                 "da_collegare": [a for a in gestite if slug not in (a.app_collegate or [])],
                                                 "puo_creare": request.user.has_perm("ai.add_progettochat")})


@require_POST
@login_required
@permission_required("ai.change_progettochat", raise_exception=True)
@funzioni.richiede("aree_di_lavoro")
def collega_app(request, pk):
    """Collega o scollega un'app a un'area (solo chi l'ha creata), dalla pagina «Aree di lavoro» dell'app o dall'area."""
    from core.registry import modules
    area = _area_gestita(request, pk)
    slug = request.POST.get("app", "")
    if area is None or slug not in modules.manifests_attivi() or slug == "ai":
        raise Http404
    app = list(area.app_collegate or [])
    if request.POST.get("azione") == "scollega":
        app = [s for s in app if s != slug]
    elif slug not in app:
        app.append(slug)
    area.app_collegate = app
    area.save(update_fields=["app_collegate"])
    prossimo = request.POST.get("da", "")
    return redirect(prossimo if prossimo.startswith("/") and not prossimo.startswith("//") else reverse("ai:progetto", args=[area.pk]))


@login_required
@permission_required("ai.view_strumentospento", raise_exception=True)
def strumenti(request):
    """Gli strumenti dell'assistente: funzione, app, rischio e se sono disponibili (se no, perché). Si spengono per
    l'azienda corrente (permesso di modifica) o per tutta l'istanza (Global Admin). Si può solo togliere."""
    from . import elenco_strumenti
    from .models import StrumentoSpento
    azienda = getattr(request, "azienda", None)
    if request.method == "POST":
        nome, livello, azione = request.POST.get("nome", ""), request.POST.get("livello"), request.POST.get("azione")
        if not elenco_strumenti.esiste(nome) or livello not in ("istanza", "azienda") or azione not in ("spegni", "accendi"):
            return HttpResponse("richiesta non valida", status=400)
        if livello == "istanza" and not request.user.is_superuser:
            raise PermissionDenied
        if livello == "azienda" and (azienda is None or not request.user.has_perm("ai.change_strumentospento")):
            raise PermissionDenied
        dove = None if livello == "istanza" else azienda
        if azione == "spegni":
            StrumentoSpento.objects.get_or_create(nome=nome, azienda=dove, defaults={"spento_da": request.user})
            messages.success(request, f"«{nome}» spento {'per tutta l’istanza' if dove is None else f'per {azienda}'}.")
        else:
            for riga in StrumentoSpento.objects.filter(nome=nome, azienda=dove):
                riga.delete()                            # una per una: il registro delle modifiche le vede
            messages.success(request, f"«{nome}» riacceso {'per tutta l’istanza' if dove is None else f'per {azienda}'}.")
        return redirect(f"{reverse('ai:strumenti')}#{nome}")
    righe = elenco_strumenti.elenco(azienda)
    return render(request, "ai/strumenti.html", {
        "righe": righe, "disponibili": sum(1 for r in righe if not r["motivi"]), "azienda": azienda,
        "puo_azienda": azienda is not None and request.user.has_perm("ai.change_strumentospento"),
        "puo_istanza": request.user.is_superuser})

