import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from core import allegati, parametri
from core.models import Azienda
from documenti import accesso, quote, servizi
from documenti.models import Cartella, Documento, MembroSpazio, QuotaUtente, Spazio, Versione
from documenti.pagine import crea_spazio, spazio_personale

KB = 1024


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    azienda = Azienda.objects.get(pk=1)
    utenti = Group.objects.create(name="Utenti documenti")
    utenti.permissions.set(Permission.objects.filter(content_type__app_label="documenti").exclude(
        codename__in=["vedi_tutte_cartelle", "crea_spazio_condiviso"]))
    anna, bruno, carla = (User.objects.create_user(n, password="x") for n in ("anna", "bruno", "carla"))
    for u in (anna, bruno, carla):
        u.groups.add(utenti)
    responsabile = User.objects.create_user("resp", password="x")
    responsabile.groups.add(utenti)
    responsabile.user_permissions.add(Permission.objects.get(codename="vedi_tutte_cartelle"),
                                      Permission.objects.get(codename="crea_spazio_condiviso"))
    return {"azienda": azienda, **{u.username: User.objects.get(pk=u.pk) for u in (anna, bruno, carla, responsabile)}}


def _file(nome="nota.txt", byte=10):
    return ContentFile(b"x" * byte, name=nome)


def _radice(spazio):
    return spazio.cartelle.get(padre__isnull=True)


def test_spazio_personale_al_primo_accesso(client, scena):
    client.force_login(scena["anna"])
    html = client.get("/documenti/").content.decode()
    spazio = Spazio.objects.get(proprietario=scena["anna"])
    assert spazio.personale and _radice(spazio).nome == "Il mio spazio" and "I miei spazi" in html
    client.get("/documenti/")
    assert Spazio.objects.filter(proprietario=scena["anna"]).count() == 1           # una volta sola


def test_chi_vede_gli_spazi(scena):
    azienda, anna, bruno, resp = scena["azienda"], scena["anna"], scena["bruno"], scena["resp"]
    personale = spazio_personale(anna, azienda)
    sotto = Cartella.objects.create(azienda=azienda, nome="Bozze", padre=_radice(personale))
    assert sotto.spazio == personale                                                # eredita lo spazio della madre
    assert sotto in accesso.visibili(anna, azienda) and sotto not in accesso.visibili(bruno, azienda)
    assert sotto in accesso.visibili(resp, azienda)                                  # regole aziendali (default)
    parametri.scrivi("documenti.responsabili_vedono_personali", False, azienda)
    assert sotto not in accesso.visibili(resp, azienda)
    progetto = crea_spazio(azienda, resp, "Progetto X", Spazio.CONDIVISO)
    MembroSpazio.objects.create(spazio=progetto, utente=bruno, ruolo=MembroSpazio.LETTURA)
    MembroSpazio.objects.create(spazio=progetto, utente=anna, ruolo=MembroSpazio.SCRITTURA)
    radice = _radice(progetto)
    assert accesso.puo_scrivere(anna, radice) and not accesso.puo_scrivere(bruno, radice)
    assert radice in accesso.visibili(bruno, azienda) and radice not in accesso.visibili(scena["carla"], azienda)


def test_nuovo_spazio_condiviso_solo_con_il_permesso(client, scena):
    client.force_login(scena["anna"])
    assert client.post("/documenti/spazio/", {"nome": "Team", "tipo": "condiviso"}).status_code == 403
    client.post("/documenti/spazio/", {"nome": "Ricerche"})
    assert Spazio.objects.get(nome="Ricerche").personale
    client.force_login(scena["resp"])
    r = client.post("/documenti/spazio/", {"nome": "Team", "tipo": "condiviso"})
    team = Spazio.objects.get(nome="Team")
    assert r.status_code == 302 and r["Location"] == f"/documenti/spazi/{team.pk}/modifica/"
    assert MembroSpazio.objects.get(spazio=team).ruolo == "gestione"


def test_quota_personale_dell_utente(scena):
    azienda, anna = scena["azienda"], scena["anna"]
    QuotaUtente.objects.create(azienda=azienda, utente=anna, quota_mb=1)
    radice = _radice(spazio_personale(anna, azienda))
    servizi.carica(radice, _file("a.bin", 600 * KB), anna)
    with pytest.raises(allegati.AllegatoNonValido, match="quota personale esaurita"):
        servizi.carica(radice, _file("b.bin", 600 * KB), anna)
    assert quote.riepilogo(radice.spazio)["usato"] == 600 * KB
    parametri.scrivi("documenti.quota_utente_mb", 5, azienda)                         # il default non conta: ha la sua
    with pytest.raises(allegati.AllegatoNonValido):
        servizi.carica(radice, _file("b.bin", 600 * KB), anna)


def test_quota_dell_azienda_e_dello_spazio_condiviso(scena):
    azienda = scena["azienda"]
    progetto = crea_spazio(azienda, scena["resp"], "Progetto", Spazio.CONDIVISO)
    Spazio.objects.filter(pk=progetto.pk).update(quota_mb=1)
    radice = _radice(Spazio.objects.get(pk=progetto.pk))
    servizi.carica(radice, _file("a.bin", 700 * KB), scena["resp"])
    with pytest.raises(allegati.AllegatoNonValido, match="quota dello spazio «Progetto» esaurita"):
        servizi.carica(radice, _file("b.bin", 700 * KB), scena["resp"])
    parametri.scrivi("documenti.quota_azienda_mb", 1, azienda)
    with pytest.raises(allegati.AllegatoNonValido, match="spazio dell'azienda esaurito"):
        servizi.carica(_radice(spazio_personale(scena["anna"], azienda)), _file("c.bin", 400 * KB), scena["anna"])


def test_spostare_in_uno_spazio_pieno(client, scena):
    azienda, anna = scena["azienda"], scena["anna"]
    QuotaUtente.objects.create(azienda=azienda, utente=anna, quota_mb=1)
    archivio = Cartella.objects.create(azienda=azienda, nome="Comune")
    grosso = servizi.carica(archivio, _file("grosso.bin", 1100 * KB), anna)
    radice = _radice(spazio_personale(anna, azienda))
    client.force_login(anna)
    r = client.post("/documenti/azione/", {"azione": "sposta", "pk": [grosso.pk], "cartella": radice.pk}, follow=True)
    grosso.refresh_from_db()
    assert grosso.cartella == archivio and "quota personale esaurita" in r.content.decode()


def test_dimensione_massima_per_azienda(scena, settings):
    azienda, anna = scena["azienda"], scena["anna"]
    radice = _radice(spazio_personale(anna, azienda))
    parametri.scrivi("documenti.file_max_mb", 1, azienda)
    with pytest.raises(allegati.AllegatoNonValido, match="supera 1 MB"):
        servizi.carica(radice, _file("grande.bin", 1100 * KB), anna)
    parametri.scrivi("documenti.file_max_mb", 50, azienda)
    settings.DOCUMENTI_FILE_MAX_MB = 2                                               # tetto del server
    assert quote.max_file_mb(azienda) == 2
    servizi.carica(radice, _file("grande.bin", 1100 * KB), anna)


def test_versioni(client, scena):
    azienda, anna = scena["azienda"], scena["anna"]
    parametri.scrivi("documenti.versioni_max", 2, azienda)
    radice = _radice(spazio_personale(anna, azienda))
    primo = servizi.carica(radice, ContentFile(b"uno", name="offerta.docx"), anna)
    for contenuto in (b"due", b"tre", b"quattro"):
        servizi.carica(radice, ContentFile(contenuto, name="offerta.docx"), anna)
    primo.refresh_from_db()
    assert Documento.objects.filter(cartella=radice).count() == 1 and primo.versione == 4
    assert list(primo.versioni.values_list("numero", flat=True)) == [3, 2]          # le ultime 2
    assert primo.file.open("rb").read() == b"quattro"
    client.force_login(anna)
    assert client.get(f"/documenti/{primo.pk}/versioni/2/").getvalue() == b"due"
    assert "Versioni precedenti" in client.get(f"/documenti/{primo.pk}/anteprima/").content.decode()
    client.post(f"/documenti/{primo.pk}/versioni/2/ripristina/")
    primo.refresh_from_db()
    assert primo.versione == 5 and primo.file.open("rb").read() == b"due" and primo.versioni.count() == 2
    assert quote.riepilogo(radice.spazio)["usato"] == len(b"due") + len(b"quattro") + len(b"tre")
    client.force_login(scena["bruno"])
    assert client.get(f"/documenti/{primo.pk}/versioni/4/").status_code == 404      # spazio altrui
    nomi = [v.file.name for v in primo.versioni.all()]
    servizi.cestina([primo])
    primo.refresh_from_db()
    servizi.elimina([primo])
    assert not Versione.objects.exists()
    assert not any(primo.file.storage.exists(n) for n in nomi)                    # anche i file delle versioni


def test_carica_dalla_pagina_e_pagine_di_gestione(client, scena):
    azienda, anna = scena["azienda"], scena["anna"]
    client.force_login(anna)
    client.get("/documenti/")
    radice = _radice(Spazio.objects.get(proprietario=anna))
    client.post("/documenti/carica/", {"cartella": radice.pk, "file": SimpleUploadedFile("a.txt", b"ciao")})
    html = client.get(f"/documenti/?cartella={radice.pk}").content.decode()
    assert "a.txt" in html and "dei tuoi spazi personali" in html and "doc-uso-barra" in html
    progetto = crea_spazio(azienda, scena["resp"], "Progetto", Spazio.CONDIVISO)
    MembroSpazio.objects.create(spazio=progetto, utente=anna, ruolo=MembroSpazio.GESTIONE)
    assert client.get(f"/documenti/spazi/{progetto.pk}/").status_code == 200        # lo gestisce
    client.post(f"/documenti/spazi/{progetto.pk}/modifica/", {
        "nome": "Progetto", "quota_mb": "99999", "descrizione": "", "righe0-TOTAL_FORMS": "0",
        "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000"})
    assert Spazio.objects.get(pk=progetto.pk).quota_mb == 0                        # la quota no: la decide il responsabile
    client.force_login(scena["carla"])
    assert client.get(f"/documenti/spazi/{progetto.pk}/").status_code == 404
