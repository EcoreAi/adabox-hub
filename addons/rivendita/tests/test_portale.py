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


@pytest.mark.django_db
def test_richiesta_di_demo_non_entra_in_licenza_e_il_link_generale(client, superuser, scena, settings):
    istanza, token = scena
    settings.RIVENDITA_URL_DEMO = "https://demo.example/"
    dati = _post(client, token, {"richieste": [{"id": 1, "slug": "premium", "nome": "Premium", "tipo": "demo"}]}).json()
    testo, catalogo = sincronia._verifica(dati)
    assert "premium" not in licenza.leggi(testo).moduli and catalogo["disponibili"][0]["url_demo"] == "https://demo.example/"
    ModuloVendibile.objects.filter(slug="premium").update(url_demo="https://demo.example/premium")
    assert sincronia._verifica(_post(client, token).json())[1]["disponibili"][0]["url_demo"] == "https://demo.example/premium"
    richiesta = Richiesta.objects.get()
    assert richiesta.tipo == "demo"
    assert b"Approva" not in client.get(reverse("rivendita:richieste_dettaglio", args=[richiesta.pk])).content
    client.post(reverse("rivendita:richieste_bottone", args=[richiesta.pk, "gestita"]))
    richiesta.refresh_from_db()
    assert richiesta.stato == "approvata" and not istanza.moduli_extra.exists()


def _su_misura(tmp_path, portale, slug="bolle_rossi", **manifest):
    return _pubblica(tmp_path, portale, slug, su_misura=True, **manifest).modulo


@pytest.mark.django_db
def test_modulo_su_misura_solo_per_il_suo_cliente(client, scena, portale, tmp_path):
    rossi, token_rossi = scena
    bianchi = Istanza.objects.create(cliente="Bianchi Srl", piano=rossi.piano, scadenza=rossi.scadenza)
    token_bianchi = bianchi.nuovo_token()
    modulo = _su_misura(tmp_path, portale)
    assert modulo.su_misura and not modulo.in_catalogo
    rossi.moduli_extra.add(modulo)
    dati_rossi, dati_bianchi = _post(client, token_rossi).json(), _post(client, token_bianchi).json()
    assert "bolle_rossi" in [v["slug"] for v in dati_rossi["catalogo"]["moduli"]]
    testo = json.dumps(dati_bianchi)
    assert "bolle_rossi" not in testo                        # né nella licenza, né nel catalogo, né descritto
    url = reverse("rivendita:api_pacchetto", args=["bolle_rossi", "1.0.0"])
    assert client.get(url, headers={"Authorization": f"Bearer {token_rossi}"}).status_code == 200
    assert client.get(url, headers={"Authorization": f"Bearer {token_bianchi}"}).status_code == 403


@pytest.mark.django_db
def test_modulo_su_misura_non_passa_da_un_piano_o_da_una_richiesta(client, scena, portale, tmp_path):
    rossi, token = scena
    modulo = _su_misura(tmp_path, portale)
    rossi.piano.moduli.add(modulo)                           # anche se finisse in un piano per errore
    assert "bolle_rossi" not in servizi.moduli_di(rossi)
    _post(client, token, {"richieste": [{"id": 1, "slug": "bolle_rossi", "nome": "Bolle", "tipo": "installazione"}]})
    assert not Richiesta.objects.filter(slug="bolle_rossi").exists()
    from django.forms import modelform_factory
    assert modulo not in modelform_factory(Piano, fields=["moduli"])().fields["moduli"].queryset     # nel form non si sceglie


@pytest.mark.django_db
def test_ripubblicare_non_rende_pubblico_e_il_portale_decide(scena, portale, tmp_path):
    modulo = _su_misura(tmp_path, portale)
    _pubblica(tmp_path, portale, "bolle_rossi", version="1.1.0")   # anche senza la chiave nel manifest
    modulo.refresh_from_db()
    assert modulo.su_misura and not modulo.in_catalogo and modulo.ultimo().versione == "1.1.0"


@pytest.mark.django_db
def test_i_moduli_normali_restano_nel_catalogo(client, scena):
    rossi, token = scena
    assert "premium" in [v["slug"] for v in _post(client, token).json()["catalogo"]["disponibili"]]


@pytest.mark.django_db
def test_comando_pubblica_per_un_cliente(portale, addons_tmp, scena):
    from django.core.management import CommandError, call_command
    rossi, _ = scena
    addons_tmp.crea("su_rossi", su_misura=True)
    with pytest.raises(CommandError, match="0 istanze"):
        call_command("rivendita_pubblica", "su_rossi", "--per", "Nessuno")
    assert not ModuloVendibile.objects.filter(slug="su_rossi").exists()
    call_command("rivendita_pubblica", "su_rossi", "--per", "Rossi Srl")
    modulo = ModuloVendibile.objects.get(slug="su_rossi")
    assert modulo.su_misura and modulo in rossi.moduli_extra.all() and "su_rossi" in servizi.moduli_di(rossi)
