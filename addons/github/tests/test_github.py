import hashlib
import hmac
import io
import json
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

import progetti
from core.models import Azienda, Messaggio
from github import api
from github.models import Collegamento, Repository, ramo_suggerito, riferimenti
from progetti.models import Compito, FaseCompito, Progetto, Rilascio


@pytest.fixture
def scena(db):
    cartella = Path(progetti.__file__).parent
    call_command("loaddata", str(cartella / "data" / "fasi.json"), str(cartella / "data" / "tipi.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    progetto = Progetto.objects.create(azienda=azienda, nome="Gestionale")
    repo = Repository.objects.create(azienda=azienda, progetto=progetto, nome="ichnobyte/gestionale")
    compito = Compito.objects.create(azienda=azienda, progetto=progetto, titolo="Export Excel degli ordini")
    altrui = Compito.objects.create(azienda=azienda, progetto=Progetto.objects.create(azienda=azienda, nome="Altro"),
                                    titolo="Di un altro progetto")
    return {"azienda": azienda, "progetto": progetto, "repo": repo, "compito": compito, "altrui": altrui}


def _invia(client, repo, evento, dati, segreto=None):
    corpo = json.dumps(dati).encode()
    firma = "sha256=" + hmac.new((segreto or repo.segreto).encode(), corpo, hashlib.sha256).hexdigest()
    return client.post(f"/github/webhook/{repo.pk}/", corpo, content_type="application/json",
                       HTTP_X_GITHUB_EVENT=evento, HTTP_X_HUB_SIGNATURE_256=firma)


def test_riferimenti_e_ramo(scena):
    c = scena["compito"]
    assert riferimenti("Fix ADA-12 e ada-7", "ada-12-export", "nada-99 ADA-120x") == [12, 7]
    assert ramo_suggerito(c) == f"ada-{c.pk}-export-excel-degli-ordini"


def test_firma_obbligatoria_e_ping(client, scena):
    repo = scena["repo"]
    assert _invia(client, repo, "ping", {}, segreto="sbagliato").status_code == 403
    assert _invia(client, repo, "ping", {"zen": "x"}).json()["pong"]


def test_push_collega_i_commit_una_volta(client, scena):
    c, altrui = scena["compito"], scena["altrui"]
    dati = {"ref": "refs/heads/main", "commits": [
        {"id": "a1b2c3d4e5f6", "message": f"Export in Excel ADA-{c.pk}\n\ndettagli", "url": "https://github.com/x/c/1",
         "author": {"username": "sara"}},
        {"id": "ffff0000", "message": f"Tocca ADA-{altrui.pk}", "url": "https://github.com/x/c/2",
         "author": {"name": "Luca"}}]}
    assert _invia(client, scena["repo"], "push", dati).json()["esito"] == "1 commit collegati"
    _invia(client, scena["repo"], "push", dati)                                     # ripetuto: niente doppioni
    link = Collegamento.objects.get()
    assert link.compito == c and link.etichetta == "a1b2c3d" and link.titolo == f"Export in Excel ADA-{c.pk}"
    assert Messaggio.objects.filter(object_id=c.pk, corpo__startswith="Commit a1b2c3d di sara").count() == 1


def _pr(compito, azione, merged=False, stato="open"):
    return {"action": azione, "pull_request": {
        "number": 42, "title": "Export Excel", "body": "", "state": stato, "merged": merged,
        "html_url": "https://github.com/x/pull/42", "user": {"login": "sara"},
        "head": {"ref": f"ada-{compito.pk}-export"}}}


def test_pull_request_unita_chiude_il_compito(client, scena):
    c, repo = scena["compito"], scena["repo"]
    _invia(client, repo, "pull_request", _pr(c, "opened"))
    link = Collegamento.objects.get(tipo="pr")
    assert link.stato == "aperta" and not Compito.objects.get(pk=c.pk).fase.chiusa
    _invia(client, repo, "pull_request", _pr(c, "closed", merged=True, stato="closed"))
    link.refresh_from_db()
    c.refresh_from_db()
    assert link.stato == "unita" and c.fase.chiusa and c.completato_il


def test_merge_non_chiude_se_bloccato_o_disattivato(client, scena):
    c, repo = scena["compito"], scena["repo"]
    prima = Compito.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], titolo="API")
    c.bloccato_da.add(prima)
    _invia(client, repo, "pull_request", _pr(c, "closed", merged=True, stato="closed"))
    assert not Compito.objects.get(pk=c.pk).fase.chiusa
    assert Messaggio.objects.filter(object_id=c.pk, corpo__contains="lo bloccano").exists()
    c.bloccato_da.clear()
    repo.chiudi_al_merge = False
    repo.save()
    _invia(client, repo, "pull_request", _pr(c, "closed", merged=True, stato="closed"))
    assert not Compito.objects.get(pk=c.pk).fase.chiusa


def test_release_pubblica_il_rilascio(client, scena):
    r = Rilascio.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], versione="2.4.0")
    esito = _invia(client, scena["repo"], "release", {"action": "published", "release": {"tag_name": "v2.4.0"}})
    r.refresh_from_db()
    assert esito.json()["esito"] == "rilascio 2.4.0 pubblicato" and r.stato == Rilascio.RILASCIATO


def test_crea_issue_e_stato(client, scena, monkeypatch, settings):
    settings.LAVORI_SINCRONI = True
    c, repo = scena["compito"], scena["repo"]
    repo.token = "ghp_segreto"
    repo.save()
    assert "ghp_segreto" not in Repository.objects.get(pk=repo.pk).token_cifrato           # cifrato
    chiamate = []

    class Risposta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def finto(richiesta, timeout):
        chiamate.append((richiesta.full_url, richiesta.get_header("Authorization"), json.loads(richiesta.data)))
        return Risposta(json.dumps({"number": 7, "title": "x", "html_url": "https://github.com/i/7"}).encode())
    monkeypatch.setattr(api.urllib.request, "urlopen", finto)
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    html = client.get(f"/progetti/compiti/{c.pk}/").content.decode()
    assert f"ADA-{c.pk}" in html and "Crea issue su ichnobyte/gestionale" in html
    client.post(f"/github/compito/{c.pk}/issue/", {"repository": repo.pk})
    client.post(f"/github/compito/{c.pk}/issue/", {"repository": repo.pk})
    assert len(chiamate) == 1                                                            # una sola issue
    url, auth, corpo = chiamate[0]
    assert url.endswith("/repos/ichnobyte/gestionale/issues") and auth == "Bearer ghp_segreto"
    assert corpo["title"] == f"[ADA-{c.pk}] Export Excel degli ordini"
    _invia(client, repo, "issues", {"action": "closed", "issue": {"number": 7, "state": "closed"}})
    assert Collegamento.objects.get(tipo="issue").stato == "chiusa"


def test_scheda_e_form_del_repository(client, scena):
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    repo = scena["repo"]
    html = client.get(f"/github/repository/{repo.pk}/").content.decode()
    assert repo.segreto in html and f"/github/webhook/{repo.pk}/" in html
    r = client.post(f"/github/repository/{repo.pk}/modifica/", {"nome": "nome sbagliato", "progetto": repo.progetto_id})
    assert "proprietario/nome" in r.content.decode()
    client.post(f"/github/repository/{repo.pk}/modifica/", {"nome": repo.nome, "progetto": repo.progetto_id,
                                                            "attivo": "on", "token": "ghp_nuovo"})
    assert Repository.objects.get(pk=repo.pk).token == "ghp_nuovo"
    client.post(f"/github/repository/{repo.pk}/modifica/", {"nome": repo.nome, "progetto": repo.progetto_id,
                                                            "attivo": "on"})
    assert Repository.objects.get(pk=repo.pk).token == "ghp_nuovo"                       # vuoto: resta
