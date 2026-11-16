"""SharePoint: il formato delle chiamate a Microsoft Graph, l'accesso «client credentials», l'allineamento nei due versi
contro la SharePoint finta e le garanzie di base del modulo (azienda, permessi, segreti)."""
from urllib.parse import parse_qs

import httpx2 as httpx
import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.base import ContentFile

from core.models import Azienda, Lavoro
from documenti import servizi
from documenti.models import Cartella, Documento, Versione
from sharepoint import graph, prova, sincronia
from sharepoint.forms import CollegamentoForm
from sharepoint.models import CollegamentoSharePoint, FileProva, FileSharePoint

pytestmark = pytest.mark.django_db
URL = "/sharepoint/collegamenti/"
DA, VERSO, ENTRAMBI = CollegamentoSharePoint.DA_SHAREPOINT, CollegamentoSharePoint.VERSO_SHAREPOINT, CollegamentoSharePoint.ENTRAMBI


@pytest.fixture(autouse=True)
def file_privati(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path


@pytest.fixture
def azienda():
    return Azienda.objects.first()


@pytest.fixture
def cartella(azienda):
    return Cartella.objects.create(azienda=azienda, nome="Contratti")


def _collegamento(cartella, verso=DA, percorso="Adabox"):
    return CollegamentoSharePoint.objects.create(azienda=cartella.azienda, nome="Contratti", cartella=cartella, verso=verso,
                                                 percorso=percorso)


def _giro(c):
    return sincronia.giro(c.pk)


def _testo(doc):
    doc.refresh_from_db()
    with doc.file.open("rb") as f:
        return f.read()


def _sp(c, percorso):
    return bytes(FileProva.objects.get(collegamento=c, percorso=percorso).contenuto)


def _carica(cartella, nome, testo):
    return servizi.carica(cartella, ContentFile(testo, name=nome), None)


# --- valori scritti dall'utente -------------------------------------------------------------------------------------

def test_sito_tenant_e_percorso():
    assert graph.sito_valido("https://azienda.sharepoint.com/sites/Ufficio/Shared%20Documents/Forms/AllItems.aspx") == "azienda.sharepoint.com/sites/Ufficio"
    assert graph.sito_valido("azienda.sharepoint.com/teams/Vendite") == "azienda.sharepoint.com/teams/Vendite"
    assert graph.sito_valido("https://azienda.sharepoint.com/") == "azienda.sharepoint.com"
    for sbagliato in ("https://example.com/sites/x", "sharepoint.com", "", "https://azienda.sharepoint.com.evil.it/sites/x"):
        with pytest.raises(graph.ErroreSharePoint):
            graph.sito_valido(sbagliato)
    assert graph.tenant_valido(" Azienda.onmicrosoft.com ") == "azienda.onmicrosoft.com"
    assert graph.tenant_valido("72f988bf-86f1-41af-91ab-2d7cd011db47") == "72f988bf-86f1-41af-91ab-2d7cd011db47"
    with pytest.raises(graph.ErroreSharePoint):
        graph.tenant_valido("../evil")
    assert graph.percorso_pulito("/Commerciale//Contratti/") == "Commerciale/Contratti"
    with pytest.raises(graph.ErroreSharePoint):
        graph.percorso_pulito("Commerciale/../Segreti")
    assert graph.nome_per_sharepoint('Offerta: "Rossi"?.pdf') == "Offerta_ _Rossi__.pdf"


# --- il client Graph ------------------------------------------------------------------------------------------------

def _client(gestore, deposito=None):
    return graph.Graph("azienda.onmicrosoft.com", "app-id", "segreto", deposito=deposito, transport=httpx.MockTransport(gestore))


def test_token_client_credentials_e_nuovo_token_al_401():
    chiamate = []

    def gestore(r):
        chiamate.append(r)
        if r.url.host == "login.microsoftonline.com":
            dati = parse_qs(r.content.decode())
            assert r.url.path == "/azienda.onmicrosoft.com/oauth2/v2.0/token"
            assert dati == {"grant_type": ["client_credentials"], "client_id": ["app-id"], "client_secret": ["segreto"],
                            "scope": ["https://graph.microsoft.com/.default"]}
            numero = sum(1 for c in chiamate if c.url.host == "login.microsoftonline.com")
            return httpx.Response(200, json={"access_token": f"t{numero}", "expires_in": 3600})
        if r.headers["Authorization"] == "Bearer t1":
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken", "message": "expired"}})
        assert r.url.path == "/v1.0/sites/azienda.sharepoint.com:/sites/Ufficio"
        return httpx.Response(200, json={"id": "sito-1", "displayName": "Ufficio"})

    salvati = []

    class Deposito(graph.Deposito):
        def salva(self, token, scade):
            salvati.append(token)

    assert _client(gestore, Deposito()).sito("azienda.sharepoint.com/sites/Ufficio")["nome"] == "Ufficio"
    assert salvati == ["t1", "t2"]


def test_errori_di_graph():
    def gestore(stato, **altro):
        def risposta(r):
            if r.url.host == "login.microsoftonline.com":
                return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
            return httpx.Response(stato, json={"error": {"code": "x", "message": "dettaglio"}}, **altro)
        return risposta

    with pytest.raises(graph.ErroreTemporaneo, match="429"):
        _client(gestore(429, headers={"Retry-After": "10"})).sito("a.sharepoint.com")
    with pytest.raises(graph.ErroreTemporaneo):
        _client(gestore(503)).sito("a.sharepoint.com")
    with pytest.raises(graph.ErroreSharePoint, match="Sites.Selected") as e:
        _client(gestore(403)).sito("a.sharepoint.com")
    assert not isinstance(e.value, graph.ErroreTemporaneo)
    with pytest.raises(graph.ErroreSharePoint, match="non esiste"):
        _client(gestore(404)).sito("a.sharepoint.com/sites/x")

    def rifiutato(r):
        return httpx.Response(400, json={"error": "unauthorized_client", "error_description": "AADSTS7000215: Invalid client secret."})
    with pytest.raises(graph.ErroreSharePoint, match="AADSTS7000215"):
        _client(rifiutato).sito("a.sharepoint.com")


def test_indirizzi_fuori_da_microsoft_rifiutati():
    def gestore(r):
        if r.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if r.url.path.endswith("/content"):
            return httpx.Response(302, headers={"Location": "https://169.254.169.254/latest/meta-data"})
        return httpx.Response(200, json={"value": [], "@odata.nextLink": "https://evil.example/pagina2"})

    g = _client(gestore)
    with pytest.raises(graph.ErroreSharePoint, match="indirizzo inatteso"):
        g.scarica("d", "i", 1000)
    with pytest.raises(graph.ErroreSharePoint, match="pagina inatteso"):
        list(g.figli("d", "root"))


# --- da SharePoint ad adabox ----------------------------------------------------------------------------------------

def test_da_sharepoint_porta_file_e_sottocartelle(cartella):
    c = _collegamento(cartella)
    prova.prepara(c)
    for i in range(4):                                  # più di una pagina della prova: si segue @odata.nextLink
        prova.scrivi(c, f"Adabox/Offerte/Offerta {i}.txt", f"offerta {i}".encode())
    prova.scrivi(c, "Fuori/Altro.txt", b"non collegato")
    esito = _giro(c)
    assert "5 file copiati da SharePoint" in esito, esito
    offerte = Cartella.objects.get(padre=cartella, nome="Offerte")
    assert offerte.documenti.count() == 4 and _testo(offerte.documenti.get(nome="Offerta 2.txt")) == b"offerta 2"
    assert cartella.documenti.get().nome == "Benvenuto.txt"
    assert not Documento.objects.filter(nome="Altro.txt").exists()
    c.refresh_from_db()
    assert not c.in_errore and c.ultimo_giro and c.accesso_cifrato and b"prova-graph" not in c.accesso_cifrato.encode()
    assert "0 file copiati" in _giro(c)                 # niente è cambiato: niente si scarica


def test_da_sharepoint_modifica_spostamento_e_cancellazione(cartella):
    c = _collegamento(cartella)
    prova.prepara(c)
    f = prova.scrivi(c, "Adabox/Listino.csv", b"v1")
    _giro(c)
    doc = Documento.objects.get(nome="Listino.csv")
    prova.scrivi(c, "Adabox/Listino.csv", b"v2")
    assert "1 file copiati" in _giro(c)
    assert _testo(doc) == b"v2" and doc.versione == 2 and Versione.objects.filter(documento=doc).count() == 1
    f.refresh_from_db()
    f.percorso = "Adabox/Archivio/Listino 2026.csv"     # rinominato e spostato su SharePoint
    f.save()
    FileProva.objects.create(collegamento=c, percorso="Adabox/Archivio", cartella=True, id_esterno="Farch", ctag="x")
    assert "0 file copiati" in _giro(c)
    doc.refresh_from_db()
    assert doc.nome == "Listino 2026.csv" and doc.cartella.nome == "Archivio" and doc.cartella.padre == cartella
    FileProva.objects.filter(pk=f.pk).delete()
    assert "1 documenti nel cestino" in _giro(c)
    doc.refresh_from_db()
    assert doc.cestinato_il is not None and not FileSharePoint.objects.filter(documento=doc).exists()


def test_da_sharepoint_non_scrive_e_non_crea_cartelle(cartella):
    c = _collegamento(cartella, percorso="Non esiste")
    FileProva.objects.create(collegamento=c, percorso="Altro", cartella=True, id_esterno="F1", ctag="x")
    _carica(cartella, "Solo qui.txt", b"adabox")
    esito = _giro(c)
    c.refresh_from_db()
    assert c.in_errore and "Non esiste" in esito
    assert not FileProva.objects.filter(percorso__startswith="Non esiste").exists()


def test_file_troppo_grandi_o_vietati_restano_fuori(cartella, settings):
    c = _collegamento(cartella)
    prova.prepara(c)
    prova.scrivi(c, "Adabox/virus.exe", b"MZ")
    prova.scrivi(c, "Adabox/enorme.bin", b"x" * (21 * 1024 * 1024))
    esito = _giro(c)
    assert "virus.exe" in esito and "enorme.bin" in esito and "supera 20 MB" in esito
    assert set(Documento.objects.values_list("nome", flat=True)) == {"Benvenuto.txt"}


# --- da adabox a SharePoint -----------------------------------------------------------------------------------------

def test_verso_sharepoint_carica_aggiorna_e_rinomina(cartella):
    c = _collegamento(cartella, verso=VERSO, percorso="Da adabox/Contratti")
    sotto = Cartella.objects.create(azienda=cartella.azienda, nome="Clienti: 2026", padre=cartella)
    uno = _carica(cartella, "Contratto quadro.txt", b"bozza")
    due = _carica(sotto, "Rossi?.txt", b"rossi")
    prova.prepara(c)
    prova.scrivi(c, "Da adabox/Contratti/Solo su SharePoint.txt", b"resta la")
    esito = _giro(c)
    assert "2 file copiati su SharePoint" in esito and "da SharePoint" not in esito, esito
    assert _sp(c, "Da adabox/Contratti/Contratto quadro.txt") == b"bozza"
    assert _sp(c, "Da adabox/Contratti/Clienti_ 2026/Rossi_.txt") == b"rossi"
    assert not Documento.objects.filter(nome="Solo su SharePoint.txt").exists()
    assert "0 file copiati" in _giro(c)
    servizi.nuova_versione(uno, ContentFile(b"firmato", name="x.txt"))
    Documento.objects.filter(pk=due.pk).update(nome="Rossi Srl.txt")
    assert "2 file copiati" in _giro(c)
    assert _sp(c, "Da adabox/Contratti/Contratto quadro.txt") == b"firmato"
    assert _sp(c, "Da adabox/Contratti/Clienti_ 2026/Rossi Srl.txt") == b"rossi"
    assert not FileProva.objects.filter(percorso__endswith="Rossi_.txt").exists()     # spostato, non duplicato
    servizi.cestina([uno])
    _giro(c)
    assert FileProva.objects.filter(percorso="Da adabox/Contratti/Contratto quadro.txt").exists()   # su SharePoint non si cancella


def test_file_grandi_con_la_sessione_di_caricamento(cartella, monkeypatch):
    monkeypatch.setattr(graph, "PICCOLO", 1000)
    monkeypatch.setattr(graph, "PEZZO", 320)
    c = _collegamento(cartella, verso=VERSO)
    contenuto = bytes(range(256)) * 10
    _carica(cartella, "Grande.bin", contenuto)
    assert "1 file copiati" in _giro(c)
    assert _sp(c, "Adabox/Grande.bin") == contenuto


# --- nei due versi --------------------------------------------------------------------------------------------------

def test_entrambi_senza_rimbalzi_e_con_il_conflitto(cartella):
    c = _collegamento(cartella, verso=ENTRAMBI)
    qui = _carica(cartella, "Da adabox.txt", b"adabox")
    esito = _giro(c)
    assert "1 file copiati da SharePoint" in esito and "1 file copiati su SharePoint" in esito, esito   # il benvenuto e il nostro
    assert "0 file copiati da SharePoint, 0 file copiati su SharePoint" in _giro(c)
    servizi.nuova_versione(qui, ContentFile(b"modificato qui", name="x.txt"))
    prova.scrivi(c, "Adabox/Da adabox.txt", b"modificato la")
    esito = _giro(c)
    assert "cambiato da entrambe le parti" in esito
    assert _testo(qui) == b"modificato la" and _sp(c, "Adabox/Da adabox.txt") == b"modificato la"
    with qui.versioni.get(numero=2).file.open("rb") as f:
        assert f.read() == b"modificato qui"                  # niente si perde
    assert "0 file copiati da SharePoint, 0 file copiati su SharePoint" in _giro(c)


def test_un_giro_alla_volta(cartella):
    c = _collegamento(cartella)
    assert sincronia._prendi(c.pk)
    assert _giro(c) == "c'è già un giro in corso"


# --- modulo, pagine e permessi --------------------------------------------------------------------------------------

def _utente(azienda, *permessi):
    u = User.objects.create_user("prova", "prova@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="sharepoint", codename__in=permessi))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


def test_si_crea_vero_con_il_segreto_cifrato(client, azienda, cartella):
    client.force_login(_utente(azienda, "view_collegamentosharepoint", "add_collegamentosharepoint"))
    dati = {"nome": "Contratti", "cartella": cartella.pk, "verso": DA, "modalita": "vera", "attivo": "on",
            "sito": "https://azienda.sharepoint.com/sites/Ufficio/SitePages/Home.aspx", "libreria": "", "percorso": "/Contratti/",
            "tenant": "azienda.onmicrosoft.com", "client_id": "app-id", "nuovo_segreto": "S3greto~molto.lungo"}
    risposta = client.post(URL + "nuovo/", dati)
    assert risposta.status_code == 302, risposta.content.decode()[:2000]
    c = CollegamentoSharePoint.objects.get()
    assert c.azienda == azienda and c.sito == "azienda.sharepoint.com/sites/Ufficio" and c.percorso == "Contratti"
    assert c.segreto() == "S3greto~molto.lungo" and "S3greto" not in c.segreto_cifrato
    pagina = client.get(f"{URL}{c.pk}/").content.decode()
    assert "S3greto" not in pagina and "salvato (cifrato)" in pagina


def test_modulo_vero_vuole_le_credenziali_e_niente_sovrapposizioni(azienda, cartella):
    form = CollegamentoForm(data={"nome": "x", "cartella": cartella.pk, "verso": DA, "modalita": "vera", "sito": "example.com"})
    assert not form.is_valid()
    assert {"sito", "tenant", "client_id", "nuovo_segreto"} <= set(form.errors)
    _collegamento(cartella)
    sotto = Cartella.objects.create(azienda=azienda, nome="Sotto", padre=cartella)
    form = CollegamentoForm(data={"nome": "y", "cartella": sotto.pk, "verso": DA, "modalita": "prova"})
    assert not form.is_valid() and "già dentro" in str(form.errors["cartella"])


def test_cambiare_modalita_azzera_la_corrispondenza(cartella):
    c = _collegamento(cartella)
    _giro(c)
    assert FileSharePoint.objects.filter(collegamento=c).exists()
    form = CollegamentoForm(instance=c, data={"nome": c.nome, "cartella": cartella.pk, "verso": DA, "modalita": "vera",
                                              "sito": "azienda.sharepoint.com", "tenant": "azienda.onmicrosoft.com",
                                              "client_id": "app", "nuovo_segreto": "s", "percorso": "Adabox"})
    assert form.is_valid(), form.errors
    form.save()
    assert not FileSharePoint.objects.filter(collegamento=c).exists() and not FileProva.objects.filter(collegamento=c).exists()


def test_bottoni_in_prova(client, azienda, cartella):
    c = _collegamento(cartella)
    client.force_login(_utente(azienda, "view_collegamentosharepoint", "change_collegamentosharepoint"))
    pagina = client.get(f"{URL}{c.pk}/").content.decode()
    assert "Simula un file nuovo" in pagina and "Sulla SharePoint finta" in pagina
    base = f"{URL}{c.pk}/bottone/"
    assert "funziona" in client.post(base + "verifica/", follow=True).content.decode()
    assert client.post(base + "simula_nuovo/").status_code == 302
    assert client.post(base + "sincronizza/").status_code == 302    # LAVORI_SINCRONI: il giro gira subito
    assert Lavoro.objects.filter(funzione="sharepoint.sincronia.giro").exists()
    assert Documento.objects.filter(cartella=cartella).count() == 2  # il benvenuto e il file simulato
    assert "modificato" in client.post(base + "simula_modifica/", follow=True).content.decode()
    c.modalita = CollegamentoSharePoint.VERA
    c.save()
    assert "Simula" not in client.get(f"{URL}{c.pk}/").content.decode()


def test_un_altra_azienda_non_vede_i_dati(client, azienda, cartella):
    altra = Azienda.objects.create(nome="Altra azienda")
    _collegamento(cartella)
    estraneo = _collegamento(Cartella.objects.create(azienda=altra, nome="Estranea"))
    estraneo.nome = "ESTRANEO"
    estraneo.save()
    client.force_login(_utente(azienda, "view_collegamentosharepoint"))
    pagina = client.get(URL).content.decode()
    assert "Contratti" in pagina and "ESTRANEO" not in pagina
    assert client.get(f"{URL}{estraneo.pk}/").status_code == 404


def test_senza_permesso_non_si_entra(client, azienda):
    client.force_login(_utente(azienda))
    assert client.get(URL).status_code == 403


def test_nomi_con_cancelletto_non_rimbalzano(cartella):
    c = _collegamento(cartella, verso=ENTRAMBI)
    prova.prepara(c)
    prova.scrivi(c, "Adabox/Offerta #1 al 50%.txt", b"x")
    _giro(c)
    assert "0 file copiati da SharePoint, 0 file copiati su SharePoint" in _giro(c)
    assert FileProva.objects.filter(percorso="Adabox/Offerta #1 al 50%.txt").exists()
