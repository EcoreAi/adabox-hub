"""Le previsioni del magazzino salvate: calcolo per azienda, lavoro della notte e «Aggiorna»."""
import datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission, User
from django.contrib.messages import get_messages
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core import parametri
from core.models import Azienda, Lavoro, Modulo
from previsioni import calcolo, motore, servizio
from previsioni.models import PrevisioneArticolo, StatoCalcolo
from previsioni.servizio import ErrorePrevisione
from previsioni.tests.test_motore import _finta_risposta

pytestmark = [pytest.mark.django_db, pytest.mark.skipif(not apps.is_installed("magazzino"), reason="serve Magazzino")]

if apps.is_installed("magazzino"):
    from magazzino.models import Magazzino, Movimento, ScortaMagazzino
    from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)
    from previsioni import magazzino as pm
    from prodotti.models import Prodotto


def _mov(azienda, prodotto, magazzino, tipo, quantita, giorno):
    return Movimento.objects.create(azienda=azienda, prodotto=prodotto, magazzino=magazzino, quantita=quantita, tipo=tipo,
                                    data=timezone.make_aware(datetime.datetime.combine(giorno, datetime.time(10))))


def _storia(azienda, prodotto, magazzino, periodi, consumo, per="settimana", carico=100):
    """Un carico all'inizio del primo periodo, poi un prelievo a mano a metà di ognuno dei `periodi` completi
    che precedono quello in corso."""
    attuale = motore.inizio(timezone.localdate(), per)
    inizio = motore.avanti(attuale, per, -periodi)
    _mov(azienda, prodotto, magazzino, Movimento.CARICO, carico, inizio)
    for i in range(periodi):
        _mov(azienda, prodotto, magazzino, Movimento.RETTIFICA, -consumo, motore.avanti(inizio, per, i) + datetime.timedelta(days=2))


@pytest.fixture
def servizi(monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    chiamate = []

    def chiama(percorso, dati):
        chiamate.append(dati)
        return _finta_risposta(dati)
    monkeypatch.setattr(servizio, "chiama", chiama)
    return chiamate


@pytest.fixture
def capo(db):
    return User.objects.create_superuser("capo", "capo@example.com", "x")


@pytest.fixture
def s(scena):  # noqa: F811
    """Dieci settimane di storia: il monitor consuma 3 a settimana dal magazzino principale (riga sul totale, scorta
    minima 5), il cavo 2 a settimana dal negozio, dove ha la sua scorta (riga del negozio); la vite ha solo un carico
    (nessun consumo, nessuna riga)."""
    azienda, principale, _, _, monitor, _ = scena
    negozio = Magazzino.objects.create(azienda=azienda, nome="Negozio")
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", codice="CV-3")
    vite = Prodotto.objects.create(azienda=azienda, nome="Vite")
    ScortaMagazzino.objects.create(azienda=azienda, magazzino=negozio, prodotto=cavo, punto_riordino=10, scorta_obiettivo=50)
    _storia(azienda, monitor, principale, 10, 3)
    _storia(azienda, cavo, negozio, 10, 2, carico=60)
    _mov(azienda, vite, principale, Movimento.CARICO, 10, motore.inizio(timezone.localdate(), "settimana"))
    return {"azienda": azienda, "principale": principale, "negozio": negozio, "monitor": monitor, "cavo": cavo, "vite": vite}


def _altra_azienda(nome):
    azienda = Azienda.objects.create(nome=nome)
    magazzino = Magazzino.objects.create(azienda=azienda, nome="Centrale")
    _storia(azienda, Prodotto.objects.create(azienda=azienda, nome="Bullone"), magazzino, 10, 4)
    return azienda


def test_calcolo_salva_una_riga_per_chiave(s, capo, servizi):
    oggi = timezone.localdate()
    lunedi = motore.inizio(oggi, "settimana")
    assert calcolo.magazzino(s["azienda"]) == 2

    assert len(servizi) == 1                                   # una chiamata per tutte le serie, con id opachi
    assert servizi[0]["horizon"] == 52
    assert sorted(x["id"] for x in servizi[0]["series"]) == ["s1", "s2"]
    assert sorted(x["values"] for x in servizi[0]["series"]) == [[2.0] * 10, [3.0] * 10]

    righe = {(r.prodotto_pk, r.magazzino_pk): r for r in PrevisioneArticolo.objects.filter(azienda=s["azienda"])}
    assert set(righe) == {(s["monitor"].pk, None), (s["cavo"].pk, s["negozio"].pk)}
    monitor = righe[(s["monitor"].pk, None)]
    assert (monitor.prodotto, monitor.codice, monitor.magazzino) == ("Monitor", s["monitor"].codice, "")   # nomi copiati
    assert monitor.per == "settimana" and monitor.partenza == 70
    assert len(monitor.futuro) == 52
    assert monitor.futuro[0] == [motore.etichetta(lunedi, "settimana"), 1.0, 3.0, 5.0]       # il periodo in corso
    assert monitor.futuro[1][0] == motore.etichetta(motore.avanti(lunedi, "settimana"), "settimana")
    assert monitor.consumo_mensile == Decimal("123.500")      # mediane 3…54 a settimana, in media 28,5 × 52 / 12
    attesa = pm.proietta(Decimal(70), [tuple(f[1:]) for f in monitor.futuro], "settimana", lunedi, 5, None, oggi)
    assert {campo: getattr(monitor, campo) for campo in attesa} == attesa
    assert monitor.riordino is not None and monitor.quantita_suggerita is not None
    assert monitor.affidabilita["periodi_di_storia"] == 10 and monitor.affidabilita["livello"] == "bassa"
    assert monitor.modello == "finto-timestral" and monitor.calcolata_il is not None

    cavo = righe[(s["cavo"].pk, s["negozio"].pk)]
    assert (cavo.prodotto, cavo.codice, cavo.magazzino) == ("Cavo", "CV-3", "Negozio")
    attesa = pm.proietta(Decimal(40), [tuple(f[1:]) for f in cavo.futuro], "settimana", lunedi, 10, 50, oggi)
    assert cavo.partenza == 40 and {campo: getattr(cavo, campo) for campo in attesa} == attesa

    stato = StatoCalcolo.objects.get(azienda=s["azienda"], cosa="magazzino")
    assert stato.errore == "" and stato.ultimo_ok is not None and stato.ultimo_tentativo is not None

    assert calcolo.magazzino(s["azienda"]) == 2               # il calcolo dopo sostituisce le righe
    assert PrevisioneArticolo.objects.filter(azienda=s["azienda"]).count() == 2


def test_storia_mensile_dodici_mesi_avanti(scena, capo, servizi):  # noqa: F811
    azienda, principale, _, _, monitor, _ = scena
    _storia(azienda, monitor, principale, 14, 10, per="mese", carico=500)
    assert calcolo.magazzino(azienda) == 1
    riga = PrevisioneArticolo.objects.get(azienda=azienda)
    assert servizi[0]["horizon"] == 12 and servizi[0]["series"][0]["values"] == [10.0] * 14
    assert riga.per == "mese" and len(riga.futuro) == 12
    assert riga.futuro[0][0] == motore.etichetta(timezone.localdate().replace(day=1), "mese")
    assert riga.consumo_mensile == Decimal("15.500")          # media delle mediane 10…21


def test_articoli_senza_storia_sufficiente_non_hanno_riga(scena, capo, servizi):  # noqa: F811
    azienda, principale, _, _, monitor, _ = scena
    _storia(azienda, monitor, principale, motore.MIN_PERIODI - 1, 3)
    assert calcolo.magazzino(azienda) == 0
    assert not PrevisioneArticolo.objects.exists() and servizi == []
    stato = StatoCalcolo.objects.get(azienda=azienda, cosa="magazzino")
    assert stato.errore == "" and stato.ultimo_ok is not None


def test_servizio_giu_restano_le_vecchie(s, capo, servizi, monkeypatch):
    assert calcolo.magazzino(s["azienda"]) == 2
    ieri = timezone.now() - datetime.timedelta(days=1)
    PrevisioneArticolo.objects.update(calcolata_il=ieri)
    StatoCalcolo.objects.update(ultimo_ok=ieri, ultimo_tentativo=ieri)
    prima = list(PrevisioneArticolo.objects.order_by("pk").values())

    def giu(percorso, dati):
        raise ErrorePrevisione("Il servizio di previsione non risponde: riprova tra poco.")
    monkeypatch.setattr(servizio, "chiama", giu)
    assert calcolo.magazzino(s["azienda"]) == 0
    calcolo.aggiorna(azienda_id=s["azienda"].pk, cosa="magazzino")         # l'errore non risale al lavoro

    assert list(PrevisioneArticolo.objects.order_by("pk").values()) == prima
    stato = StatoCalcolo.objects.get(azienda=s["azienda"], cosa="magazzino")
    assert stato.errore == "Il servizio di previsione non risponde: riprova tra poco."
    assert stato.ultimo_ok == ieri and stato.ultimo_tentativo > ieri


def test_request_per_senza_superuser(s, servizi):
    azienda = s["azienda"]
    assert calcolo.request_per(azienda) is None
    assert calcolo.magazzino(azienda) == 0
    assert not PrevisioneArticolo.objects.exists() and servizi == []
    assert StatoCalcolo.objects.get(azienda=azienda, cosa="magazzino").errore == "nessun utente con cui calcolare"

    User.objects.create_superuser("spento", "spento@example.com", "x", is_active=False)
    User.objects.create_user("normale", "normale@example.com", "x")
    assert calcolo.request_per(azienda) is None
    primo = User.objects.create_superuser("primo", "primo@example.com", "x")
    User.objects.create_superuser("secondo", "secondo@example.com", "x")
    request = calcolo.request_per(azienda)
    assert request.user == primo and request.azienda == azienda


def test_notturno_salta_aziende_senza_modulo_o_magazzino(s, capo, servizi, monkeypatch):
    Azienda.objects.create(nome="Senza magazzino")                   # né magazzini né movimenti
    _altra_azienda("Con l'app riservata ad altri")
    spenta = _altra_azienda("Spenta")
    spenta.attiva = False
    spenta.save()
    Modulo.objects.update_or_create(slug="previsioni", defaults={"nome": "Previsioni"})[0].aziende.add(s["azienda"], spenta)

    parametri.scrivi("previsioni.url_servizio", "")                   # servizio non configurato: niente
    calcolo.notturno()
    assert not PrevisioneArticolo.objects.exists() and not StatoCalcolo.objects.exists() and servizi == []

    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    installata = apps.is_installed
    monkeypatch.setattr(apps, "is_installed", lambda nome: nome != "magazzino" and installata(nome))
    calcolo.notturno()                                                # senza Magazzino: niente
    assert not PrevisioneArticolo.objects.exists() and not StatoCalcolo.objects.exists() and servizi == []
    monkeypatch.setattr(apps, "is_installed", installata)

    calcolo.notturno()
    assert set(PrevisioneArticolo.objects.values_list("azienda", flat=True)) == {s["azienda"].pk}
    assert list(StatoCalcolo.objects.values_list("azienda", flat=True)) == [s["azienda"].pk]
    assert len(servizi) == 1 and len(servizi[0]["series"]) == 2     # nessuna serie delle aziende escluse


def test_notturno_un_azienda_che_fallisce_non_ferma_le_altre(s, capo, servizi, monkeypatch):
    seconda = _altra_azienda("Seconda")
    chiamate = []

    def chiama(percorso, dati):
        chiamate.append(dati)
        if len(chiamate) == 1:
            raise RuntimeError("risposta imprevista")
        return _finta_risposta(dati)
    monkeypatch.setattr(servizio, "chiama", chiama)
    calcolo.notturno()
    assert set(PrevisioneArticolo.objects.values_list("azienda", flat=True)) == {seconda.pk}
    assert StatoCalcolo.objects.get(azienda=s["azienda"]).errore != ""
    assert StatoCalcolo.objects.get(azienda=seconda).errore == ""


def test_aggiorna_solo_con_permesso(s, capo, servizi, client):
    url = reverse("previsioni:aggiorna") + "?cosa=magazzino"
    norma = User.objects.create_user("norma", "norma@example.com", "x")
    norma.profilo.aziende.set([s["azienda"]])
    client.force_login(norma)
    assert client.post(url).status_code == 403
    assert not Lavoro.objects.filter(funzione="previsioni.calcolo.aggiorna").exists()

    norma.user_permissions.add(Permission.objects.get(codename="change_previsionearticolo"))
    assert client.get(url).status_code == 405
    assert client.post(reverse("previsioni:aggiorna") + "?cosa=vendite").status_code == 400
    assert not Lavoro.objects.filter(funzione="previsioni.calcolo.aggiorna").exists()

    with override_settings(LAVORI_SINCRONI=True):
        risposta = client.post(url, HTTP_REFERER="http://testserver/magazzino/giacenze/")
    assert risposta.status_code == 302 and risposta.url == "http://testserver/magazzino/giacenze/"
    assert "Aggiornamento avviato: le previsioni saranno pronte tra poco." in [str(m) for m in get_messages(risposta.wsgi_request)]
    lavoro = Lavoro.objects.get(funzione="previsioni.calcolo.aggiorna")
    assert lavoro.argomenti == {"azienda_id": s["azienda"].pk, "cosa": "magazzino"}
    assert (lavoro.azienda, lavoro.utente, lavoro.max_tentativi, lavoro.stato) == (s["azienda"], norma, 1, Lavoro.FATTO)
    assert PrevisioneArticolo.objects.filter(azienda=s["azienda"]).count() == 2

    risposta = client.post(url, HTTP_REFERER="https://altro.example.com/")      # da fuori: alla pagina iniziale
    assert risposta.status_code == 302 and risposta.url == reverse("core:home")
