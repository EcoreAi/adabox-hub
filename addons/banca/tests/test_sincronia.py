"""Lettura automatica dei conti (PSD2): consenso con GoCardless (server finto), conto trovato per IBAN, movimenti senza
doppioni a ogni giro, saldo, consenso scaduto, errori che non fermano gli altri conti, pagine e simulato."""
import datetime
import json

import httpx2 as httpx
import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from banca import sincronia
from banca.models import Aggregatore, CollegamentoConto, Conto, Importazione, MovimentoBanca
from core import cifratura
from core.models import Azienda

IBAN = "IT60X0542811101000000123456"
OGGI = timezone.localdate()


class FintoGoCardless:
    def __init__(self):
        self.richieste, self.transazioni, self.stato_richiesta, self.errore = [], [], "LN", None

    def __call__(self, r):
        self.richieste.append(r)
        p = r.url.path.removeprefix("/api/v2")
        if self.errore and p.startswith("/accounts/") and p.endswith("/transactions/"):
            return httpx.Response(self.errore, json={"summary": "Access has expired", "detail": "EUA expired"})
        risposte = {
            "/token/new/": {"access": "TOK", "access_expires": 86400},
            "/institutions/": [{"id": "INTESA_SANPAOLO_BCITITMM", "name": "Intesa Sanpaolo", "bic": "BCITITMM", "transaction_total_days": "540"}],
            "/agreements/enduser/": {"id": "AGR1", "access_valid_for_days": 90},
            "/requisitions/": {"id": "REQ1", "link": "https://ob.gocardless.com/psd2/start/REQ1"},
            "/requisitions/REQ1/": {"id": "REQ1", "status": self.stato_richiesta, "accounts": ["ACC-ALTRO", "ACC1"]},
            "/accounts/ACC-ALTRO/details/": {"account": {"iban": "IT02A0301503200000003517230"}},
            "/accounts/ACC1/details/": {"account": {"iban": IBAN}},
            "/accounts/ACC1/transactions/": {"transactions": {"booked": self.transazioni, "pending": []}},
            "/accounts/ACC1/balances/": {"balances": [{"balanceAmount": {"amount": "5321.40", "currency": "EUR"}, "balanceType": "closingBooked",
                                                       "referenceDate": OGGI.isoformat()}]},
        }
        if p in risposte:
            return httpx.Response(200, json=risposte[p])
        return httpx.Response(404, json={"summary": "Not found"})


@pytest.fixture
def gc(monkeypatch):
    finto = FintoGoCardless()
    monkeypatch.setattr(sincronia, "HTTP", httpx.Client(transport=httpx.MockTransport(lambda r: finto(r))))
    return finto


@pytest.fixture
def s(db, settings):
    settings.SITO_URL = "https://hub.esempio.it"
    azienda = Azienda.objects.get(pk=1)
    conto = Conto.objects.create(azienda=azienda, nome="Principale", iban=IBAN)
    ag = Aggregatore.objects.create(azienda=azienda, secret_id="sid", secret_key_cifrata=cifratura.cifra("skey"))
    return {"azienda": azienda, "conto": conto, "ag": ag}


def _t(id_, importo, giorni_fa=1, **extra):
    return {"transactionId": id_, "bookingDate": (OGGI - datetime.timedelta(days=giorni_fa)).isoformat(),
            "transactionAmount": {"amount": importo, "currency": "EUR"}, **extra}


def test_consenso_e_lettura_senza_doppioni(s, gc):
    c = sincronia.avvia(s["conto"], s["ag"], "INTESA_SANPAOLO_BCITITMM", "Intesa Sanpaolo")
    accordo = json.loads(next(r for r in gc.richieste if r.url.path.endswith("/agreements/enduser/")).content)
    assert accordo["access_scope"] == ["balances", "details", "transactions"]
    richiesta = json.loads(next(r for r in gc.richieste if r.url.path.endswith("/requisitions/")).content)
    assert richiesta["redirect"] == f"https://hub.esempio.it/banca/collegamento/{c.pk}/ritorno/"
    assert c.link_consenso.startswith("https://ob.gocardless.com/") and c.stato == "in_attesa"
    sincronia.completa(c)
    assert c.stato == "attivo" and c.conto_esterno == "ACC1"                      # quello con il nostro IBAN
    gc.transazioni = [_t("T1", "122.00", debtorName="Rossi Srl", debtorAccount={"iban": "IT02 A030 1503 2000 0000 3517 230"},
                         remittanceInformationUnstructured="Saldo fattura 12/2026"),
                      _t("T2", "-45.10", creditorName="Enel", remittanceInformationUnstructuredArray=["Bolletta", "ottobre"]),
                      {"transactionId": "T3", "transactionAmount": {"amount": "x"}}]
    esito = sincronia.leggi(c)
    assert esito.nuovi == 2 and esito.scartati == 1 and esito.formato == "psd2"
    entrata = MovimentoBanca.objects.get(importo="122.00")
    assert entrata.controparte == "Rossi Srl" and entrata.iban_controparte == "IT02A0301503200000003517230" and entrata.riferimento == "T1"
    assert MovimentoBanca.objects.get(importo="-45.10").descrizione == "Bolletta ottobre"
    s["conto"].refresh_from_db()
    assert str(s["conto"].saldo) == "5321.40"
    gc.transazioni = gc.transazioni[:2] + [_t("T4", "10.00", 0)]                     # giro dopo: solo il nuovo
    esito = sincronia.leggi(c)
    assert esito.nuovi == 1 and esito.doppi == 2 and MovimentoBanca.objects.count() == 3
    data_from = [r.url.params.get("date_from") for r in gc.richieste if r.url.path.endswith("/transactions/")][-1]
    assert data_from == (OGGI - datetime.timedelta(days=sincronia.SOVRAPPOSIZIONE)).isoformat()
    gc.transazioni = gc.transazioni[:1]                                             # niente di nuovo: nessuna riga in Importazioni
    prima = Importazione.objects.count()
    sincronia.leggi(c)
    assert Importazione.objects.count() == prima


def test_consenso_negato_o_conto_assente(s, gc):
    c = sincronia.avvia(s["conto"], s["ag"], "INTESA_SANPAOLO_BCITITMM")
    gc.stato_richiesta = "RJ"
    with pytest.raises(sincronia.ErroreBanca, match="consenso"):
        sincronia.completa(c)
    gc.stato_richiesta = "LN"
    s["conto"].iban = "IT60X0542811101000000654321"
    s["conto"].save()
    c.refresh_from_db()
    with pytest.raises(sincronia.ErroreBanca, match="non c'è"):
        sincronia.completa(c)


def test_scaduto_e_giro(s, gc):
    c = sincronia.completa(sincronia.avvia(s["conto"], s["ag"], "INTESA_SANPAOLO_BCITITMM"))
    altro = Conto.objects.create(azienda=s["azienda"], nome="Simulato", iban="IT02A0301503200000003517230")
    finto = Aggregatore.objects.create(azienda=s["azienda"], tipo="finto", nome="Simulato")
    sincronia.completa(sincronia.avvia(altro, finto, "FINTA_BANCA_IT"))
    gc.errore = 401
    assert sincronia.giro() == 1                                                   # il conto in errore non ferma l'altro
    c.refresh_from_db()
    assert c.stato == "scaduto" and "EUA" in c.errore and MovimentoBanca.objects.filter(conto=altro).count() == 1
    assert list(sincronia.in_scadenza(s["azienda"])) == [c]
    attivo = CollegamentoConto.objects.get(conto=altro)
    attivo.scade_il = OGGI - datetime.timedelta(days=1)
    attivo.save()
    assert sincronia.leggi(attivo) is None and CollegamentoConto.objects.get(conto=altro).stato == "scaduto"


def test_pagine_con_il_simulato(client, s):
    s["ag"].tipo = "finto"
    s["ag"].save()
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(reverse("banca:conti_dettaglio", args=[s["conto"].pk])).content.decode()
    assert "Collega alla banca" in html
    assert "Banca Simulata" in client.get(reverse("banca:collega", args=[s["conto"].pk])).content.decode()
    r = client.post(reverse("banca:collega", args=[s["conto"].pk]), {"istituto": "FINTA_BANCA_IT"})
    assert r.status_code == 302 and "/ritorno/" in r.url
    r = client.get(r.url.replace("https://hub.esempio.it", ""))
    assert r.status_code == 302 and MovimentoBanca.objects.filter(conto=s["conto"]).count() == 1
    c = CollegamentoConto.objects.get()
    assert c.stato == "attivo" and c.nome_istituto == "Banca Simulata"
    html = client.get(reverse("banca:conti_dettaglio", args=[s["conto"].pk])).content.decode()
    assert "Leggi adesso" in html and "Rinnova il consenso" in html
    assert client.post(reverse("banca:collega_leggi", args=[c.pk])).status_code == 302
    assert MovimentoBanca.objects.count() == 1                                      # stesso movimento: nessun doppione
    assert client.post(reverse("banca:collega", args=[s["conto"].pk]), {"istituto": "INVENTATA"}).status_code == 302
    client.post(reverse("banca:scollega", args=[c.pk]))
    assert not CollegamentoConto.objects.exists() and MovimentoBanca.objects.count() == 1


def test_servizio_e_chiavi(client, s, gc):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    Aggregatore.objects.all().delete()
    r = client.post(reverse("banca:aggregatori_nuovo"), {"nome": "GoCardless", "tipo": "gocardless", "secret_id": "sid", "attivo": "on"})
    assert r.status_code == 200 and not Aggregatore.objects.exists()               # manca la Secret Key
    client.post(reverse("banca:aggregatori_nuovo"), {"nome": "GoCardless", "tipo": "gocardless", "secret_id": "sid", "attivo": "on",
                                                     "nuova_chiave": "skey"})
    ag = Aggregatore.objects.get()
    assert ag.secret_key() == "skey" and "skey" not in client.get(reverse("banca:aggregatori_dettaglio", args=[ag.pk])).content.decode()
    r = client.post(reverse("banca:aggregatori_bottone", args=[ag.pk, "prova"]), follow=True)
    assert "1 banche italiane" in r.content.decode()
