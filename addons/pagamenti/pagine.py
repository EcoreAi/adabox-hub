"""Pagine pubbliche e del portale: «Paga ora», ritorno dal pagamento, pagamento simulato, webhook di Stripe e PayPal."""
from django.contrib import messages
from django.core import signing
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import fornitori, servizi
from .models import FornitorePagamento, Pagamento


def _vai_a_pagare(request, fattura, indietro):
    try:
        pagamento = servizi.avvia(fattura)
    except fornitori.ErrorePagamento as e:
        messages.error(request, f"Il pagamento non è partito: {e}")
        return redirect(indietro)
    return redirect(pagamento.url_pagamento)


def fattura(request, token):
    """La pagina del link firmato (dalle email): riepilogo della fattura e «Paga ora», senza accesso al portale."""
    f = servizi.da_token(token)
    if f is None:
        return render(request, "pagamenti/fattura.html", {"invalido": True}, status=400)
    if request.method == "POST" and servizi.pagabile(f):
        return _vai_a_pagare(request, f, request.path)
    return render(request, "pagamenti/fattura.html", {"fattura": f, "pagabile": servizi.pagabile(f)})


def esito(request, pk, firma):
    """Il ritorno dal pagamento: si chiede al fornitore com'è andata (il browser non basta a dire che è pagato)."""
    try:
        if signing.loads(firma, salt="pagamenti.esito") != pk:
            raise signing.BadSignature
    except signing.BadSignature:
        raise Http404
    pagamento = get_object_or_404(Pagamento.objects.select_related("fattura", "fornitore"), pk=pk)
    annullato = request.GET.get("annullato") == "1" and pagamento.stato == Pagamento.AVVIATO
    errore = ""
    if not annullato:
        try:
            pagamento = servizi.verifica(pagamento)
        except fornitori.ErrorePagamento as e:
            errore = str(e)
    return render(request, "pagamenti/esito.html", {"pagamento": pagamento, "annullato": annullato, "errore": errore,
                                                     "link_fattura": servizi.link(pagamento.fattura)})


def finto(request, pk):
    """La pagina del fornitore simulato (prove e demo): un bottone paga, l'altro annulla."""
    pagamento = get_object_or_404(Pagamento.objects.select_related("fattura", "fornitore"), pk=pk,
                                  fornitore__tipo=FornitorePagamento.FINTO)
    firma = signing.dumps(pagamento.pk, salt="pagamenti.esito")
    if request.method == "POST" and pagamento.stato == Pagamento.AVVIATO:
        if request.POST.get("azione") == "paga":
            servizi.conferma(pagamento, f"simulato-{pagamento.pk}")
            return redirect("pagamenti:esito", pk=pagamento.pk, firma=firma)
        return redirect(f"{request.build_absolute_uri('/')[:-1]}{_esito_url(pagamento.pk, firma)}?annullato=1")
    return render(request, "pagamenti/finto.html", {"pagamento": pagamento})


def _esito_url(pk, firma):
    from django.urls import reverse
    return reverse("pagamenti:esito", args=[pk, firma])


@csrf_exempt
@require_POST
def webhook(request, pk):
    """Gli eventi del fornitore, verificati (Stripe con il segreto, PayPal chiedendo a PayPal): un pagamento completato
    diventa un incasso anche se il cliente chiude la pagina prima di tornare."""
    fornitore = FornitorePagamento.objects.filter(pk=pk, tipo__in=[FornitorePagamento.STRIPE, FornitorePagamento.PAYPAL]).first()
    if fornitore is None:
        return HttpResponse(status=404)
    if fornitore.tipo == FornitorePagamento.PAYPAL:
        return _webhook_paypal(request, fornitore)
    try:
        evento = fornitori.evento_stripe(fornitore, request.body, request.headers.get("Stripe-Signature", ""))
    except (fornitori.ErrorePagamento, ValueError):
        return HttpResponseBadRequest("firma non valida")
    if evento.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        sessione = (evento.get("data") or {}).get("object") or {}
        pagamento = Pagamento.objects.filter(fornitore=fornitore, id_esterno=sessione.get("id", "")).first()
        if pagamento is not None and sessione.get("payment_status") == "paid":
            servizi.conferma(pagamento, sessione.get("payment_intent") or sessione.get("id", ""))
    return HttpResponse(status=200)


def _webhook_paypal(request, fornitore):
    try:
        evento = fornitori.evento_paypal(fornitore, request.body, request.headers)
    except fornitori.ErrorePagamento:
        return HttpResponseBadRequest("firma non valida")
    if evento.get("event_type") in ("CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED", "PAYMENT.CAPTURE.COMPLETED"):
        ordine = fornitori.ordine_dell_evento(evento)
        pagamento = Pagamento.objects.filter(fornitore=fornitore, id_esterno=ordine).first() if ordine else None
        if pagamento is not None:
            try:
                servizi.verifica(pagamento)                 # cattura se serve, poi l'incasso una volta sola
            except fornitori.ErrorePagamento:
                return HttpResponse(status=503)             # PayPal riprova più tardi
    return HttpResponse(status=200)


def paga_dal_portale(request, pk):
    """«Paga ora» nelle fatture del portale clienti: solo fatture del cliente che ha fatto l'accesso."""
    from fatturazione.portale import _fatture
    from portale.accesso import di
    if request.method != "POST":
        return HttpResponse(status=405)
    if not request.user.is_authenticated:
        return redirect("login")
    f = get_object_or_404(_fatture(di(request)), pk=pk)
    return _vai_a_pagare(request, f, "fatturazione:portale_fatture")
