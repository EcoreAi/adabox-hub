"""Listini, condizioni, approvazioni, contratti, gare: le regole del ciclo dell'ordine."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.utils import timezone

import fiscale
import prodotti
from acquisti import listini, operazioni
from acquisti.models import (Approvazione, CondizioniFornitore, ContrattoQuadro, Gara, OrdineAcquisto, RegolaApprovazione,
                             RigaAcquisto, RigaContratto, RigaGara, VoceListino)
from contatti.models import Contatto
from core.models import Azienda
from fiscale.models import AliquotaIva, TerminePagamento
from prodotti.models import Categoria, Prodotto


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Grossista Spa", fornitore=True, email="ordini@grossista.it")
    altro = Contatto.objects.create(azienda=azienda, nome="Concorrente Srl", fornitore=True, email="vendite@concorrente.it")
    toner = Prodotto.objects.create(azienda=azienda, nome="Toner", costo=Decimal("38"), prezzo_vendita=Decimal("64"))
    return azienda, fornitore, altro, toner


def _ordine(azienda, fornitore, prodotto, quantita=10, prezzo=None, **campi):
    o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero=campi.pop("numero", "OA/T/1"), **campi)
    RigaAcquisto.objects.create(ordine=o, prodotto=prodotto, quantita=quantita, prezzo=prezzo)
    o.ricalcola()
    return o


def _persona(nome, *gruppi):
    u = User.objects.create_user(nome, f"{nome}@example.com", "pass12345!")
    for g in gruppi:
        u.groups.add(Group.objects.get_or_create(name=g)[0])
    return u


# --- listini

def test_scaglione_del_listino_decide_prezzo_e_codice(scena):
    azienda, fornitore, _, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("30"),
                               quantita_minima=1, codice_fornitore="GR-1")
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("25"),
                               quantita_minima=50, codice_fornitore="GR-1")
    piccolo = _ordine(azienda, fornitore, toner, 10)
    grande = _ordine(azienda, fornitore, toner, 50, numero="OA/T/2")
    assert piccolo.righe.get().prezzo == Decimal("30") and piccolo.righe.get().codice_fornitore == "GR-1"
    assert grande.righe.get().prezzo == Decimal("25")


def test_listino_scaduto_o_di_altri_non_vale(scena):
    azienda, fornitore, altro, toner = scena
    ieri = timezone.localdate() - datetime.timedelta(days=1)
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("1"), valido_al=ieri)
    VoceListino.objects.create(azienda=azienda, fornitore=altro, prodotto=toner, prezzo=Decimal("2"))
    assert _ordine(azienda, fornitore, toner).righe.get().prezzo == Decimal("38")          # il costo del prodotto


def test_il_prezzo_scritto_a_mano_vince_sul_listino(scena):
    azienda, fornitore, _, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("30"))
    assert _ordine(azienda, fornitore, toner, prezzo=Decimal("12")).righe.get().prezzo == Decimal("12")


def test_scelta_del_fornitore_preferito_poi_meno_caro_e_minimo(scena):
    azienda, fornitore, altro, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("30"))
    VoceListino.objects.create(azienda=azienda, fornitore=altro, prodotto=toner, prezzo=Decimal("20"), quantita_minima=12)
    voce, quantita = listini.scegli_fornitore(toner, Decimal(5))
    # 20 € × 12 = 240 è più di 30 € × 5 = 150: conta la spesa vera, minimo compreso
    assert voce.fornitore == fornitore and quantita == 5
    VoceListino.objects.filter(fornitore=altro).update(preferito=True)
    voce, quantita = listini.scegli_fornitore(toner, Decimal(5))
    assert voce.fornitore == altro and quantita == 12


def test_avviso_sotto_il_minimo(client, superuser, scena):
    azienda, fornitore, _, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("30"), quantita_minima=20)
    o = _ordine(azienda, fornitore, toner, 5)
    assert "il minimo d'ordine del fornitore è 20" in client.get(f"/acquisti/ordini/{o.pk}/").content.decode().replace("&#x27;", "'")


# --- condizioni del fornitore

def test_condizioni_proposte_sul_nuovo_ordine(client, superuser, scena):
    azienda, fornitore, _, toner = scena
    termine = TerminePagamento.objects.first()
    esente = AliquotaIva.objects.exclude(codice="22").first()
    CondizioniFornitore.objects.create(azienda=azienda, fornitore=fornitore, termine_pagamento=termine, aliquota=esente,
                                       giorni_consegna=10, iban="IT60 X054 2811 1010 0000 0123 456")
    assert CondizioniFornitore.objects.get().iban == "IT60X0542811101000000123456"
    oggi = timezone.localdate()
    dati = {"fornitore": fornitore.pk, "data": oggi.isoformat(), "righe0-TOTAL_FORMS": "1", "righe0-INITIAL_FORMS": "0",
            "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000", "righe0-0-prodotto": toner.pk,
            "righe0-0-quantita": "5", "righe0-0-sconto": "0"}
    assert client.post("/acquisti/ordini/nuovo/", dati).status_code == 302
    o = OrdineAcquisto.objects.get()
    assert o.termine_pagamento == termine and o.consegna_prevista == oggi + datetime.timedelta(days=10)
    assert o.righe.get().aliquota == esente


def test_iban_sbagliato_rifiutato(scena):
    azienda, fornitore, _, _ = scena
    with pytest.raises(ValidationError):
        CondizioniFornitore(azienda=azienda, fornitore=fornitore, iban="IT00X0000000000000000000000").full_clean()


# --- approvazioni

@pytest.fixture
def regola(scena):
    azienda, *_ = scena
    capo = _persona("capo")
    r = RegolaApprovazione.objects.create(azienda=azienda, nome="Oltre 100 €", soglia=Decimal("100"))
    r.approvatori.add(capo)
    return r, capo


def test_senza_regole_si_conferma_subito(scena):
    azienda, fornitore, _, toner = scena
    o = _ordine(azienda, fornitore, toner)
    assert operazioni.conferma(o) is True
    o.refresh_from_db()
    assert o.stato == OrdineAcquisto.CONFERMATO


def test_sotto_soglia_non_serve_approvare(scena, regola):
    azienda, fornitore, _, toner = scena
    assert operazioni.conferma(_ordine(azienda, fornitore, toner, 1)) is True


def test_sopra_soglia_serve_approvare_e_il_magazzino_aspetta(scena, regola):
    from magazzino.models import Ricevimento
    azienda, fornitore, _, toner = scena
    _, capo = regola
    o = _ordine(azienda, fornitore, toner)
    assert operazioni.conferma(o) is False
    o.refresh_from_db()
    assert o.stato == OrdineAcquisto.DA_APPROVARE and not o.modificabile
    assert not Ricevimento.objects.exists() and o.confermato_il is None
    assert operazioni.approva(o, capo) is True
    o.refresh_from_db()
    assert o.stato == OrdineAcquisto.CONFERMATO and Ricevimento.objects.count() == 1
    a = o.approvazioni.get()
    assert a.esito == Approvazione.APPROVATA and a.decisa_da == capo and a.imponibile == o.imponibile


def test_regola_per_categoria(scena):
    azienda, fornitore, _, toner = scena
    categoria = Categoria.objects.create(nome="Ricambi critici")
    RegolaApprovazione.objects.create(azienda=azienda, nome="Critici", categoria=categoria)
    assert operazioni.conferma(_ordine(azienda, fornitore, toner, numero="OA/T/1")) is True
    Prodotto.objects.filter(pk=toner.pk).update(categoria=categoria)
    assert operazioni.conferma(_ordine(azienda, fornitore, toner, numero="OA/T/2")) is False


def test_due_livelli_in_ordine_e_avviso_al_secondo_solo_dopo_il_primo(scena):
    from core import attivita
    azienda, fornitore, _, toner = scena
    primo, secondo = _persona("primo"), _persona("secondo")
    r1 = RegolaApprovazione.objects.create(azienda=azienda, nome="Responsabile", livello=1)
    r2 = RegolaApprovazione.objects.create(azienda=azienda, nome="Direzione", livello=2)
    r1.approvatori.add(primo)
    r2.approvatori.add(secondo)
    o = _ordine(azienda, fornitore, toner)
    operazioni.conferma(o)
    assert [a.assegnatario for a in attivita.di(o)] == [primo]
    with pytest.raises(PermissionDenied):
        operazioni.approva(o, secondo)
    assert operazioni.approva(o, primo) is False
    assert [a.assegnatario for a in attivita.di(o)] == [secondo]
    with pytest.raises(PermissionDenied):
        operazioni.approva(o, primo)
    assert operazioni.approva(o, secondo) is True
    assert not attivita.di(o).exists()


@pytest.mark.parametrize("ruolo", ["buyer", "richiedente"])
def test_chi_compra_non_si_approva_da_solo(scena, ruolo):
    azienda, fornitore, _, toner = scena
    persona = _persona("mario")
    r = RegolaApprovazione.objects.create(azienda=azienda, nome="Sempre")
    r.approvatori.add(persona)
    o = _ordine(azienda, fornitore, toner, buyer=persona if ruolo == "buyer" else None)
    operazioni.conferma(o, persona)
    with pytest.raises(PermissionDenied):
        operazioni.approva(o, persona)


def test_estraneo_non_approva_neppure_via_http(client, scena, regola):
    from django.contrib.auth.models import Permission
    azienda, fornitore, _, toner = scena
    o = _ordine(azienda, fornitore, toner)
    operazioni.conferma(o)
    u = _persona("curioso")
    u.user_permissions.add(Permission.objects.get(codename="view_ordineacquisto"))
    u.profilo.aziende.add(azienda)
    client.force_login(u)
    assert client.post(f"/acquisti/ordini/{o.pk}/bottone/approva/").status_code == 403
    o.refresh_from_db()
    assert o.stato == OrdineAcquisto.DA_APPROVARE
    assert "bottone/approva" not in client.get(f"/acquisti/ordini/{o.pk}/").content.decode()


def test_rifiuto_torna_al_buyer_e_si_ripresenta_da_capo(scena, regola):
    azienda, fornitore, _, toner = scena
    _, capo = regola
    o = _ordine(azienda, fornitore, toner)
    operazioni.conferma(o)
    operazioni.rifiuta(o, capo)
    o.refresh_from_db()
    assert o.stato == OrdineAcquisto.BOZZA and o.modificabile
    assert operazioni.conferma(o) is False
    assert o.approvazioni.filter(esito=Approvazione.ATTESA).count() == 1
    assert o.approvazioni.filter(esito=Approvazione.SUPERATA).count() == 1


def test_gli_assistenti_non_approvano(scena):
    from acquisti.views import OrdineAcquistoView
    assert OrdineAcquistoView.approva.ai is False and OrdineAcquistoView.rifiuta.ai is False


def test_annullo_chiude_le_approvazioni(scena, regola):
    from core import attivita
    azienda, fornitore, _, toner = scena
    o = _ordine(azienda, fornitore, toner)
    operazioni.conferma(o)
    operazioni.annulla(o)
    assert not o.approvazioni.filter(esito=Approvazione.ATTESA).exists() and not attivita.di(o).exists()


def test_doppia_conferma_non_crea_due_ricevimenti(scena):
    from magazzino.models import Ricevimento
    azienda, fornitore, _, toner = scena
    o = _ordine(azienda, fornitore, toner)
    copia = OrdineAcquisto.objects.get(pk=o.pk)
    operazioni.conferma(o)
    with pytest.raises(ValidationError):
        operazioni.conferma(copia)                     # la copia è vecchia: lo stato si rilegge dal database
    assert Ricevimento.objects.count() == 1


# --- contratti quadro

@pytest.fixture
def contratto(scena):
    azienda, fornitore, _, toner = scena
    c = ContrattoQuadro.objects.create(azienda=azienda, fornitore=fornitore)
    RigaContratto.objects.create(contratto=c, prodotto=toner, prezzo=Decimal("20"), quantita=Decimal("100"))
    operazioni.attiva_contratto(c)
    return c


def test_numero_e_richiamo_col_residuo_al_prezzo_concordato(scena, contratto):
    assert contratto.numero.startswith("CQ/")
    o = operazioni.richiamo(contratto)
    riga = o.righe.get()
    assert (riga.prezzo, riga.quantita) == (Decimal("20"), Decimal("100")) and o.contratto == contratto
    assert o.stato == OrdineAcquisto.BOZZA


def test_prezzo_del_contratto_vince_sul_listino(scena, contratto):
    azienda, fornitore, _, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("30"))
    assert _ordine(azienda, fornitore, toner, contratto=contratto).righe.get().prezzo == Decimal("20")


def test_il_residuo_scende_e_non_si_supera(scena, contratto):
    azienda, fornitore, _, toner = scena
    operazioni.conferma(_ordine(azienda, fornitore, toner, 80, contratto=contratto, numero="A"))
    assert operazioni.residui_contratto(contratto)[0]["residuo"] == Decimal("20")
    troppo = _ordine(azienda, fornitore, toner, 21, contratto=contratto, numero="B")
    with pytest.raises(ValidationError, match="residuo 20"):
        operazioni.conferma(troppo)
    assert operazioni.conferma(_ordine(azienda, fornitore, toner, 20, contratto=contratto, numero="C")) is True
    with pytest.raises(ValidationError, match="per intero"):
        operazioni.richiamo(contratto)


def test_annullare_un_richiamo_libera_il_residuo(scena, contratto):
    azienda, fornitore, _, toner = scena
    o = _ordine(azienda, fornitore, toner, 80, contratto=contratto)
    operazioni.conferma(o)
    operazioni.annulla(o)
    assert operazioni.residui_contratto(contratto)[0]["residuo"] == Decimal("100")


def test_contratto_scaduto_o_chiuso_non_conferma(scena, contratto):
    azienda, fornitore, _, toner = scena
    o = _ordine(azienda, fornitore, toner, 1, contratto=contratto)
    ContrattoQuadro.objects.filter(pk=contratto.pk).update(al=timezone.localdate() - datetime.timedelta(days=1))
    with pytest.raises(ValidationError, match="in vigore"):
        operazioni.conferma(o)
    operazioni.chiudi_contratto(ContrattoQuadro.objects.get(pk=contratto.pk))
    with pytest.raises(ValidationError, match="non è attivo"):
        operazioni.conferma(o)


def test_contratto_di_un_altro_fornitore_rifiutato(scena, contratto):
    azienda, _, altro, _ = scena
    with pytest.raises(ValidationError):
        OrdineAcquisto(azienda=azienda, fornitore=altro, contratto=contratto).clean()


def test_contratto_senza_limite_di_quantita(scena):
    azienda, fornitore, _, toner = scena
    c = ContrattoQuadro.objects.create(azienda=azienda, fornitore=fornitore)
    RigaContratto.objects.create(contratto=c, prodotto=toner, prezzo=Decimal("20"))
    operazioni.attiva_contratto(c)
    assert operazioni.conferma(_ordine(azienda, fornitore, toner, 5000, contratto=c)) is True


def test_viste_del_contratto(client, superuser, scena):
    azienda, fornitore, _, toner = scena
    dati = {"fornitore": fornitore.pk, "dal": timezone.localdate().isoformat(), "righe0-TOTAL_FORMS": "1",
            "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000",
            "righe0-0-prodotto": toner.pk, "righe0-0-prezzo": "20", "righe0-0-quantita": "100"}
    assert client.post("/acquisti/contratti/nuovo/", dati).status_code == 302
    c = ContrattoQuadro.objects.get()
    client.post(f"/acquisti/contratti/{c.pk}/bottone/attiva/")
    r = client.post(f"/acquisti/contratti/{c.pk}/bottone/richiama/")
    assert r.status_code == 302 and "/acquisti/ordini/" in r.url
    pagina = client.get(f"/acquisti/contratti/{c.pk}/").content.decode()
    assert "Avanzamento del contratto" in pagina


# --- gare

@pytest.fixture
def gara(scena):
    azienda, fornitore, altro, toner = scena
    g = Gara.objects.create(azienda=azienda, titolo="Toner per il 2027")
    g.fornitori.add(fornitore, altro)
    RigaGara.objects.create(gara=g, prodotto=toner, quantita=Decimal("10"))
    return g


def test_una_richiesta_per_fornitore_senza_doppioni(scena, gara):
    assert operazioni.crea_offerte(gara) == 2
    assert operazioni.crea_offerte(gara) == 0
    assert gara.offerte.count() == 2 and gara.numero.startswith("GA/")


def test_invio_a_tutti_salta_chi_non_ha_email(scena, gara, mailoutbox):
    _, fornitore, altro, _ = scena
    Contatto.objects.filter(pk=altro.pk).update(email="")
    operazioni.crea_offerte(gara)
    inviate, senza = operazioni.invia_offerte(gara)
    assert inviate == 1 and senza == ["Concorrente Srl"] and mailoutbox[0].to == [fornitore.email]


def test_aggiudica_conferma_il_vincitore_e_annulla_gli_altri(scena, gara):
    from magazzino.models import Ricevimento
    _, fornitore, altro, _ = scena
    operazioni.crea_offerte(gara)
    vincente = gara.offerte.get(fornitore=altro)
    assert operazioni.aggiudica(gara, vincente) is True
    gara.refresh_from_db()
    vincente.refresh_from_db()
    assert gara.stato == Gara.AGGIUDICATA and gara.vincitore == vincente and vincente.stato == OrdineAcquisto.CONFERMATO
    assert gara.offerte.get(fornitore=fornitore).stato == OrdineAcquisto.ANNULLATO
    assert Ricevimento.objects.count() == 1


def test_confermare_dall_ordine_chiude_ugualmente_la_gara(scena, gara):
    _, fornitore, altro, _ = scena
    operazioni.crea_offerte(gara)
    operazioni.conferma(gara.offerte.get(fornitore=altro))
    gara.refresh_from_db()
    assert gara.stato == Gara.AGGIUDICATA and gara.offerte.get(fornitore=fornitore).stato == OrdineAcquisto.ANNULLATO


def test_aggiudica_con_approvazione_chiude_solo_a_decisione_presa(scena, gara, regola):
    _, fornitore, altro, _ = scena
    _, capo = regola
    operazioni.crea_offerte(gara)
    vincente = gara.offerte.get(fornitore=altro)
    assert operazioni.aggiudica(gara, vincente) is False
    gara.refresh_from_db()
    assert gara.stato == Gara.APERTA and gara.offerte.get(fornitore=fornitore).stato == OrdineAcquisto.BOZZA
    operazioni.rifiuta(vincente, capo)
    gara.refresh_from_db()
    assert gara.stato == Gara.APERTA and gara.vincitore is None      # rifiutata: si può scegliere ancora
    assert operazioni.aggiudica(gara, gara.offerte.get(fornitore=fornitore)) is False
    operazioni.approva(gara.offerte.get(fornitore=fornitore), capo)
    gara.refresh_from_db()
    assert gara.stato == Gara.AGGIUDICATA and gara.offerte.get(fornitore=altro).stato == OrdineAcquisto.ANNULLATO


def test_annulla_gara_e_confronto_in_pagina(client, superuser, scena, gara):
    _, fornitore, altro, _ = scena
    operazioni.crea_offerte(gara)
    RigaAcquisto.objects.filter(ordine__fornitore=altro).update(prezzo=Decimal("30"), importo=Decimal("300"))
    pagina = client.get(f"/acquisti/gare/{gara.pk}/").content.decode()
    assert "Confronto delle offerte" in pagina and "Concorrente Srl" in pagina and "<strong>30,00 €</strong>" in pagina
    r = client.post(f"/acquisti/gare/{gara.pk}/bottone/annulla_gara/")
    assert r.status_code == 302
    gara.refresh_from_db()
    assert gara.stato == Gara.ANNULLATA and not gara.offerte.exclude(stato=OrdineAcquisto.ANNULLATO).exists()


def test_aggiudica_offerta_di_un_altra_gara_non_si_puo(client, superuser, scena, gara):
    azienda, fornitore, _, toner = scena
    estraneo = _ordine(azienda, fornitore, toner)
    assert client.post(f"/acquisti/gare/{gara.pk}/aggiudica/{estraneo.pk}/").status_code == 404
