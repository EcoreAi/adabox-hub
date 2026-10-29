"""Webhook di GitHub (un indirizzo per repository, firmato con HMAC SHA-256 sul segreto del repository).

Eventi: push (commit che citano un compito), pull_request (collegamento con lo stato; al merge i compiti citati si
completano se il repository lo prevede), issues (stato delle issue collegate), release (pubblicata: il rilascio del
progetto con la stessa versione viene pubblicato), ping."""
import hashlib
import hmac
import json
import logging

from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core import chatter
from progetti.models import Compito, FaseCompito, Rilascio

from .models import Collegamento, Repository, riferimenti

log = logging.getLogger("github")


def firma_valida(repository, corpo, firma):
    atteso = "sha256=" + hmac.new(repository.segreto.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(atteso, firma or "")


def _compiti(repository, ids):
    return list(Compito.objects.filter(pk__in=ids, progetto_id=repository.progetto_id))


def _collega(repository, compito, tipo, chiave, **campi):
    """Crea o aggiorna il collegamento; True se è nuovo."""
    oggetto, nuovo = Collegamento.objects.update_or_create(compito=compito, repository=repository, tipo=tipo,
                                                           chiave=str(chiave), defaults=campi)
    return nuovo


def push(repository, dati):
    ramo = dati.get("ref", "").removeprefix("refs/heads/")
    n = 0
    for commit in dati.get("commits", []):
        messaggio = commit.get("message", "")
        autore = (commit.get("author") or {}).get("username") or (commit.get("author") or {}).get("name", "")
        for compito in _compiti(repository, riferimenti(messaggio, ramo)):
            prima_riga = messaggio.splitlines()[0][:300] if messaggio else ""
            if _collega(repository, compito, Collegamento.COMMIT, commit["id"], titolo=prima_riga,
                        url=commit.get("url", repository.url), autore=autore[:100]):
                chatter.scrivi(compito, None, f"Commit {commit['id'][:7]} di {autore or '—'} su {ramo}: {prima_riga}",
                               tipo="nota")
                n += 1
    return f"{n} commit collegati"


def chiudi(compito, motivo):
    """Completa il compito (prima fase chiusa) se non lo è già e nessun compito lo blocca."""
    if compito.fase.chiusa:
        return False
    if aperti := compito.bloccanti_aperti():
        chatter.scrivi(compito, None, f"{motivo}, ma il compito resta aperto: lo bloccano "
                                      + ", ".join(f"«{c}»" for c in aperti) + ".", tipo="nota")
        return False
    fase = FaseCompito.objects.filter(chiusa=True).order_by("ordine", "pk").first()
    if fase is None:
        return False
    vecchi = chatter.valori(compito, ["fase"])
    compito.fase = fase
    compito.save()
    chatter.traccia(compito, vecchi)
    chatter.scrivi(compito, None, f"{motivo}: compito completato.", tipo="nota")
    return True


def pull_request(repository, dati):
    pr = dati.get("pull_request") or {}
    numero, azione = pr.get("number"), dati.get("action")
    if numero is None:
        return "senza pull request"
    stato = Collegamento.UNITA if pr.get("merged") else (Collegamento.CHIUSA if pr.get("state") == "closed"
                                                         else Collegamento.APERTA)
    autore = (pr.get("user") or {}).get("login", "")
    ids = riferimenti(pr.get("title"), pr.get("body"), (pr.get("head") or {}).get("ref"))
    for compito in _compiti(repository, ids):
        if _collega(repository, compito, Collegamento.PULL_REQUEST, numero, titolo=(pr.get("title") or "")[:300],
                    url=pr.get("html_url", repository.url), stato=stato, autore=autore[:100]):
            chatter.scrivi(compito, None, f"Pull request #{numero} di {autore or '—'}: {pr.get('title', '')}",
                           tipo="nota")
        if azione == "closed" and stato == Collegamento.UNITA and repository.chiudi_al_merge:
            chiudi(compito, f"Pull request #{numero} unita")
    return f"pull request #{numero} {stato}"


def issues(repository, dati):
    issue = dati.get("issue") or {}
    stato = Collegamento.CHIUSA if issue.get("state") == "closed" else Collegamento.APERTA
    n = Collegamento.objects.filter(repository=repository, tipo=Collegamento.ISSUE,
                                    chiave=str(issue.get("number"))).update(stato=stato)
    return f"{n} issue aggiornate"


def release(repository, dati):
    if dati.get("action") not in ("published", "released"):
        return "ignorata"
    tag = ((dati.get("release") or {}).get("tag_name") or "").strip()
    versione = tag[1:] if tag[:1] in ("v", "V") else tag
    rilascio = Rilascio.objects.filter(progetto_id=repository.progetto_id, versione__in={tag, versione}).first()
    if rilascio is None:
        return f"nessun rilascio {versione}"
    rilascio.rilascia()
    return f"rilascio {rilascio.versione} pubblicato"


EVENTI = {"push": push, "pull_request": pull_request, "issues": issues, "release": release}


@csrf_exempt
@require_POST
def ricevi(request, pk):
    repository = get_object_or_404(Repository, pk=pk, attivo=True)
    if not firma_valida(repository, request.body, request.headers.get("X-Hub-Signature-256")):
        return HttpResponseForbidden("firma non valida")
    evento = request.headers.get("X-GitHub-Event", "")
    if evento == "ping":
        return JsonResponse({"ok": True, "pong": True})
    gestore = EVENTI.get(evento)
    if gestore is None:
        return HttpResponse(status=204)
    try:
        dati = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("JSON non valido (imposta Content type: application/json)")
    with transaction.atomic():
        esito = gestore(repository, dati)
    log.info("github %s %s: %s", repository, evento, esito)
    return JsonResponse({"ok": True, "esito": esito})
