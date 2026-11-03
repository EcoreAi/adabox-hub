"""Contratti ricorrenti: periodi, fatture una volta sola, rinnovi, disdette, ISTAT, pagine."""
import datetime
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command

import fiscale
from contatti.models import Contatto
from core.models import Azienda
from fatturazione.models import Fattura
from fiscale.models import AliquotaIva
from ricorrenti import operazioni
from ricorrenti.models import Canone, FatturaCanone, RigaCanone, piu_mesi

G = datetime.date


def _oggi(giorno):
    return mock.patch("django.utils.timezone.localdate", return_value=giorno)


@pytest.fixture
def scena(db):
    call_command("loaddata", str(Path(fiscale.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", partita_iva="12345678903", cliente=True, email="rossi@example.com",
                                      indirizzo="Via Po 2", cap="20100", citta="Milano", provincia="MI")
    capo = User.objects.create_user("capo", "capo@example.com", "x")
    return {"azienda": azienda, "cliente": cliente, "capo": capo}


def _contratto(s, inizio=G(2026, 1, 1), periodicita=1, attiva_il=None, prezzo=100, **extra):
    extra.setdefault("responsabile", s["capo"])
    c = Canone.objects.create(azienda=s["azienda"], cliente=s["cliente"], numero="CT/1", nome="Manutenzione", inizio=inizio,
                              periodicita=periodicita, **extra)
    RigaCanone.objects.create(canone=c, descrizione="Canone", prezzo=D(prezzo), aliquota=AliquotaIva.objects.get(codice="22"))
    c.ricalcola()
    with _oggi(attiva_il or inizio):
        operazioni.attiva(c)
    c.refresh_from_db()
    return c


def _giro(giorno):
    with _oggi(giorno):
        return operazioni.giro()


def test_periodi_contati_dall_inizio_senza_slittare(scena):
    c = Canone(inizio=G(2026, 1, 31), periodicita=1)
    assert c.dopo(G(2026, 1, 31)) == G(2026, 2, 28)
    assert c.dopo(G(2026, 2, 28)) == G(2026, 3, 31)
    assert c.fine_periodo(G(2026, 2, 28)) == G(2026, 3, 30)
    assert c.periodo_che_contiene(G(2026, 2, 15)) == G(2026, 1, 31)
    assert c.allineato(G(2026, 2, 28)) and not c.allineato(G(2026, 2, 27))


def test_bozza_non_fattura_e_senza_righe_non_si_attiva(scena):
    c = Canone.objects.create(azienda=scena["azienda"], cliente=scena["cliente"], nome="Vuoto", inizio=G(2026, 1, 1))
    assert _giro(G(2026, 6, 1)) == 0
    with pytest.raises(ValidationError):
        operazioni.attiva(c)


def test_attivazione_non_fattura_il_passato(scena):
    c = _contratto(scena, attiva_il=G(2026, 5, 20))
    assert c.prossimo_periodo == G(2026, 5, 1)
    assert _giro(G(2026, 5, 20)) == 1
    assert list(c.fatturati.values_list("dal", flat=True)) == [G(2026, 5, 1)]


def test_una_fattura_per_periodo_anche_ripetendo_il_giro(scena):
    c = _contratto(scena)
    assert _giro(G(2026, 1, 1)) == 1
    assert _giro(G(2026, 1, 1)) == 0
    assert _giro(G(2026, 1, 31)) == 0
    fattura = c.fatturati.get().fattura
    assert fattura.stato == Fattura.BOZZA and fattura.imponibile == D(100)
    assert fattura.rif_tipo == "contratto" and fattura.rif_numero == "CT/1"
    assert "dal 01/01/2026 al 31/01/2026" in fattura.righe.get().descrizione


def test_recupera_i_periodi_persi_se_il_worker_era_fermo(scena):
    c = _contratto(scena)
    assert _giro(G(2026, 3, 15)) == 3
    assert c.fatturati.count() == 3


def test_posticipata_a_fine_periodo(scena):
    _contratto(scena, anticipata=False, periodicita=3)
    assert _giro(G(2026, 3, 30)) == 0
    assert _giro(G(2026, 3, 31)) == 1


def test_massimo_per_giro(scena):
    c = _contratto(scena)
    with mock.patch.object(operazioni, "MAX_PER_GIRO", 2):
        assert _giro(G(2026, 6, 1)) == 2
    assert c.fatturati.count() == 2


def test_emissione_automatica_e_invio(scena, django_capture_on_commit_callbacks):
    _contratto(scena, emissione_automatica=True, invio_automatico=True)
    with mock.patch("ricorrenti.operazioni.lavori.accoda") as accoda:
        _giro(G(2026, 1, 1))
    fattura = FatturaCanone.objects.get().fattura
    assert fattura.stato == Fattura.EMESSA and fattura.numero
    accoda.assert_called_once_with("fatturazione.lavori.invia", fattura_id=fattura.pk)


def test_emissione_impossibile_resta_in_bozza_e_non_ferma_gli_altri(scena):
    senza = Contatto.objects.create(azienda=scena["azienda"], nome="Senza dati", cliente=True)
    c = _contratto(scena, emissione_automatica=True)
    Canone.objects.filter(pk=c.pk).update(cliente=senza)
    altro = _contratto(scena)
    assert _giro(G(2026, 1, 1)) == 2
    assert c.fatturati.get().fattura.stato == Fattura.BOZZA
    assert altro.fatturati.count() == 1


def test_rinnovo_tacito_solo_quando_il_nuovo_termine_comincia(scena):
    c = _contratto(scena, periodicita=12, durata_mesi=12)
    assert c.scadenza == G(2026, 12, 31)
    _giro(G(2026, 1, 1))
    _giro(G(2026, 6, 1))
    c.refresh_from_db()
    assert c.scadenza == G(2026, 12, 31)      # fatturato l'anno, ma il rinnovo non è ancora scattato: si può disdire
    _giro(G(2027, 1, 1))
    c.refresh_from_db()
    assert c.scadenza == G(2027, 12, 31) and c.fatturati.count() == 2


def test_senza_rinnovo_si_conclude(scena):
    c = _contratto(scena, periodicita=12, durata_mesi=12, rinnovo_tacito=False)
    _giro(G(2026, 1, 1))
    _giro(G(2027, 1, 1))
    c.refresh_from_db()
    assert c.stato == Canone.CONCLUSO and c.fatturati.count() == 1


def test_disdetta_in_tempo_vale_alla_scadenza(scena):
    c = _contratto(scena, durata_mesi=12, preavviso_giorni=60)
    assert operazioni.disdici(c, giorno=G(2026, 11, 1)) == G(2026, 12, 31)
    _giro(G(2026, 12, 31))
    assert c.fatturati.count() == 12
    _giro(G(2027, 1, 1))
    c.refresh_from_db()
    assert c.stato == Canone.CONCLUSO and c.fatturati.count() == 12


def test_disdetta_oltre_il_preavviso_vale_al_termine_dopo(scena):
    c = _contratto(scena, durata_mesi=12, preavviso_giorni=60)
    assert operazioni.disdici(c, giorno=G(2026, 11, 15)) == G(2027, 12, 31)
    _giro(G(2027, 2, 1))
    c.refresh_from_db()
    assert c.stato == Canone.DISDETTO and c.scadenza == G(2027, 12, 31)
    _giro(G(2028, 1, 1))
    c.refresh_from_db()
    assert c.stato == Canone.CONCLUSO and c.fatturati.count() == 24


def test_disdetta_senza_scadenza_e_revoca(scena):
    c = _contratto(scena, durata_mesi=0, preavviso_giorni=30)
    assert c.scadenza is None
    assert operazioni.disdici(c, giorno=G(2026, 3, 10)) == G(2026, 4, 30)
    operazioni.revoca_disdetta(c)
    c.refresh_from_db()
    assert c.stato == Canone.ATTIVO and c.cessa_il is None


def test_sospensione_non_fattura_i_mesi_fermi(scena):
    c = _contratto(scena)
    _giro(G(2026, 1, 1))
    operazioni.sospendi(c)
    assert _giro(G(2026, 4, 10)) == 0
    with _oggi(G(2026, 4, 10)):
        operazioni.riprendi(c)
    assert _giro(G(2026, 4, 10)) == 1
    assert list(c.fatturati.order_by("dal").values_list("dal", flat=True)) == [G(2026, 1, 1), G(2026, 4, 1)]


def test_periodo_annullato_si_rifa_e_quelli_validi_no(scena):
    c = _contratto(scena)
    _giro(G(2026, 2, 1))
    prima = c.fatturati.get(dal=G(2026, 1, 1)).fattura
    Fattura.objects.filter(pk=prima.pk).update(stato=Fattura.ANNULLATA)
    Canone.objects.filter(pk=c.pk).update(prossimo_periodo=G(2026, 1, 1))
    assert _giro(G(2026, 2, 1)) == 1
    assert c.fatturati.get(dal=G(2026, 1, 1)).fattura != prima
    assert c.fatturati.count() == 2
    c.refresh_from_db()
    assert c.prossimo_periodo == G(2026, 3, 1)


def test_bozza_eliminata_lo_dice_senza_ricrearla(scena):
    from core.models import Messaggio
    c = _contratto(scena)
    _giro(G(2026, 1, 1))
    c.fatturati.get().fattura.delete()
    assert _giro(G(2026, 1, 2)) == 0
    assert Messaggio.objects.filter(object_id=c.pk, corpo__contains="eliminata").exists()


def test_fattura_ora_in_anticipo_una_volta(scena):
    c = _contratto(scena)
    fattura = operazioni.fattura_prossimo(c)
    assert fattura.stato == Fattura.BOZZA
    assert _giro(G(2026, 1, 1)) == 0
    assert c.fatturati.count() == 1


def test_avviso_scadenza_una_volta(scena):
    c = _contratto(scena, durata_mesi=12, preavviso_giorni=60)
    _giro(G(2026, 9, 30))
    assert len(mail.outbox) == 0
    _giro(G(2026, 10, 2))
    _giro(G(2026, 10, 3))
    assert len(mail.outbox) == 1
    assert "01/11/2026" in mail.outbox[0].body and c.numero in mail.outbox[0].subject
    assert mail.outbox[0].to == ["capo@example.com"]


def test_adeguamento_istat_una_volta_al_giorno(scena):
    c = _contratto(scena)
    with _oggi(G(2026, 6, 1)):
        operazioni.adegua(c, D("1.5"))
        with pytest.raises(ValidationError):
            operazioni.adegua(c, D("1.5"))
        with pytest.raises(ValidationError):
            operazioni.adegua(c, D("0"), giorno=G(2026, 6, 2))
    c.refresh_from_db()
    assert c.imponibile == D("101.50")
    _giro(G(2026, 6, 1))
    assert c.fatturati.order_by("-dal").first().fattura.imponibile == D("101.50")


def test_previsione_rispetta_la_fine(scena):
    c = _contratto(scena, durata_mesi=12, rinnovo_tacito=False, attiva_il=G(2026, 11, 1))
    colonne = dict(operazioni.previsione([c], 4, G(2026, 11, 1)))
    assert colonne[G(2026, 11, 1)] == D(100) and colonne[G(2026, 12, 1)] == D(100)
    assert colonne[G(2027, 1, 1)] == 0


def test_validazioni_del_modello(scena):
    c = _contratto(scena, periodicita=3, durata_mesi=12)
    c.durata_mesi = 10
    with pytest.raises(ValidationError):
        c.full_clean()
    c.durata_mesi = 12
    c.periodicita = 1
    with pytest.raises(ValidationError):
        c.full_clean()
    c.periodicita = 3
    c.prossimo_periodo = G(2026, 2, 1)
    with pytest.raises(ValidationError):
        c.full_clean()


def test_pagine_e_permessi(scena, client):
    admin = User.objects.create_superuser("root", "root@example.com", "x")
    c = _contratto(scena, attiva_il=G(2026, 1, 1), adeguamento_istat=True)
    _giro(G(2026, 1, 1))
    client.force_login(scena["capo"])
    assert client.get("/ricorrenti/cruscotto/").status_code == 403
    assert client.get("/ricorrenti/adeguamento/").status_code == 403
    client.force_login(admin)
    pagina = client.get("/ricorrenti/cruscotto/")
    assert pagina.status_code == 200 and "Ricavi ricorrenti" in pagina.content.decode()
    assert client.get("/ricorrenti/adeguamento/").status_code == 200
    dettaglio = client.get(f"/ricorrenti/canoni/{c.pk}/")
    assert dettaglio.status_code == 200 and "Periodi fatturati" in dettaglio.content.decode()
    client.post("/ricorrenti/adeguamento/", {"percentuale": "NaN", "canone": [c.pk]})
    risposta = client.post("/ricorrenti/adeguamento/", {"percentuale": "2,5", "canone": [c.pk]})
    assert risposta.status_code == 302
    c.refresh_from_db()
    assert c.imponibile == D("102.50")


def test_piu_mesi():
    assert piu_mesi(G(2026, 12, 31), 2) == G(2027, 2, 28)
