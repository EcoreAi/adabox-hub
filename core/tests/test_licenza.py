import datetime
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from core import applicazioni, due_fattori, licenza
from core.models import LicenzaIstanza, Modulo, RichiestaModulo, Ruolo
from core.signals import crea_profilo
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
def test_catalogo_a_tre_sezioni_demo_e_installazione(client, superuser, chiave, settings, mailoutbox):
    settings.LICENZA_OBBLIGATORIA = True
    settings.LICENZA_EMAIL_RICHIESTE = "vendite@example.com"
    licenza.salva(_file(chiave, moduli=["todo", "crm", "contatti"]), catalogo={"istanza": "abc", "moduli": [], "disponibili": [
        {"slug": "magia", "nome": "Magia", "riassunto": "Fa magie", "categoria": "Vendite", "icona": "data:image/svg+xml;base64,AAA", "descrizione": "Fa magie vere",
         "funzioni": ["Conigli"], "url_demo": "https://demo.example/magia"},
        {"slug": "cattiva", "nome": "Cattiva", "icona": "javascript:alert(1)", "url_demo": "javascript:alert(1)"}]})
    modules.sincronizza()
    Modulo.objects.filter(slug="crm").update(disattivato=True)
    r = client.get(reverse("core:applicazioni"))
    html = r.content.decode()
    assert [v["slug"] for v in r.context["ferme"]] == ["crm"] and "todo" in [v["slug"] for v in r.context["attive"]]
    assert {v["slug"] for v in r.context["altre"]} == {"magia", "cattiva"}           # helpdesk: su disco ma non in licenza né a catalogo
    assert "Installate ma non attive" in html and "Da acquistare" in html and "Fa magie vere" in html and "Conigli" in html
    assert "Guarda la demo" in html and "https://demo.example/magia" in html and "Richiedi una demo" in html and "Richiedi l&#x27;installazione" in html or "Richiedi l'installazione" in html
    assert "javascript:" not in html.replace("javascript:alert", "") and "alert(1)" not in html
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "magia", "tipo": "demo"}).status_code == 302
    assert RichiestaModulo.objects.get().tipo == "demo" and "demo" in mailoutbox[0].subject
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "magia", "tipo": "demo"}).status_code == 404    # una volta sola
    r = client.post(reverse("core:applicazioni_richiedi"), {"slug": "magia", "nota": "ci serve"})
    assert r.status_code == 302 and RichiestaModulo.objects.get(tipo="installazione").nota == "ci serve"
    voce = next(v for v in applicazioni.voci() if v["slug"] == "magia")
    assert voce["stato"] == "richiesta" and voce["demo_chiesta"]
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "helpdesk"}).status_code == 404
    client.force_login(User.objects.create_user("semplice"))
    assert client.get(reverse("core:applicazioni")).status_code == 403


@pytest.mark.django_db
def test_admin_dal_front_attiva_decide_chi_e_niente_admin_di_django(client, db, chiave, settings):
    settings.LICENZA_OBBLIGATORIA = True
    licenza.salva(_file(chiave, moduli=["todo", "crm", "contatti"]))
    modules.sincronizza()
    Modulo.objects.filter(slug__in=["crm", "contatti"]).update(disattivato=True)
    capo = User.objects.create_user("capo", password="x")
    profilo = crea_profilo(capo)
    profilo.ruolo = Ruolo.objects.get(nome="Admin")
    profilo.save()
    capo = User.objects.get(pk=capo.pk)
    assert not capo.is_staff and not capo.is_superuser and capo.has_perm("core.change_modulo") and capo.has_perm("auth.change_user")
    assert due_fattori.obbligatoria_per(capo) is (due_fattori.leggi_obbligo() in (due_fattori.TUTTI, due_fattori.AMMINISTRATORI))
    client.force_login(capo)
    assert client.get("/admin/").status_code == 302 and client.get(reverse("core:moduli")).status_code == 403
    html = client.get(reverse("core:dashboard")).content.decode()
    assert reverse("core:applicazioni") in html and reverse("admin:index") not in html and "Amministrazione" not in html and reverse("core:le_mie_app") in html
    assert html.index(reverse("core:applicazioni")) < html.index(reverse("core:utenti"))
    # attivare crm accende anche la sua dipendenza e porta alla scelta di chi lo usa
    r = client.post(reverse("core:applicazioni_attivazione"), {"slug": "crm", "attivo": "1"})
    assert r.url == reverse("core:applicazione", args=["crm"]) and not modules.Modulo.objects.get(slug="contatti").disattivato
    # contatti serve a crm: non si spegne finché crm è acceso
    assert client.post(reverse("core:applicazioni_attivazione"), {"slug": "contatti", "attivo": "0"}).status_code == 302
    assert not Modulo.objects.get(slug="contatti").disattivato
    # chi può usarla: per ruolo e per persona
    lettore = User.objects.create_user("lettore", password="x")
    p = crea_profilo(lettore)
    p.ruolo = Ruolo.objects.get(nome="Lettore")
    p.save()
    html = client.get(reverse("core:applicazione", args=["crm"])).content.decode()
    assert "Per ruolo" in html and "Per persona" in html and "Global Admin" in html and "lettore" in html
    r = Ruolo.objects.get(nome="Lettore")
    client.post(reverse("core:applicazione_ruolo", args=["crm"]), {"ruolo": r.pk, "livello": "nessuno"})
    assert Ruolo.objects.get(pk=r.pk).livelli["crm"] == "nessuno" and not User.objects.get(pk=lettore.pk).has_perm("crm.view_opportunita")
    client.post(reverse("core:applicazione_ruolo", args=["crm"]), {"ruolo": r.pk, "livello": "lettura"})
    assert User.objects.get(pk=lettore.pk).has_perm("crm.view_opportunita")
    tecnico = Ruolo.objects.get(tecnico=True)
    assert client.post(reverse("core:applicazione_ruolo", args=["crm"]), {"ruolo": tecnico.pk, "livello": "nessuno"}).status_code == 403
    assert client.get(reverse("core:applicazione", args=["helpdesk"])).status_code == 404       # non in licenza
    # disattiva: sparisce per tutti, i dati restano
    client.post(reverse("core:applicazioni_attivazione"), {"slug": "crm", "attivo": "0"})
    assert Modulo.objects.get(slug="crm").disattivato and client.get(reverse("crm:opportunita_lista")).status_code == 404
    client.force_login(User.objects.get(pk=lettore.pk))
    assert client.post(reverse("core:applicazioni_attivazione"), {"slug": "crm", "attivo": "1"}).status_code == 403


@pytest.mark.django_db
def test_le_voci_di_servizio_seguono_l_app_da_cui_dipendono(superuser, client):
    """Controllo AI e Da approvare (Agate) non restano nel menu se l'assistente è spento."""
    modules.sincronizza()
    assert "Controllo AI" in client.get(reverse("core:dashboard")).content.decode()
    modules.imposta_attivo("ai", False)
    assert Modulo.objects.get(slug="agate").disattivato and Modulo.objects.get(slug="awf").disattivato
    html = client.get(reverse("core:dashboard")).content.decode()
    assert "Controllo AI" not in html and "Da approvare" not in html and "Agenti AI" not in html
    modules.imposta_attivo("ai", True)
    assert not Modulo.objects.get(slug="agate").disattivato


@pytest.mark.django_db
def test_con_la_licenza_i_moduli_nuovi_arrivano_spenti_tranne_al_primo_avvio(chiave, settings, addons_tmp, tmp_path, monkeypatch):
    settings.LICENZA_OBBLIGATORIA, settings.BACKUP_DIR = True, tmp_path / "backup"
    licenza.salva(_file(chiave, moduli=["alfa", "beta", "gamma"]))
    crea_modulo(addons_tmp.dir, "alfa", application=True)
    crea_modulo(addons_tmp.dir, "beta", application=True)
    crea_modulo(addons_tmp.dir, "gamma")
    monkeypatch.setattr(install, "_applica", lambda *a, **k: modules.sincronizza())
    monkeypatch.setattr(install.backup, "esegui", lambda motivo: None)        # dentro la transazione del test si bloccherebbe
    install.installa(["alfa"])
    assert not Modulo.objects.get(slug="alfa").disattivato                           # primo avvio: il piano è già pronto
    install.installa(["beta", "gamma"])
    assert Modulo.objects.get(slug="beta").disattivato and not Modulo.objects.get(slug="gamma").disattivato     # senza app propria resta acceso


@pytest.mark.django_db
def test_ognuno_sceglie_le_sue_app_nel_menu(client, superuser):
    from core import barra
    r = client.get(reverse("core:le_mie_app"))
    assert r.status_code == 200 and "Vale solo per te" in r.content.decode()
    client.post(reverse("core:le_mie_app"), {"fissa_todo": "1", "ordine_todo": "2", "fissa_crm": "1", "ordine_crm": "1"})
    assert barra.per_utente(superuser)["fisse"] == ["crm", "todo"]
    nav = client.get(reverse("core:dashboard")).context["theme"]["nav_principale"]
    assert [v["slug"] for v in nav if v.get("slug") in ("crm", "todo")] == ["crm", "todo"]
    assert [v["slug"] for v in nav][:2] == ["crm", "todo"]                           # Chat e Dashboard non sono più in testa d'ufficio
    # la pagina mostra l'ordine reale dell'header, separando la barra dal menu «Altre»
    r = client.get(reverse("core:le_mie_app"))
    assert [x["slug"] for x in r.context["barra"]] == ["crm", "todo"] and "helpdesk" in [x["slug"] for x in r.context["altre"]]
    assert r.context["theme"]["nav_altre"] and {x["slug"] for x in r.context["altre"]} == {x["slug"] for x in r.context["theme"]["nav_altre"]}
    html = r.content.decode()
    html = html[html.index("Nella barra in alto"):]
    assert html.index("CRM") < html.index("To-Do") < html.index("Nel menu «Altre»") < html.index("Helpdesk")
    assert [x["posizione"] for x in r.context["barra"]] == [1, 2]
    altro = User.objects.create_user("altro")
    assert barra.per_utente(altro)["fisse"] == []                                    # non tocca gli altri
    client.post(reverse("core:le_mie_app"), {"ripristina": "1"})
    assert barra.per_utente(superuser)["fisse"] == []


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


@pytest.mark.django_db
def test_il_lavoro_di_sincronizzazione_non_gira_in_una_transazione(monkeypatch):
    """Dentro una transazione il backup e l'installazione, in altri processi, resterebbero bloccati in attesa."""
    from types import SimpleNamespace

    from core import lavori
    from core.models import Lavoro
    assert sincronia.esegui.senza_transazione is True
    monkeypatch.setattr(lavori, "transaction", SimpleNamespace(atomic=lambda: pytest.fail("non doveva aprire una transazione")))
    lavoro = Lavoro.objects.create(funzione="core.registry.sincronia.esegui", argomenti={})
    assert lavori._esegui(lavoro).stato == Lavoro.FATTO


@pytest.mark.django_db
def test_l_intervallo_di_sincronizzazione_si_imposta_e_resiste_alle_installazioni(settings):
    from core import cron
    from core.models import Pianificazione
    settings.LICENZA_SINCRONIA_OGNI = "2m"
    cron.sincronizza()
    assert Pianificazione.objects.get(funzione="core.registry.sincronia.esegui").ogni == "2m"


def test_le_colonne_del_menu_altre_raggruppano_per_area_in_ordine_alfabetico():
    from core import barra
    voci = [{"label": "Vendite", "categoria": "Vendite"}, {"label": "Contatti", "categoria": "Anagrafiche"}, {"label": "Note spese", "categoria": "Risorse umane"},
            {"label": "Strana", "categoria": "Inventata"}]
    assert [(g["titolo"], [v["label"] for v in g["voci"]]) for g in barra.gruppi(voci)] == [
        ("Vendite e clienti", ["Contatti", "Vendite"]), ("Persone", ["Note spese"]), ("Altre app", ["Strana"])]


@pytest.mark.django_db
def test_il_menu_altre_e_a_colonne_e_le_mie_app_lo_rispecchia(client, superuser):
    r = client.get(reverse("core:le_mie_app"))
    html = r.content.decode()
    assert 'class="ui-dropdown-menu ui-menucol"' in html and "Vendite e clienti" in html and "ui-menucol-titolo" in html
    gruppi = r.context["theme"]["nav_altre_gruppi"]
    menu = [v["slug"] for g in gruppi for v in g["voci"]]
    assert menu == [v["slug"] for v in r.context["altre"]] and r.context["altre"][0]["colonna"] == gruppi[0]["titolo"]
    assert set(menu) == {v["slug"] for v in r.context["theme"]["nav_altre"]}


@pytest.mark.django_db
def test_l_admin_rinomina_un_app_e_il_nome_compare_ovunque(client, superuser):
    modules.sincronizza()
    url = reverse("core:applicazione_nome", args=["discuss"])
    r = client.post(url, {"etichetta": "  Comunicazioni   interne "}, follow=True)
    assert Modulo.objects.get(slug="discuss").etichetta == "Comunicazioni interne" and "Comunicazioni interne" in r.content.decode()
    r = client.get(reverse("core:le_mie_app"))
    voci = [v["label"] for g in r.context["theme"]["nav_altre_gruppi"] for v in g["voci"]] + [v["label"] for v in r.context["theme"]["nav_principale"]]
    assert "Comunicazioni interne" in voci and "Discuss" not in voci
    assert "Comunicazioni interne" in [x["nome"] for x in [*r.context["barra"], *r.context["altre"]]]
    assert next(v for v in applicazioni.voci() if v["slug"] == "discuss")["nome"] == "Comunicazioni interne"
    assert "Comunicazioni interne" in client.get(reverse("core:launcher")).content.decode()
    modules.sincronizza()                                                            # il riallineamento col disco non lo tocca
    assert Modulo.objects.get(slug="discuss").etichetta == "Comunicazioni interne"
    client.post(url, {"etichetta": ""})
    assert Modulo.objects.get(slug="discuss").etichetta == "" and next(v for v in applicazioni.voci() if v["slug"] == "discuss")["nome"] == "Discuss"
    client.post(url, {"etichetta": "Discuss"})                                       # il nome originale non è una personalizzazione
    assert Modulo.objects.get(slug="discuss").etichetta == ""
    client.force_login(User.objects.create_user("semplice"))
    assert client.post(url, {"etichetta": "X"}).status_code == 403


@pytest.mark.django_db
def test_chat_e_dashboard_si_spostano_e_ogni_voce_si_nasconde(client, superuser):
    client.post(reverse("core:le_mie_app"), {"fissa_todo": "1", "ordine_todo": "1", "fissa_dashboard": "1", "ordine_dashboard": "2", "fissa_ai": "1", "ordine_ai": "3",
                                             "fissa_crm": "1", "ordine_crm": "4", "nascosta_crm": "1", "nascosta_helpdesk": "1"})
    tema = client.get(reverse("core:launcher")).context["theme"]
    assert [v["slug"] for v in tema["nav_principale"] if v.get("slug")][:3] == ["todo", "dashboard", "ai"]
    assert "crm" not in [v.get("slug") for v in tema["nav_principale"]] and "helpdesk" not in [v["slug"] for v in tema["nav_altre"]]
    r = client.get(reverse("core:le_mie_app"))
    righe = {x["slug"]: x for x in [*r.context["barra"], *r.context["altre"]]}
    assert righe["crm"]["nascosta"] and righe["helpdesk"]["nascosta"] and "posizione" not in righe["crm"] and righe["ai"]["posizione"] == 3 and 'name="fissa_dashboard"' in r.content.decode()
    # nascosta non vuol dire bloccata: si apre, e mentre ci sei la voce c'è
    r = client.get(reverse("crm:opportunita_lista"))
    assert r.status_code == 200 and "crm" in [v.get("slug") for v in r.context["theme"]["nav_principale"]]
    # Dashboard in «Altre»: finisce nella sua colonna
    client.post(reverse("core:le_mie_app"), {"fissa_todo": "1", "ordine_todo": "1"})
    gruppi = client.get(reverse("core:launcher")).context["theme"]["nav_altre_gruppi"]
    assert "dashboard" in [v["slug"] for g in gruppi if g["titolo"] == "Direzione e strumenti" for v in g["voci"]]
    client.post(reverse("core:le_mie_app"), {"ripristina": "1"})
    assert [v.get("slug") for v in client.get(reverse("core:launcher")).context["theme"]["nav_principale"]][:2] == ["ai", "dashboard"]

