"""Ricerca mirata nella conoscenza: solo nei propri documenti o nella cartella dell'area di lavoro; spazi personali
privati di default anche per l'assistente."""
import pytest
from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.core.files.base import ContentFile

from ai import conoscenza, strumenti
from ai.models import Conversazione, ProgettoChat
from ai.strumenti import conoscenza as strumenti_conoscenza
from core import parametri
from core.models import Azienda

pytestmark = [pytest.mark.django_db,
              pytest.mark.skipif("documenti" not in settings.ADDONS_ATTIVI, reason="serve l'app documenti")]


@pytest.fixture
def scena(settings, tmp_path):
    from documenti import servizi
    from documenti.models import Cartella
    from documenti.pagine import spazio_personale
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    azienda = Azienda.objects.get(pk=1)
    utenti = Group.objects.create(name="Utenti documenti")
    utenti.permissions.set(Permission.objects.filter(content_type__app_label="documenti").exclude(codename="vedi_tutte_cartelle"))
    anna, resp = User.objects.create_user("anna", password="x"), User.objects.create_user("resp", password="x")
    for u in (anna, resp):
        u.groups.add(utenti)
    resp.user_permissions.add(Permission.objects.get(codename="vedi_tutte_cartelle"))
    anna, resp = User.objects.get(pk=anna.pk), User.objects.get(pk=resp.pk)
    mio = spazio_personale(anna, azienda).cartelle.get(padre__isnull=True)
    archivio = Cartella.objects.create(azienda=azienda, nome="Archivio")
    gara = Cartella.objects.create(azienda=azienda, nome="Gara Comune", padre=archivio)
    servizi.carica(mio, ContentFile("Appunti personali: il preventivo del fornitore Verdi è di 12.000 euro.".encode(), name="appunti.txt"))
    servizi.carica(archivio, ContentFile("Listino generale: il preventivo standard è di 9.000 euro.".encode(), name="listino.txt"))
    servizi.carica(gara, ContentFile("Capitolato della gara: il preventivo massimo ammesso è di 15.000 euro.".encode(), name="capitolato.txt"))
    conoscenza.indicizza()
    return {"azienda": azienda, "anna": anna, "resp": resp, "gara": gara}


def _cerca(utente, azienda, dove="ovunque", progetto=None):
    contesto = strumenti.Contesto(utente=utente, azienda=azienda, conversazione=Conversazione.objects.create(utente=utente, progetto=progetto))
    return strumenti_conoscenza.cerca_conoscenza(contesto, "preventivo", fonti=["documento"], dove=dove)


def _nomi(risposta):
    return sorted(r["titolo"].split("«")[1].split("»")[0] for r in risposta["risultati"])


def test_gli_spazi_personali_sono_privati_anche_per_l_assistente(scena):
    assert "appunti.txt" in _nomi(_cerca(scena["anna"], scena["azienda"]))
    assert "appunti.txt" not in _nomi(_cerca(scena["resp"], scena["azienda"]))               # il responsabile non li vede più
    parametri.scrivi("documenti.responsabili_vedono_personali", True, scena["azienda"])
    assert "appunti.txt" in _nomi(_cerca(scena["resp"], scena["azienda"]))                   # se l'azienda lo decide


def test_solo_nei_miei_documenti(scena):
    assert _nomi(_cerca(scena["anna"], scena["azienda"], "miei_documenti")) == ["appunti.txt"]
    vuoto = _cerca(scena["resp"], scena["azienda"], "miei_documenti")
    assert vuoto["risultati"] == [] and "nei documenti personali" in vuoto["nota"]


def test_solo_nella_cartella_dell_area(scena):
    area = ProgettoChat.objects.create(utente=scena["anna"], azienda=scena["azienda"], nome="Gara", cartella_documenti=scena["gara"].pk)
    assert _nomi(_cerca(scena["anna"], scena["azienda"], "cartella_area", progetto=area)) == ["capitolato.txt"]
    senza = ProgettoChat.objects.create(utente=scena["anna"], azienda=scena["azienda"], nome="Altro")
    with pytest.raises(strumenti.ErroreStrumento, match="area di lavoro con una cartella"):
        _cerca(scena["anna"], scena["azienda"], "cartella_area", progetto=senza)


def test_la_nota_dell_area_suggerisce_la_ricerca_nella_cartella(scena):
    from ai.contesto_utente import _nota_cartella
    area = ProgettoChat.objects.create(utente=scena["anna"], azienda=scena["azienda"], nome="Gara", cartella_documenti=scena["gara"].pk)
    conversazione = Conversazione.objects.create(utente=scena["anna"], progetto=area)
    assert 'dove="cartella_area"' in " ".join(_nota_cartella(conversazione, area))


def test_anche_l_elenco_dei_documenti_del_responsabile_li_esclude(client, scena):
    resp = scena["resp"]
    resp.profilo.aziende.set([scena["azienda"]])
    resp.profilo.azienda_predefinita = scena["azienda"]
    resp.profilo.save()
    client.force_login(resp)
    html = client.get("/documenti/documenti/").content.decode()
    assert "listino.txt" in html and "appunti.txt" not in html
    parametri.scrivi("documenti.responsabili_vedono_personali", True, scena["azienda"])
    assert "appunti.txt" in client.get("/documenti/documenti/").content.decode()
