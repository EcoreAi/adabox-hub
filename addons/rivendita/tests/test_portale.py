import datetime
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core import licenza
from core.registry import pacchetti, sincronia
from core.tests.conftest_aiuti import crea_modulo
from rivendita import servizi
from rivendita.models import Istanza, ModuloVendibile, Pacchetto, Piano, Richiesta


@pytest.fixture
def portale(settings, tmp_path):
    privata = Ed25519PrivateKey.generate()
    percorso = tmp_path / "chiave.pem"
    percorso.write_bytes(privata.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    settings.MODULI_CHIAVE_PRIVATA, settings.MODULI_CHIAVI_FIDATE = str(percorso), [pacchetti.pubblica_b64(privata)]
    settings.MODULI_FIRMA_OBBLIGATORIA, settings.PRIVATE_MEDIA_ROOT = True, tmp_path / "private"
    return privata


def _pubblica(tmp_path, privata, slug, **manifest):
    cartella = crea_modulo(tmp_path / f"src-{slug}-{manifest.get('version', '1.0.0')}", slug, application=True, summary=f"Modulo {slug}", category="Vendite", **manifest)
    return servizi.pubblica(pacchetti.impacchetta(cartella, tmp_path / "dist", privata))


@pytest.fixture
def scena(portale, tmp_path):
    _pubblica(tmp_path, portale, "base")
    _pubblica(tmp_path, portale, "base", version="1.1.0")
    _pubblica(tmp_path, portale, "extra", depends=["base"])
    _pubblica(tmp_path, portale, "premium")
    piano = Piano.objects.create(nome="Base", utenti=10, prezzo_mese=99)
    piano.moduli.add(ModuloVendibile.objects.get(slug="extra"))
    istanza = Istanza.objects.create(cliente="Rossi Srl", piano=piano, scadenza=timezone.localdate() + datetime.timedelta(days=365))
    return istanza, istanza.nuovo_token()


def _post(client, token, dati=None):
    return client.post(reverse("rivendita:api_sincronizza"), json.dumps(dati or {}), content_type="application/json", headers={"Authorization": f"Bearer {token}"})


@pytest.mark.django_db
def test_licenza_e_catalogo_firmati_solo_per_il_token_giusto(client, scena):
    istanza, token = scena
    assert _post(client, "sbagliato").status_code == 401
    assert client.post(reverse("rivendita:api_sincronizza"), "{}", content_type="application/json").status_code == 401
    r = _post(client, token, {"moduli": {"base": "1.0.0"}, "utenti_attivi": 3})
    dati = r.json()
    # è esattamente ciò che l'istanza accetta: firme buone, dipendenze comprese
    testo, catalogo = sincronia._verifica(dati)
    stato = licenza.leggi(testo)
    assert stato.moduli == {"base", "extra"} and stato.cliente == "Rossi Srl" and stato.utenti == 10 and stato.istanza == str(istanza.codice)
    assert {v["slug"]: v["versione"] for v in catalogo["moduli"]} == {"base": "1.1.0", "extra": "1.0.0"}
    assert [v["slug"] for v in catalogo["disponibili"]] == ["premium"]
    assert "url" not in catalogo["disponibili"][0] and "sha256" not in catalogo["disponibili"][0]    # del non comprato, solo la descrizione
    istanza.refresh_from_db()
    assert istanza.ultimo_contatto and istanza.moduli_presenti == {"base": "1.0.0"} and istanza.utenti_attivi == 3
    Istanza.objects.filter(pk=istanza.pk).update(attiva=False)
    assert _post(client, token).status_code == 401


@pytest.mark.django_db
def test_il_pacchetto_si_scarica_solo_se_in_licenza(client, scena, settings):
    istanza, token = scena
    base = reverse("rivendita:api_pacchetto", args=["base", "1.1.0"])
    assert client.get(base).status_code == 401
    r = client.get(base, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r["Content-Type"] == "application/zip" and b"".join(r.streaming_content)[:2] == b"PK"
    premium = reverse("rivendita:api_pacchetto", args=["premium", "1.0.0"])
    assert client.get(premium, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    Istanza.objects.filter(pk=istanza.pk).update(scadenza=timezone.localdate() - datetime.timedelta(days=60))
    assert client.get(base, headers={"Authorization": f"Bearer {token}"}).status_code == 403


@pytest.mark.django_db
def test_i_pacchetti_non_stanno_nei_media_pubblici(scena, settings):
    p = Pacchetto.objects.first()
    assert not str(p.file.path).startswith(str(settings.MEDIA_ROOT)) and str(p.file.path).startswith(str(settings.PRIVATE_MEDIA_ROOT))


@pytest.mark.django_db
def test_richiesta_arriva_si_approva_e_compare_in_licenza(client, superuser, scena):
    istanza, token = scena
    r = _post(client, token, {"richieste": [{"id": 7, "slug": "premium", "nome": "Premium", "nota": "ci serve", "utente": "mario"}]})
    assert r.json()["ricevute"] == [7]
    _post(client, token, {"richieste": [{"id": 7, "slug": "premium", "nome": "Premium"}]})
    richiesta = Richiesta.objects.get()
    assert richiesta.nota == "ci serve" and richiesta.stato == "nuova"
    r = client.post(reverse("rivendita:richieste_bottone", args=[richiesta.pk, "approva"]))
    richiesta.refresh_from_db()
    assert r.status_code == 302 and richiesta.stato == "approvata" and richiesta.decisa_da == superuser
    stato = licenza.leggi(sincronia._verifica(_post(client, token).json())[0])
    assert "premium" in stato.moduli
    seconda = Richiesta.objects.create(istanza=istanza, slug="altro", nome="Altro")
    client.post(reverse("rivendita:richieste_bottone", args=[seconda.pk, "rifiuta"]))
    assert _post(client, token).json()["rifiutate"] == ["altro"]


@pytest.mark.django_db
def test_token_visibile_una_volta_e_carica_pacchetto(client, superuser, portale, tmp_path):
    piano = Piano.objects.create(nome="P")
    istanza = Istanza.objects.create(cliente="C", piano=piano, scadenza=timezone.localdate())
    r = client.post(reverse("rivendita:istanze_bottone", args=[istanza.pk, "genera_token"]), follow=True)
    testo = r.content.decode()
    istanza.refresh_from_db()
    assert "Token di C:" in testo and istanza.token_hash and istanza.token_hash not in testo
    assert client.get(reverse("rivendita:carica")).status_code == 200
    firmato = pacchetti.impacchetta(crea_modulo(tmp_path / "a", "alfa", application=True), tmp_path / "d", portale)
    client.post(reverse("rivendita:carica"), {"pacchetto": SimpleUploadedFile(firmato.name, firmato.read_bytes())})
    assert Pacchetto.objects.filter(modulo__slug="alfa").exists()
    nudo = pacchetti.impacchetta(crea_modulo(tmp_path / "b", "beta"), tmp_path / "e")
    r = client.post(reverse("rivendita:carica"), {"pacchetto": SimpleUploadedFile(nudo.name, nudo.read_bytes())}, follow=True)
    assert not Pacchetto.objects.filter(modulo__slug="beta").exists() and "rifiutato" in r.content.decode()
    assert client.get(reverse("rivendita:istanze_lista")).status_code == 200 and client.get(reverse("core:dashboard")).status_code == 200


@pytest.mark.django_db
def test_comando_pubblica(portale, addons_tmp):
    crea_modulo(addons_tmp.dir, "gamma", application=True)
    crea_modulo(addons_tmp.dir, "rivendita")
    call_command("rivendita_pubblica", "--tutti")
    assert list(ModuloVendibile.objects.values_list("slug", flat=True)) == ["gamma"]
