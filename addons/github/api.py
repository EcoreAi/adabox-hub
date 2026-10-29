"""Chiamate all'API di GitHub con il token del repository (in background, con i ritentativi dei lavori)."""
import json
import urllib.request

from django.conf import settings
from django.urls import reverse

from core import chatter
from progetti.models import Compito

from .models import Collegamento, Repository, riferimento

API = "https://api.github.com"
TIMEOUT = 20


def chiama(repository, metodo, percorso, dati=None):
    richiesta = urllib.request.Request(
        f"{API}{percorso}", method=metodo, data=json.dumps(dati).encode() if dati is not None else None,
        headers={"Authorization": f"Bearer {repository.token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                 "User-Agent": "adabox-hub"})
    with urllib.request.urlopen(richiesta, timeout=TIMEOUT) as risposta:
        return json.loads(risposta.read() or b"{}")


def crea_issue(compito_id, repository_id, utente_id=None):
    """Lavoro: apre la issue del compito (una sola per repository) e la collega."""
    compito = Compito.objects.get(pk=compito_id)
    repository = Repository.objects.get(pk=repository_id, progetto_id=compito.progetto_id)
    gia = Collegamento.objects.filter(compito=compito, repository=repository, tipo=Collegamento.ISSUE).first()
    if gia:
        return f"già aperta: #{gia.chiave}"
    link = settings.SITO_URL + reverse("progetti:compiti_dettaglio", args=[compito.pk])
    issue = chiama(repository, "POST", f"/repos/{repository.nome}/issues", {
        "title": f"[{riferimento(compito)}] {compito.titolo}",
        "body": f"{compito.descrizione}\n\n---\nCompito {riferimento(compito)}: {link}".strip()})
    Collegamento.objects.create(compito=compito, repository=repository, tipo=Collegamento.ISSUE,
                                chiave=str(issue["number"]), titolo=issue.get("title", "")[:300],
                                url=issue["html_url"], stato=Collegamento.APERTA)
    chatter.scrivi(compito, None, f"Aperta la issue #{issue['number']} su {repository.nome}: {issue['html_url']}",
                   tipo="nota")
    return f"issue #{issue['number']}"
