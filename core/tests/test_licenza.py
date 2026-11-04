import datetime
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from core import applicazioni, licenza
from core.models import LicenzaIstanza, RichiestaModulo
from core.registry import install, modules, pacchetti, sincronia
from core.tests.conftest_aiuti import crea_modulo
from core.utenti import UtenteForm


@pytest.fixture
def chiave(settings):
    privata = Ed25519PrivateKey.generate()
    settings.MODULI_CHIAVI_FIDATE = [pacchetti.pubblica_b64(privata)]
    return privata


def _file(chiave, moduli=("todo",), giorni=100, grazia=30, emessa="2026-11-04T10:00:00", **altro):
    scadenza = timezone.localdate() + datetime.timedelta(days=giorni)
    return json.dumps(licenza.firma({"cliente": "Rossi Srl", "istanza": "abc", "piano": "Base", "moduli": list(moduli), "utenti": 0,
                                     "scadenza": scadenza.isoformat(), "grazia_giorni": grazia, "emessa": emessa, **altro}, chiave))


@pytest.mark.django_db
def test_senza_obbligo_non_cambia_niente(superuser, client, django_assert_num_queries):
    assert licenza.fuori_licenza() == frozenset() and licenza.ammesso("qualunque") and not licenza.bloccata() and licenza.avviso() == ""
    with django_assert_num_queries(0):
        licenza.fuori_licenza()
    assert client.get(reverse("todo:attivita_lista")).status_code == 200


@pytest.mark.django_db
def test_firma_altri_prodotti_e_licenze_vecchie_si_rifiutano(chiave):
    with pytest.raises(ValueError, match="Firma non valida"):
        licenza.salva(_file(Ed25519PrivateKey.generate()))
    manomessa = json.loads(_file(chiave))
    manomessa["licenza"]["moduli"].append("crm")
    with pytest.raises(ValueError, match="Firma non valida"):
        licenza.salva(json.dumps(manomessa))
    with pytest.raises(ValueError, match="non è una licenza"):
        licenza.salva("boh")
    assert licenza.salva(_file(chiave)).cliente == "Rossi Srl"
    with pytest.raises(ValueError, match="più vecchia"):
        licenza.salva(_file(chiave, emessa="2026-01-01T10:00:00"))
    assert licenza.attuale().moduli == {"todo"}


@pytest.mark.django_db
def test_moduli_fuori_licenza_spenti_e_non_installabili(superuser, client, chiave, settings, monkeypatch):
    settings.LICENZA_OBBLIGATORIA = True
    assert "todo" in modules.disattivati() and licenza.bloccata()           # senza licenza tutto spento
    assert client.get(reverse("todo:attivita_lista")).status_code == 404
    licenza.salva(_file(chiave, moduli=["todo"]))
    spenti = modules.disattivati()
    assert "todo" not in spenti and "crm" in spenti and not licenza.bloccata()
    assert client.get(reverse("todo:attivita_lista")).status_code == 200
    assert client.get(reverse("crm:opportunita_lista")).status_code == 404
    assert b"crm:" not in client.get(reverse("core:launcher")).content
    monkeypatch.setattr(modules, "installati", lambda: ["todo"])
    monkeypatch.setattr(install, "_applica", lambda *a, **k: pytest.fail("non doveva installare"))
    with pytest.raises(install.NonLicenziato, match="crm"):
        install.installa(["crm"])


@pytest.mark.django_db
def test_grazia_poi_sola_lettura(superuser, client, chiave, settings):
    settings.LICENZA_OBBLIGATORIA = True
    licenza.salva(_file(chiave, giorni=-5, grazia=30))
    assert licenza.attuale().in_grazia and not licenza.bloccata() and "è scaduta" in licenza.avviso()
    assert "mk-avviso" in client.get(reverse("core:dashboard")).content.decode()
    r = client.post(reverse("todo:attivita_nuovo"), {"titolo": "x"})
    assert r.status_code != 403
    LicenzaIstanza.objects.all().delete()
    licenza.salva(_file(chiave, giorni=-40, grazia=30))
    assert licenza.bloccata()
    assert client.get(reverse("todo:attivita_lista")).status_code == 200    # si legge
    r = client.post(reverse("todo:attivita_nuovo"), {"titolo": "x"})
    assert r.status_code == 403 and "sola lettura" in r.content.decode()    # non si scrive
    assert client.post(reverse("core:moduli_sincronizza")).status_code == 302   # da qui si rimette a posto


@pytest.mark.django_db
def test_tetto_degli_utenti(chiave, settings):
    settings.LICENZA_OBBLIGATORIA = True
    User.objects.create_user("uno")
    licenza.salva(_file(chiave, utenti=1))
    form = UtenteForm({"username": "due", "email": "d@example.com", "is_active": True})
    assert not form.is_valid() and "is_active" in form.errors
    assert UtenteForm({"username": "tre", "email": "t@example.com", "is_active": False}).is_valid()


@pytest.mark.django_db
def test_catalogo_delle_applicazioni_e_richiesta(client, superuser, chiave, settings, mailoutbox):
    settings.LICENZA_OBBLIGATORIA = True
    settings.LICENZA_EMAIL_RICHIESTE = "vendite@example.com"
    licenza.salva(_file(chiave, moduli=["todo"]), catalogo={"istanza": "abc", "moduli": [], "disponibili": [
        {"slug": "magia", "nome": "Magia", "riassunto": "Fa magie", "categoria": "Vendite", "icona": "data:image/svg+xml;base64,AAA"},
        {"slug": "cattiva", "nome": "Cattiva", "icona": "javascript:alert(1)"}]})
    html = client.get(reverse("core:applicazioni")).content.decode()
    assert "Magia" in html and "Fa magie" in html and "Richiedi" in html and "To-Do" in html and "javascript:" not in html
    assert "crm" not in [v["slug"] for v in applicazioni.voci()]           # su disco ma non in licenza né a catalogo
    r = client.post(reverse("core:applicazioni_richiedi"), {"slug": "magia", "nota": "ci serve"})
    assert r.status_code == 302 and RichiestaModulo.objects.get().nota == "ci serve" and mailoutbox[0].to == ["vendite@example.com"]
    assert next(v for v in applicazioni.voci() if v["slug"] == "magia")["stato"] == "richiesta"
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "magia"}).status_code == 404    # una volta sola
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "crm"}).status_code == 404      # non a catalogo
    client.force_login(User.objects.create_user("semplice"))
    assert client.get(reverse("core:applicazioni")).status_code == 403


@pytest.mark.django_db
def test_sincronia_scarica_installa_revoca_e_toglie_il_codice(chiave, settings, addons_tmp, tmp_path, monkeypatch):
    settings.LICENZA_OBBLIGATORIA, settings.LICENZA_PORTALE_URL, settings.LICENZA_TOKEN = True, "https://portale.example/api", "segreto"
    settings.BACKUP_DIR = tmp_path / "backup"
    zip_nuovo = pacchetti.impacchetta(crea_modulo(tmp_path / "src", "nuovo", version="1.2.0"), tmp_path / "dist", chiave)
    crea_modulo(addons_tmp.dir, "revocato")
    crea_modulo(addons_tmp.dir, "estraneo")
    stato_installati = ["revocato"]
    monkeypatch.setattr(modules, "installati", lambda: list(stato_installati))
    fatti = []

    def installa(slugs, riavvia=False):
        fatti.append(("installa", slugs))
        stato_installati.extend(slugs)
        return slugs

    def disinstalla(slug, riavvia=False):
        fatti.append(("disinstalla", slug))
        stato_installati.remove(slug)
    monkeypatch.setattr(install, "installa", installa)
    monkeypatch.setattr(install, "disinstalla", disinstalla)
    monkeypatch.setattr(install, "aggiorna", lambda **k: (_ for _ in ()).throw(install.NienteDaAggiornare()))
    monkeypatch.setattr(install, "ricarica", lambda: fatti.append(("ricarica", None)))
    richiesta = RichiestaModulo.objects.create(slug="nuovo", nome="Nuovo")
    catalogo = {"istanza": "abc", "moduli": [{"slug": "nuovo", "versione": "1.2.0", "min_core": "1.0", "file": zip_nuovo.name, "url": "https://portale.example/z",
                                              "sha256": pacchetti._sha256(zip_nuovo)}], "disponibili": []}

    def chiama(percorso, dati=None, limite=0):
        if percorso == "sincronizza/":
            assert [r["slug"] for r in dati["richieste"]] == ["nuovo"] and dati["moduli"] == {} or dati["moduli"]
            return json.dumps({**json.loads(_file(chiave, moduli=["nuovo"])), "catalogo": catalogo, "ricevute": [richiesta.pk],
                               "firma_catalogo": pacchetti.firma(pacchetti.serializza(catalogo), chiave).decode()}).encode()
        return zip_nuovo.read_bytes()
    monkeypatch.setattr(sincronia, "_chiama", chiama)
    esito = sincronia.esegui()
    assert esito["errori"] == [] and fatti == [("disinstalla", "revocato"), ("installa", ["nuovo"]), ("ricarica", None)]
    assert (addons_tmp.dir / "nuovo").exists() and not (addons_tmp.dir / "revocato").exists() and not (addons_tmp.dir / "estraneo").exists()
    assert not list((tmp_path / "backup").glob("moduli/revocato*"))         # nessuna copia del codice revocato
    richiesta.refresh_from_db()
    riga = LicenzaIstanza.objects.get()
    assert richiesta.stato == RichiestaModulo.EVASA and richiesta.consegnata and riga.ultima_sincronia and riga.catalogo["istanza"] == "abc"
    # catalogo di un'altra istanza, firma sbagliata o hash alterato: non si applica niente
    fatti.clear()
    altro = {**catalogo, "istanza": "zzz"}
    monkeypatch.setattr(sincronia, "_chiama", lambda *a, **k: json.dumps({**json.loads(_file(chiave, moduli=[], emessa="2026-12-01T00:00:00")), "catalogo": altro,
                                                                           "firma_catalogo": pacchetti.firma(pacchetti.serializza(altro), chiave).decode()}).encode())
    assert "altra istanza" in sincronia.esegui()["errori"][0] and fatti == [] and licenza.attuale().moduli == {"nuovo"}
    monkeypatch.setattr(sincronia, "_chiama", lambda *a, **k: (_ for _ in ()).throw(sincronia.PortaleNonValido("giù")))
    assert sincronia.esegui()["errori"] == ["giù"] and LicenzaIstanza.objects.get().ultimo_errore == "giù" and fatti == []
    # scaduta: la licenza si aggiorna ma non si toglie niente
    monkeypatch.setattr(sincronia, "_chiama", lambda *a, **k: json.dumps({**json.loads(_file(chiave, moduli=[], giorni=-1, emessa="2026-12-02T00:00:00")), "catalogo": catalogo,
                                                                           "firma_catalogo": pacchetti.firma(pacchetti.serializza(catalogo), chiave).decode()}).encode())
    assert sincronia.esegui() == {"fatti": [], "errori": []} and fatti == []
