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
from rivendita.models import Istanza, ModuloVendibile, Pacchetto, Piano, Richiesta, Suite


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


@pytest.mark.django_db
def test_suite_dal_catalogo_alla_licenza(client, superuser, scena):
    istanza, token = scena
    suite = Suite.objects.create(nome="Vendite", slug="vendite", utenti=3, descrizione="Per chi vende")
    suite.moduli.add(ModuloVendibile.objects.get(slug="premium"))
    Suite.objects.create(nome="Nascosta", slug="nascosta", in_catalogo=False)
    dati = _post(client, token).json()
    testo, catalogo = sincronia._verifica(dati)
    stato = licenza.leggi(testo)
    assert stato.suite == () and "suite" not in dati["licenza"]                       # senza suite la licenza resta com'era
    assert [(s["slug"], s["comprata"], [m["slug"] for m in s["moduli"]]) for s in catalogo["suite"]] == [("vendite", False, ["premium"])]
    r = _post(client, token, {"richieste": [{"id": 9, "slug": "vendite", "tipo": "suite", "nota": "per 3", "utente": "mario"},
                                            {"id": 10, "slug": "nascosta", "tipo": "suite"}]})
    assert r.json()["ricevute"] == [9, 10]
    richiesta = Richiesta.objects.get()
    assert richiesta.tipo == "suite" and richiesta.nome == "Vendite" and richiesta.nota == "per 3"
    client.post(reverse("rivendita:richieste_bottone", args=[richiesta.pk, "approva"]))
    assert list(istanza.suite.all()) == [suite]
    testo, catalogo = sincronia._verifica(_post(client, token).json())
    stato = licenza.leggi(testo)
    assert "premium" in stato.moduli and stato.comuni == {"extra"}
    assert [(s["slug"], s["nome"], s["moduli"], s["utenti"]) for s in stato.suite] == [("vendite", "Vendite", frozenset({"premium"}), 3)]
    assert catalogo["suite"][0]["comprata"]
    seconda = Richiesta.objects.create(istanza=istanza, slug="marketing", nome="Marketing", tipo=Richiesta.SUITE)
    client.post(reverse("rivendita:richieste_bottone", args=[seconda.pk, "rifiuta"]))
    risposta = _post(client, token).json()
    assert risposta["suite_rifiutate"] == ["marketing"] and risposta["rifiutate"] == []
    assert client.get(reverse("rivendita:suite_lista")).status_code == 200


@pytest.mark.django_db
def test_funzioni_dal_manifest_al_piano_e_alla_licenza(client, scena, portale, tmp_path):
    istanza, token = scena
    funzioni = [{"chiave": "web", "label": "Ricerca sul web"}, {"chiave": "memoria", "label": "Memoria", "help": "ricorda"},
                {"chiave": "voce", "label": "Voce"}]
    _pubblica(tmp_path, portale, "extra", version="1.1.0", depends=["base"], funzioni=funzioni)
    extra = ModuloVendibile.objects.get(slug="extra")
    assert list(extra.funzioni_attivabili.values_list("chiave", "nome", "spiegazione")) == [
        ("web", "Ricerca sul web", ""), ("memoria", "Memoria", "ricorda"), ("voce", "Voce", "")]

    def funzioni_in_licenza():
        testo, _ = sincronia._verifica(_post(client, token).json())
        return licenza.leggi(testo).funzioni

    assert funzioni_in_licenza() == {}                       # piano senza restrizioni: la chiave non c'è, tutte le funzioni
    istanza.piano.moduli_a_funzioni.add(extra)
    assert funzioni_in_licenza() == {"extra": frozenset()}   # a funzioni scelte, nessuna scelta: solo la base
    istanza.piano.funzioni.add(extra.funzioni_attivabili.get(chiave="memoria"))
    istanza.funzioni_extra.add(extra.funzioni_attivabili.get(chiave="web"))
    assert funzioni_in_licenza() == {"extra": frozenset({"memoria", "web"})}
    # tolta dal manifest, la funzione sparisce anche dal piano
    _pubblica(tmp_path, portale, "extra", version="1.2.0", depends=["base"], funzioni=funzioni[1:])
    assert funzioni_in_licenza() == {"extra": frozenset({"memoria"})}


# ---------- le formule dell'assistente AI ----------

def _consumi(client, token, mesi):
    return client.post(reverse("rivendita:api_consumi_ai"), json.dumps({"mesi": mesi}), content_type="application/json",
                       headers={"Authorization": f"Bearer {token}"})


def _mese(giorni_fa=0):
    return f"{(timezone.localdate().replace(day=1) - datetime.timedelta(days=giorni_fa)).replace(day=1):%Y-%m}"


@pytest.mark.django_db
def test_i_termini_dell_assistente_vanno_in_licenza_solo_se_servono(client, scena):
    from decimal import Decimal

    from ai import licenza as licenza_ai
    istanza, token = scena

    def ai_in_licenza():
        dati = _post(client, token).json()
        sincronia._verifica(dati)                              # la firma copre anche i termini
        return dati["licenza"].get("ai")

    assert ai_in_licenza() is None                             # chiave del cliente: la licenza resta quella di sempre
    Piano.objects.filter(pk=istanza.piano_id).update(ai_formula="inclusa", ai_quota_utente=5, ai_quota_istanza=200, ai_ricarico=30)
    istanza.refresh_from_db()
    termini = ai_in_licenza()
    assert termini == {"formula": "inclusa", "quota_utente": "5.00", "quota_istanza": "200.00"}     # il ricarico resta sul portale
    assert licenza_ai.termini(termini) == {"formula": "inclusa", "quota_utente": Decimal("5.00"), "quota_istanza": Decimal("200.00")}
    # l'istanza può avere condizioni sue; a consumo la quota per utente non esiste
    Istanza.objects.filter(pk=istanza.pk).update(ai_formula="consumo", ai_quota_istanza=0)
    istanza.refresh_from_db()
    assert istanza.termini_ai() == {"formula": "consumo", "quota_utente": Decimal("5.00"), "quota_istanza": Decimal("0"), "ricarico": Decimal("30.00")}
    assert ai_in_licenza() == {"formula": "consumo", "quota_utente": "0", "quota_istanza": "0.00"}
    Istanza.objects.filter(pk=istanza.pk).update(ai_formula="propria")
    istanza.refresh_from_db()
    assert ai_in_licenza() is None


@pytest.mark.django_db
def test_canone_mensile_con_il_prezzo_per_utente(scena):
    istanza, _ = scena
    assert istanza.canone_mese() == 99                                         # il piano della scena: 99 € fissi, 10 utenti
    Piano.objects.filter(pk=istanza.piano_id).update(prezzo_utente_mese=12)
    suite = Suite.objects.create(nome="Vendite", slug="vendite", prezzo_mese=40)
    istanza.suite.add(suite)
    ModuloVendibile.objects.filter(slug="premium").update(prezzo_mese=15)
    istanza.moduli_extra.add(ModuloVendibile.objects.get(slug="premium"))
    istanza = Istanza.objects.get(pk=istanza.pk)
    assert istanza.posti() == 10 and istanza.canone_mese() == 99 + 12 * 10 + 40 + 15
    Istanza.objects.filter(pk=istanza.pk).update(utenti=4)
    assert Istanza.objects.get(pk=istanza.pk).canone_mese() == 99 + 12 * 4 + 40 + 15
    Istanza.objects.filter(pk=istanza.pk).update(utenti=0, utenti_attivi=7)     # senza tetto: gli utenti attivi riferiti
    assert Istanza.objects.get(pk=istanza.pk).posti() == 7


@pytest.mark.django_db
def test_consumi_dell_assistente_riferiti_dall_istanza(client, superuser, scena):
    from decimal import Decimal

    from core import parametri
    from rivendita.models import ConsumoAI
    istanza, token = scena
    voce = {"mese": _mese(), "costo": "12.500000", "costo_fornito": "10.000000", "turni": 80, "utenti": 4}
    assert _consumi(client, "sbagliato", [voce]).status_code == 401
    assert client.post(reverse("rivendita:api_consumi_ai"), "[]", content_type="application/json",
                       headers={"Authorization": f"Bearer {token}"}).status_code == 400
    # a consumo: costo sul piano × cambio × ricarico
    Piano.objects.filter(pk=istanza.piano_id).update(ai_formula="consumo", ai_ricarico=20, ai_quota_istanza=50)
    parametri.scrivi("rivendita.cambio_usd_eur", Decimal("0.90"))
    scorso = {"mese": _mese(1), "costo": "3", "costo_fornito": "3", "turni": 9, "utenti": 1}
    r = _consumi(client, token, [voce, scorso, {"mese": _mese(40), "costo": "9", "costo_fornito": "9", "turni": 1, "utenti": 1},
                                 {"mese": _mese(), "costo": "1", "costo_fornito": "2", "turni": 1, "utenti": 1},     # più sul piano che in tutto
                                 {"mese": "sempre", "costo": "1"}, "testo", {"mese": _mese(), "costo": "-1", "costo_fornito": "0", "turni": 1, "utenti": 1}])
    assert r.status_code == 200 and r.json() == {"registrati": [voce["mese"], scorso["mese"]]}     # i mesi chiusi non si riscrivono
    consumo = ConsumoAI.objects.get(mese__month=timezone.localdate().month)
    assert (consumo.costo, consumo.costo_fornito, consumo.turni, consumo.utenti) == (Decimal("12.5"), Decimal("10"), 80, 4)
    assert (consumo.formula, consumo.quota, consumo.importo) == ("consumo", Decimal("50"), Decimal("10.80"))
    assert ConsumoAI.objects.count() == 2
    # rimandare lo stesso mese sostituisce la riga
    _consumi(client, token, [{**voce, "costo_fornito": "11"}])
    consumo.refresh_from_db()
    assert ConsumoAI.objects.count() == 2 and consumo.importo == Decimal("11.88")
    # inclusa: niente da fatturare, ma si vede il consumo rispetto alla quota (qui 5 $ per i 10 utenti del piano)
    Piano.objects.filter(pk=istanza.piano_id).update(ai_formula="inclusa", ai_quota_utente=5, ai_quota_istanza=0)
    _consumi(client, token, [voce])
    consumo.refresh_from_db()
    assert (consumo.formula, consumo.quota, consumo.importo) == ("inclusa", Decimal("50"), 0)
    pagina = client.get(reverse("rivendita:consumi_ai_lista")).content.decode()
    assert "Rossi Srl" in pagina and "20%" in pagina
    assert client.get(reverse("rivendita:consumi_ai_nuovo")).status_code == 403
    assert client.post(reverse("rivendita:consumi_ai_elimina", args=[consumo.pk])).status_code == 403


@pytest.mark.django_db
def test_dal_lavoro_dell_istanza_al_portale(client, scena, settings, monkeypatch):
    """ai.consumi_portale manda esattamente ciò che l'endpoint accetta."""
    from decimal import Decimal

    from django.contrib.auth.models import User

    from ai import consumi_portale
    from ai.models import Turno
    from rivendita.models import ConsumoAI
    istanza, token = scena
    Turno.objects.create(utente=User.objects.create_user("anna"), costo=Decimal("1.25"), costo_fornito=Decimal("1"))
    settings.LICENZA_PORTALE_URL, settings.LICENZA_TOKEN = "https://portale.example/rivendita/api", token
    monkeypatch.setattr(consumi_portale, "_chiama", lambda dati: _consumi(client, settings.LICENZA_TOKEN, dati["mesi"]))
    assert consumi_portale.invia().startswith("inviati")
    consumo = ConsumoAI.objects.get(mese=timezone.localdate().replace(day=1))
    assert (consumo.istanza, consumo.costo, consumo.costo_fornito, consumo.turni, consumo.utenti) == (istanza, Decimal("1.25"), Decimal("1"), 1, 1)


@pytest.mark.django_db
def test_dashboard_con_canoni_e_assistente(rf, superuser, scena):
    from decimal import Decimal

    from rivendita import dashboard
    from rivendita.models import ConsumoAI
    istanza, _ = scena
    istanza.suite.add(Suite.objects.create(nome="Vendite", slug="vendite", prezzo_mese=40))
    ConsumoAI.objects.create(istanza=istanza, mese=timezone.localdate().replace(day=1), importo=Decimal("10.80"))
    richiesta = rf.get("/")
    richiesta.user, richiesta.azienda = superuser, None
    kpi = {k["etichetta"]: k["valore"] for k in dashboard.dati(richiesta)["kpi"]}
    assert kpi["canoni al mese"].startswith("139") and kpi["assistente a consumo, mese in corso"].startswith("10,8")
