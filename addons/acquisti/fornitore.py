"""La pagina del fornitore, da un link firmato senza accesso: vede l'ordine, lo conferma con la data di consegna,
segnala un ritardo, carica DDT o fattura. Tutto finisce nel registro dell'ordine; il buyer riceve una nota."""
import datetime

from django.conf import settings
from django.core import signing
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from core import allegati, chatter

from .models import OrdineAcquisto

SALE = "acquisti.fornitore"
GIORNI = 120


def link(ordine):
    token = signing.dumps([ordine.pk, ordine.fornitore_id], salt=SALE)
    return f"{settings.SITO_URL}{reverse('acquisti:fornitore', args=[token])}"


def da_token(token):
    try:
        pk, fornitore_id = signing.loads(token, salt=SALE, max_age=GIORNI * 86400)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    return OrdineAcquisto.objects.filter(pk=pk, fornitore_id=fornitore_id).select_related("fornitore", "azienda", "buyer").first()


def _data(testo):
    try:
        return datetime.date.fromisoformat(testo) if testo else None
    except ValueError:
        return None


def pagina(request, token):
    ordine = da_token(token)
    if ordine is None or ordine.stato == OrdineAcquisto.ANNULLATO:
        return render(request, "acquisti/fornitore.html", {"invalido": True}, status=400)
    esito, errore = "", ""
    if request.method == "POST":
        azione, nome = request.POST.get("azione"), request.POST.get("nome", "").strip()[:120]
        data, nota = _data(request.POST.get("data")), request.POST.get("nota", "").strip()[:1000]
        chi = f"{nome or 'Il fornitore'} ({ordine.fornitore})"
        if azione == "conferma":
            if data is None:
                errore = "Indica la data di consegna prevista."
            else:
                ordine.consegna_prevista = data
                if request.POST.get("riferimento"):
                    ordine.riferimento_fornitore = request.POST["riferimento"].strip()[:100]
                ordine.save(update_fields=["consegna_prevista", "riferimento_fornitore"])
                chatter.scrivi(ordine, None, f"{chi} conferma l'ordine con consegna il {data:%d/%m/%Y}." + (f" {nota}" if nota else ""), tipo="nota")
                esito = "Grazie: conferma registrata."
        elif azione == "ritardo":
            if data is None:
                errore = "Indica la nuova data di consegna."
            else:
                prima = ordine.consegna_prevista
                ordine.consegna_prevista = data
                ordine.save(update_fields=["consegna_prevista"])
                chatter.scrivi(ordine, None, f"{chi} segnala un ritardo: consegna il {data:%d/%m/%Y}" + (f" invece del {prima:%d/%m/%Y}" if prima else "")
                               + (f". Motivo: {nota}" if nota else "."), tipo="nota")
                esito = "Grazie: il nuovo termine è registrato."
        elif azione == "documento":
            file = request.FILES.get("file")
            if file is None:
                errore = "Scegli il file da caricare."
            else:
                try:
                    a = allegati.salva(ordine, file)
                except allegati.AllegatoNonValido as e:
                    errore = str(e)
                else:
                    tipo = {"ddt": "DDT", "fattura": "fattura"}.get(request.POST.get("tipo"), "documento")
                    chatter.scrivi(ordine, None, f"{chi} ha caricato {tipo}: {a.nome}." + (f" {nota}" if nota else ""), tipo="nota", allegati=[a])
                    esito = "Grazie: documento ricevuto."
    return render(request, "acquisti/fornitore.html", {"ordine": ordine, "righe": ordine.righe.select_related("prodotto"),
                                                       "esito": esito, "errore": errore, "oggi": timezone.localdate()})
