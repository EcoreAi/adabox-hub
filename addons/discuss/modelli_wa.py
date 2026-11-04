"""I modelli di WhatsApp: l'unico modo di scrivere a un cliente dopo le 24 ore dal suo ultimo messaggio.

Il testo lo approva Meta, chi scrive riempie solo le parti variabili. Parte solo per mano di un operatore: l'AI non ne manda,
perché un messaggio non richiesto lo deve decidere una persona, e quelli di marketing richiedono il consenso del cliente."""
import logging

import httpx2 as httpx
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core import parametri

from . import connettori, eventi, servizi
from .models import Canale, Connessione, ConversazioneEsterna, Messaggio, ModelloWhatsApp

log = logging.getLogger("discuss.modelli")
MASSIMO_VALORE = 200
STATI_META = {"APPROVED": ModelloWhatsApp.APPROVATO, "REJECTED": ModelloWhatsApp.RIFIUTATO, "PENDING": ModelloWhatsApp.IN_ATTESA,
              "PAUSED": ModelloWhatsApp.RIFIUTATO, "DISABLED": ModelloWhatsApp.RIFIUTATO}


def valido(valore):
    """Meta non accetta a capo, tabulazioni né più di quattro spazi di fila nelle parti variabili."""
    return bool(valore.strip()) and len(valore) <= MASSIMO_VALORE and "\n" not in valore and "\t" not in valore and "    " not in valore


@transaction.atomic
def manda(conv, autore, modello, valori):
    m = Messaggio.objects.create(canale=conv.canale, autore=autore, corpo=modello.componi(valori),
                                 dati_modello={"nome": modello.nome, "lingua": modello.lingua, "valori": valori})
    eventi.emetti("nuovo", conv.canale, m=m.pk, autore=autore.pk, menzionati=[])
    servizi.Iscrizione.objects.filter(canale=conv.canale, utente=autore).update(ultimo_letto=m.pk)
    connettori.accoda(m)
    return m


def _conversazione(request, pk):
    canale = get_object_or_404(Canale, pk=pk, livechat=True, archiviato=False)
    if not request.user.has_perm("discuss.add_messaggio") or servizi.iscrizione(request.user, canale) is None:
        raise Http404
    conv = get_object_or_404(ConversazioneEsterna.objects.select_related("connessione", "canale"), canale=canale, connessione__tipo=Connessione.WHATSAPP)
    return conv


@login_required
def manda_vista(request, pk):
    conv = _conversazione(request, pk)
    approvati = conv.connessione.modelli.filter(stato=ModelloWhatsApp.APPROVATO)
    if request.method != "POST":
        voci = list(approvati)
        for m in voci:
            m.indici = range(1, m.n_variabili + 1)
        return render(request, "discuss/_modello_whatsapp.html", {"canale": conv.canale, "voci": voci, "conv": conv})
    modello = approvati.filter(pk=request.POST.get("modello") if str(request.POST.get("modello", "")).isdigit() else 0).first()
    if modello is None:
        messages.error(request, "Questo modello non è approvato.")
        return redirect("discuss:canale", pk=pk)
    valori = [request.POST.get(f"v{i}", "").strip() for i in range(1, modello.n_variabili + 1)]
    if not all(valido(v) for v in valori):
        messages.error(request, "Compila tutte le parti variabili, senza andare a capo: lo chiede WhatsApp.")
        return redirect("discuss:canale", pk=pk)
    manda(conv, request.user, modello, valori)
    return redirect("discuss:canale", pk=pk)


# --- rapporti con Meta ---

def _base():
    return f"https://graph.facebook.com/{parametri.leggi('discuss.versione_graph') or 'v24.0'}"


def a_meta(m):
    """Chiede a Meta di approvare il modello. In prova non esce nulla: approva chi prova, dalla sandbox."""
    c = m.connessione
    if c.sandbox:
        return
    if not c.id_account:
        raise connettori.ErroreConsegna("Manca l'ID dell'account WhatsApp Business nella connessione.")
    corpo = {"type": "BODY", "text": m.corpo}
    if m.n_variabili:
        corpo["example"] = {"body_text": [[f"esempio {i}" for i in range(1, m.n_variabili + 1)]]}
    try:
        r = httpx.post(f"{_base()}/{c.id_account}/message_templates", headers={"Authorization": f"Bearer {c.token()}"}, timeout=15, trust_env=False,
                       json={"name": m.nome, "language": m.lingua, "category": m.categoria, "components": [corpo]})
        dati = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise connettori.ErroreConsegna("Meta non raggiungibile", temporaneo=True) from e
    if r.status_code >= 300:
        raise connettori.ErroreConsegna((dati.get("error") or {}).get("message") or f"Errore {r.status_code}")


def sincronizza(c):
    """Lo stato dei modelli secondo Meta. Quanti ne ha aggiornati."""
    if c.sandbox or not c.id_account or c.tipo != Connessione.WHATSAPP:
        return 0
    try:
        r = httpx.get(f"{_base()}/{c.id_account}/message_templates", headers={"Authorization": f"Bearer {c.token()}"},
                      params={"fields": "name,language,status,rejected_reason", "limit": 200}, timeout=15, trust_env=False)
        dati = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise connettori.ErroreConsegna("Meta non raggiungibile", temporaneo=True) from e
    aggiornati = 0
    for voce in dati.get("data") or []:
        stato = STATI_META.get(voce.get("status"))
        if stato is None:
            continue
        motivo = voce.get("rejected_reason", "") if stato == ModelloWhatsApp.RIFIUTATO else ""
        aggiornati += ModelloWhatsApp.objects.filter(connessione=c, nome=voce.get("name"), lingua=voce.get("language")).exclude(stato=stato).update(stato=stato, motivo=str(motivo)[:300])
    return aggiornati


def sincronizza_tutti():
    """Lavoro pianificato: una connessione che non risponde non ferma le altre."""
    totale = 0
    for c in Connessione.objects.filter(tipo=Connessione.WHATSAPP, sandbox=False, attiva=True).exclude(id_account=""):
        try:
            totale += sincronizza(c)
        except connettori.ErroreConsegna as e:
            log.warning("modelli della connessione %s: %s", c.pk, e)
    return f"modelli aggiornati: {totale}"


@login_required
@require_POST
def a_meta_vista(request, pk):
    if not request.user.has_perm("discuss.change_modellowhatsapp"):
        raise PermissionDenied
    m = get_object_or_404(ModelloWhatsApp.objects.select_related("connessione"), pk=pk)
    try:
        a_meta(m)
        ModelloWhatsApp.objects.filter(pk=m.pk).update(stato=ModelloWhatsApp.IN_ATTESA, motivo="")
        messages.success(request, "Modello inviato: lo stato si aggiorna appena Meta risponde." if not m.connessione.sandbox else "In prova: approvalo o rifiutalo dalla sandbox.")
    except connettori.ErroreConsegna as e:
        messages.error(request, f"Meta non ha accettato: {e}")
    return redirect("discuss:modelliwa_dettaglio", pk=m.pk)
