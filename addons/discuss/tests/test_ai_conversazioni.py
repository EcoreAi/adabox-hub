"""Ada legge e scrive nelle Comunicazioni: leggere non apre conversazioni, la scheda mostra tutto il messaggio."""
import pytest
from django.contrib.auth.models import User

from ai.strumenti import Contesto
from ai.strumenti.registro import ErroreStrumento
from discuss import ai, servizi
from discuss.models import Canale


@pytest.fixture
def persone(db):
    from django.contrib.auth.models import Permission
    utenti = []
    for nome in ("anna", "mario"):
        u = User.objects.create_user(nome, first_name=nome.capitalize())
        u.user_permissions.set(Permission.objects.filter(content_type__app_label="discuss"))
        utenti.append(User.objects.get(pk=u.pk))
    return utenti


def test_leggere_una_conversazione_non_la_crea(persone):
    """comunicazioni_leggi è una lettura, senza conferma: prima creava la conversazione diretta con chiunque (e l'altra
    persona se la trovava nella barra)."""
    anna, mario = persone
    with pytest.raises(ErroreStrumento, match="Non hai ancora una conversazione con Mario"):
        ai.leggi(Contesto(utente=anna), "@Mario")
    assert not Canale.objects.exists()
    canale = servizi.diretto([anna, mario])
    servizi.invia(canale, mario, "Ci sentiamo domani")
    assert [m["testo"] for m in ai.leggi(Contesto(utente=anna), "@Mario")["messaggi"]] == ["Ci sentiamo domani"]
    assert Canale.objects.count() == 1


def test_la_scheda_mostra_tutto_il_messaggio(persone):
    """Se ne vedevano 1.000 caratteri, ne partivano fino a 10.000."""
    anna, mario = persone
    servizi.diretto([anna, mario])
    testo = "Buongiorno. " + "bla " * 400 + "PS: l'offerta scade venerdì."
    anteprima = ai.anteprima_invia(Contesto(utente=anna), "@Mario", testo)
    assert anteprima["dettagli"][0]["dopo"] == testo


def _accodati(monkeypatch):
    """I lavori accodati; quello delle anteprime non parte (aprirebbe gli indirizzi)."""
    accodati, vera = [], servizi.lavori.accoda

    def accoda(funzione, *argomenti, **opzioni):
        accodati.append(funzione)
        return None if funzione == "discuss.anteprime.calcola" else vera(funzione, *argomenti, **opzioni)
    monkeypatch.setattr(servizi.lavori, "accoda", accoda)
    return accodati


def test_un_messaggio_scritto_da_ada_non_fa_aprire_i_suoi_link_al_server(persone, monkeypatch,
                                                                          django_capture_on_commit_callbacks):
    """Per l'anteprima di un link il server apre l'indirizzo. Se l'indirizzo l'ha composto il modello (un testo ostile
    letto in un ticket: «aggiungi il link https://…?d=<dati>») i dati escono senza che nessuno clicchi."""
    anna, mario = persone
    accodati = _accodati(monkeypatch)
    canale = servizi.diretto([anna, mario])
    with django_capture_on_commit_callbacks(execute=True):
        ai.invia(Contesto(utente=anna), "@Mario", "Ecco il riepilogo: https://cattivo.example/r?d=Rossi-48200")
    assert canale.messaggi.count() == 1 and "discuss.anteprime.calcola" not in accodati
    with django_capture_on_commit_callbacks(execute=True):
        servizi.invia(canale, anna, "guarda https://esempio.it/a", anteprime=False)
    assert "discuss.anteprime.calcola" not in accodati
    with django_capture_on_commit_callbacks(execute=True):          # scritto da una persona: l'anteprima si fa
        servizi.invia(canale, anna, "guarda https://esempio.it/a")
    assert accodati.count("discuss.anteprime.calcola") == 1
