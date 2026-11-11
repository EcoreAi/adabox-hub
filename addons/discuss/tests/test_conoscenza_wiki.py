"""La wiki come fonte dell'assistente del sito: si scrive una volta, l'AI del sito ne legge solo gli spazi scelti."""
import pytest
from django.contrib.auth.models import User

from core.models import Azienda
from discuss import assistente_sito
from discuss.forms import SportelloForm
from discuss.models import Sportello, VoceConoscenza
from wiki.models import PaginaWiki, SpazioWiki

pytestmark = pytest.mark.django_db


@pytest.fixture
def w(db, monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    azienda = Azienda.objects.get(pk=1)
    prodotti = SpazioWiki.objects.create(azienda=azienda, nome="Prodotti")
    interno = SpazioWiki.objects.create(azienda=azienda, nome="Procedure interne")
    with django_capture_on_commit_callbacks(execute=True):
        piani = PaginaWiki.objects.create(azienda=azienda, spazio=prodotti, titolo="Piani")
        essenziale = PaginaWiki.objects.create(azienda=azienda, spazio=prodotti, padre=piani, titolo="Essenziale",
                                               testo="# Prezzo\nIl piano Essenziale costa 390 euro al mese. Vedi [[Condizioni|le condizioni]].")
        margini = PaginaWiki.objects.create(azienda=azienda, spazio=interno, titolo="Margini", testo="Il margine minimo è il 35%.")
        sportello = Sportello.objects.create(nome="Sito", modalita=Sportello.AI)
    return {"azienda": azienda, "prodotti": prodotti, "interno": interno, "essenziale": essenziale, "margini": margini,
            "piani": piani, "sportello": sportello}


def _scegli(sportello, capture, *spazi):
    with capture(execute=True):
        sportello.spazi_wiki = [s.pk for s in spazi]
        sportello.save()


def _voci(sportello):
    return {v.titolo: v for v in VoceConoscenza.objects.filter(sportello=sportello, pagina_wiki__isnull=False)}


def test_le_pagine_degli_spazi_scelti_diventano_conoscenza_del_sito(w, django_capture_on_commit_callbacks):
    _scegli(w["sportello"], django_capture_on_commit_callbacks, w["prodotti"])
    voci = _voci(w["sportello"])
    assert list(voci) == ["Prodotti › Piani › Essenziale"]                      # la pagina vuota e lo spazio interno no
    voce = voci["Prodotti › Piani › Essenziale"]
    assert voce.tipo == VoceConoscenza.WIKI and "390 euro" in voce.testo and "le condizioni" in voce.testo and "[[" not in voce.testo
    assert not VoceConoscenza.objects.filter(testo__contains="margine").exists()


def test_l_ai_del_sito_trova_la_pagina_e_non_l_interno(w, django_capture_on_commit_callbacks):
    _scegli(w["sportello"], django_capture_on_commit_callbacks, w["prodotti"])
    trovati = assistente_sito.cerca(w["sportello"], "quanto costa il piano Essenziale")
    assert trovati and "390 euro" in trovati[0][1].testo
    assert not assistente_sito.cerca(w["sportello"], "margine minimo")


def test_le_modifiche_della_wiki_seguono(w, django_capture_on_commit_callbacks):
    _scegli(w["sportello"], django_capture_on_commit_callbacks, w["prodotti"])
    p = w["essenziale"]
    with django_capture_on_commit_callbacks(execute=True):
        p.testo = "Il piano Essenziale costa 420 euro al mese."
        p.save()
    assert "420 euro" in _voci(w["sportello"])["Prodotti › Piani › Essenziale"].testo
    with django_capture_on_commit_callbacks(execute=True):
        w["piani"].titolo = "Listino"
        w["piani"].save()
    assert list(_voci(w["sportello"])) == ["Prodotti › Listino › Essenziale"]       # il percorso segue la madre
    with django_capture_on_commit_callbacks(execute=True):
        p.spazio, p.padre = w["interno"], None
        p.save()
    assert not _voci(w["sportello"])                                                 # spostata in uno spazio interno
    with django_capture_on_commit_callbacks(execute=True):
        p.spazio = w["prodotti"]
        p.save()
    with django_capture_on_commit_callbacks(execute=True):
        p.delete()
    assert not _voci(w["sportello"])


def test_togliere_lo_spazio_toglie_le_pagine(w, django_capture_on_commit_callbacks):
    _scegli(w["sportello"], django_capture_on_commit_callbacks, w["prodotti"])
    VoceConoscenza.objects.create(sportello=w["sportello"], titolo="Orari", testo="Dal lunedì al venerdì.")
    _scegli(w["sportello"], django_capture_on_commit_callbacks)
    assert list(VoceConoscenza.objects.filter(sportello=w["sportello"]).values_list("titolo", flat=True)) == ["Orari"]  # le altre restano


def test_il_modulo_dello_sportello_sceglie_gli_spazi(w):
    form = SportelloForm(instance=w["sportello"])
    assert {c for c, _ in form.fields["spazi"].choices} == {str(w["prodotti"].pk), str(w["interno"].pk)}
    dati = {"nome": "Sito", "benvenuto": "Ciao", "assenza": "Assenti", "distribuzione": w["sportello"].distribuzione,
            "modalita": Sportello.AI, "nome_ai": "Ada", "risposte_per_chat": 20, "risposte_al_giorno": 300, "spazi": [str(w["prodotti"].pk)]}
    dati["operatori"] = [User.objects.create_user("olga").pk]
    form = SportelloForm(dati, instance=w["sportello"])
    assert form.is_valid(), form.errors
    assert form.save().spazi_wiki == [w["prodotti"].pk]


def test_le_voci_della_wiki_si_modificano_nella_wiki_e_la_pagina_lo_dice(client, w, django_capture_on_commit_callbacks):
    _scegli(w["sportello"], django_capture_on_commit_callbacks, w["prodotti"])
    root = User.objects.create_superuser("root", "r@x.it", "x")
    root.profilo.aziende.set([w["azienda"]])
    root.profilo.azienda_predefinita = w["azienda"]
    root.profilo.save()
    client.force_login(root)
    voce = VoceConoscenza.objects.get(pagina_wiki=w["essenziale"].pk)
    assert client.get(f"/discuss/conoscenza/{voce.pk}/modifica/").status_code == 403
    faq = VoceConoscenza.objects.create(sportello=w["sportello"], titolo="Orari", testo="x")
    assert client.get(f"/discuss/conoscenza/{faq.pk}/modifica/").status_code == 200
    pubblica = client.get(f"/wiki/pagine/{w['essenziale'].pk}/").content.decode()
    assert "Pubblica" in pubblica and "«Sito»" in pubblica
    assert "Pubblica" not in client.get(f"/wiki/pagine/{w['margini'].pk}/").content.decode()
