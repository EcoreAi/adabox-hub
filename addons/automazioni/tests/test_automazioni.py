"""Modelli delle email e regole: testi personalizzati, sicurezza dei segnaposto, eventi, tempo, doppioni, simulazione."""
import datetime
import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

import fiscale
import helpdesk
import prodotti
from automazioni import motore, ricette
from automazioni.models import Esecuzione, Regola
from contatti.models import Contatto
from core import modelli_email
from core.models import AttivitaPianificata, Azienda, Messaggio, ModelloEmail, TipoAttivita
from fatturazione import operazioni as fatture
from fatturazione.models import Fattura, RigaFattura
from fiscale.models import AliquotaIva, TerminePagamento
from helpdesk.models import FaseTicket, Ticket

OGGI = timezone.localdate()


@pytest.fixture
def scena(db):
    for app in (fiscale, prodotti, helpdesk):
        percorso = Path(app.__file__).parent / "data" / "iniziali.json"
        if percorso.exists():
            call_command("loaddata", str(percorso), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, partita_iva="01114601006", email="amm@rossi.it")
    return azienda, cliente


def _scaduta(azienda, cliente, giorni=10):
    termine, _ = TerminePagamento.objects.get_or_create(nome="Prova a vista", defaults={"rate": [{"giorni": 0, "percentuale": 100}]})
    f = Fattura.objects.create(azienda=azienda, cliente=cliente, termine_pagamento=termine, data=OGGI - datetime.timedelta(days=giorni))
    RigaFattura.objects.create(fattura=f, descrizione="Lavoro", prezzo=D(100), aliquota=AliquotaIva.objects.get(codice="22"))
    f.ricalcola()
    return fatture.emetti(f)


def _modello(azienda, dominio="fattura", codice="personale.a", oggetto="Sollecito {{ documento }}",
             corpo="Gentile {{ cliente }}, da pagare {{ importo_scadenza }} {{ link_interno }}"):
    return ModelloEmail.objects.create(azienda=azienda, codice=codice, nome="Prova", dominio=dominio, oggetto=oggetto, corpo=corpo)


def _regola(azienda, evento, azioni, **altri):
    return Regola.objects.create(azienda=azienda, nome="R", evento=evento, azioni=azioni, attiva=altri.pop("attiva", True), **altri)


# ---------- modelli delle email

def test_il_testo_dell_azienda_sostituisce_quello_del_modulo(scena):
    azienda, _ = scena
    email = modelli_email.messaggio("commesse.monte_ore", azienda, {"contratto": "C", "soglia": 80, "usate": 8, "incluse": 10}, ["a@b.it"])
    assert email.subject == "Monte ore al 80%: C" and "8 ore su 10" in email.body
    ModelloEmail.objects.create(azienda=azienda, codice="commesse.monte_ore", oggetto="Attenzione {{ contratto }}", corpo="Solo {{ usate }}")
    email = modelli_email.messaggio("commesse.monte_ore", azienda, {"contratto": "C", "soglia": 80, "usate": 8, "incluse": 10}, ["a@b.it"])
    assert email.subject == "Attenzione C" and email.body == "Solo 8"


def test_i_segnaposto_non_eseguono_nulla_e_i_valori_non_portano_markup(scena):
    azienda, _ = scena
    oggetto, testo, html = modelli_email.componi(
        "Ciao {{ nome }}\nBcc: x@y.it", "{% load x %}{{ nome.__class__ }} {{ nome }} {{ altro }} https://esempio.it/a",
        {"nome": "<script>{{ altro }}</script>", "altro": "valore"}, azienda)
    assert "\n" not in oggetto
    assert "{% load x %}" in testo and "{{ nome.__class__ }}" in testo    # non è il motore dei template
    assert "<script>{{ altro }}</script> valore" in testo                 # un solo passaggio
    assert "<script>" not in html and "&lt;script&gt;" in html and 'href="https://esempio.it/a"' in html


def test_errori_del_testo():
    problemi = modelli_email.errori("Ok", "{{ refuso }}", {"link": []}, ["link"])
    assert any("refuso" in p for p in problemi) and any("deve contenere" in p for p in problemi)
    assert modelli_email.errori("Ok", "{{ link }}", {"link": []}, ["link"]) == []


def test_pagine_dei_modelli_e_campi_obbligatori(client, superuser, scena):
    azienda, _ = scena
    assert client.get("/automazioni/modelli/").status_code == 200
    r = client.post("/automazioni/modelli/helpdesk.valutazione/", {"oggetto": "Voto", "corpo": "Senza il collegamento"})
    assert r.status_code == 200 and not ModelloEmail.objects.exists()
    client.post("/automazioni/modelli/helpdesk.valutazione/", {"oggetto": "Voto", "corpo": "Vota: {{ link }}"})
    assert ModelloEmail.objects.get(codice="helpdesk.valutazione", azienda=azienda).corpo == "Vota: {{ link }}"
    r = client.post("/automazioni/modelli/anteprima/", {"codice": "helpdesk.valutazione", "oggetto": "{{ numero }} {{ boh }}", "corpo": "<b>{{ link }}</b>"}).json()
    assert r["oggetto"].startswith("HD/") and r["sconosciuti"] == ["boh"] and "<b>" not in r["html"]
    client.post("/automazioni/modelli/helpdesk.valutazione/ripristina/")
    assert not ModelloEmail.objects.exists()


def test_la_prova_va_solo_a_chi_scrive(client, superuser, scena):
    superuser.email = "io@esempio.it"
    superuser.save()
    assert client.post("/automazioni/modelli/helpdesk.valutazione/prova/", {"codice": "helpdesk.valutazione", "oggetto": "P", "corpo": "T", "a": "altri@x.it"}).json()["ok"]
    assert mail.outbox[-1].to == ["io@esempio.it"]


def test_l_invio_fattura_usa_il_modello(client, superuser, scena):
    azienda, cliente = scena
    ModelloEmail.objects.create(azienda=azienda, codice="fatturazione.invio", oggetto="La sua {{ documento }}", corpo="Totale {{ totale }}")
    f = _scaduta(azienda, cliente)
    client.post(f"/fatturazione/fatture/{f.pk}/bottone/invia/")
    assert mail.outbox[-1].subject == f"La sua {f}" and "122,00 €" in mail.outbox[-1].body
    assert mail.outbox[-1].alternatives


# ---------- regole a tempo

def test_sollecito_una_volta_sola_e_mai_sulle_pagate(scena):
    azienda, cliente = scena
    _modello(azienda)
    f = _scaduta(azienda, cliente)
    pagata = _scaduta(azienda, cliente)
    fatture.incassa(pagata.scadenze.get())
    regola = _regola(azienda, "fattura.scaduta", [{"tipo": "email", "a": "cliente", "modello": "personale.a"}], giorni=7)
    prima = len(mail.outbox)
    assert [r[0].pk for r in motore.in_attesa(regola)] == [f.pk]
    for _ in range(2):
        for record, chiave, extra in motore.in_attesa(regola):
            motore.applica(regola, record, chiave, extra)
    assert len(mail.outbox) == prima + 1 and "122,00 €" in mail.outbox[-1].body and mail.outbox[-1].to == ["amm@rossi.it"]
    assert Esecuzione.objects.get().esito == Esecuzione.FATTA
    assert Messaggio.objects.filter(object_id=f.pk, corpo__contains="dalla regola").exists()
    assert motore.in_attesa(regola) == []


def test_giorni_non_ancora_passati(scena):
    azienda, cliente = scena
    _scaduta(azienda, cliente, giorni=3)
    regola = _regola(azienda, "fattura.scaduta", [{"tipo": "nota", "testo": "x"}], giorni=7)
    assert motore.in_attesa(regola) == []


def test_controlla_tempo_non_lavora_di_notte_se_non_urgente(scena, monkeypatch):
    azienda, cliente = scena
    _scaduta(azienda, cliente)
    regola = _regola(azienda, "fattura.scaduta", [{"tipo": "nota", "testo": "Nota {{ documento }}"}], giorni=7)
    notte = timezone.localtime().replace(hour=3)
    monkeypatch.setattr(motore.timezone, "localtime", lambda *a: notte)
    motore.controlla_tempo()
    assert not regola.esecuzioni.exists()
    giorno = notte.replace(hour=9)
    monkeypatch.setattr(motore.timezone, "localtime", lambda *a: giorno)
    motore.controlla_tempo()
    assert regola.esecuzioni.count() == 1


def test_tetto_per_giro(scena, monkeypatch):
    azienda, cliente = scena
    for _ in range(3):
        _scaduta(azienda, cliente)
    _regola(azienda, "fattura.scaduta", [{"tipo": "nota", "testo": "x"}], giorni=7)
    monkeypatch.setattr(motore, "MAX_PER_GIRO", 2)
    giorno = timezone.localtime().replace(hour=9)
    monkeypatch.setattr(motore.timezone, "localtime", lambda *a: giorno)
    motore.controlla_tempo()
    assert Esecuzione.objects.count() == 2
    motore.controlla_tempo()
    assert Esecuzione.objects.count() == 3


def test_accendere_solo_da_ora_lascia_fuori_quello_in_attesa(client, superuser, scena):
    azienda, cliente = scena
    _modello(azienda)
    vecchia = _scaduta(azienda, cliente)
    regola = _regola(azienda, "fattura.scaduta", [{"tipo": "email", "a": "cliente", "modello": "personale.a"}], giorni=7, attiva=False)
    html = client.get(f"/automazioni/{regola.pk}/").content.decode()
    assert "riguarda già" in html and str(vecchia) in html
    prima = len(mail.outbox)
    client.post(f"/automazioni/{regola.pk}/attiva/", {"esistenti": "no"})
    regola.refresh_from_db()
    assert regola.attiva and motore.in_attesa(regola) == [] and len(mail.outbox) == prima
    assert regola.esecuzioni.get().esito == Esecuzione.SALTATA


def test_accendere_anche_su_quelli_in_attesa(client, superuser, scena):
    azienda, cliente = scena
    _scaduta(azienda, cliente)
    regola = _regola(azienda, "fattura.scaduta", [{"tipo": "nota", "testo": "x"}], giorni=7, attiva=False)
    client.post(f"/automazioni/{regola.pk}/attiva/", {"esistenti": "si"})
    regola.refresh_from_db()
    assert regola.attiva and len(motore.in_attesa(regola)) == 1


# ---------- regole al salvataggio

def _ticket(azienda, **altri):
    return Ticket.objects.create(azienda=azienda, oggetto="Stampa ferma", **altri)


def test_ticket_creato_con_condizione(scena):
    azienda, _ = scena
    utente = User.objects.create_user("sara", "sara@x.it", "x")
    tipo = TipoAttivita.objects.first()
    _regola(azienda, "ticket.creato", [{"tipo": "assegna", "utente": utente.pk},
                                       {"tipo": "attivita", "a": "assegnatario", "testo": "Guarda {{ numero }}", "tipo_attivita": tipo.pk}],
            condizioni=[{"campo": "priorita", "op": "uguale", "valore": "urgente"}])
    normale = _ticket(azienda)
    assert not Esecuzione.objects.exists() and normale.assegnatario is None
    urgente = _ticket(azienda, priorita="urgente")
    urgente.refresh_from_db()
    assert urgente.assegnatario == utente
    attivita = AttivitaPianificata.objects.get(object_id=urgente.pk)
    assert attivita.assegnatario == utente and urgente.numero in attivita.riepilogo


def test_una_regola_non_fa_scattare_le_altre(scena):
    azienda, _ = scena
    utente = User.objects.create_user("sara", "sara@x.it", "x")
    _regola(azienda, "ticket.creato", [{"tipo": "assegna", "utente": utente.pk}])
    catena = _regola(azienda, "ticket.assegnato", [{"tipo": "nota", "testo": "Catena"}])
    t = _ticket(azienda)
    assert not catena.esecuzioni.exists()
    altro = User.objects.create_user("bruno", "b@x.it", "x")
    t.refresh_from_db()
    t.assegnatario = altro
    t.save()
    assert catena.esecuzioni.count() == 1                 # a mano sì


def test_ticket_chiuso_una_volta(scena):
    azienda, _ = scena
    regola = _regola(azienda, "ticket.chiuso", [{"tipo": "nota", "testo": "Chiuso"}])
    t = _ticket(azienda)
    assert not regola.esecuzioni.exists()
    t.fase = FaseTicket.objects.filter(chiusa=True).first()
    t.save()
    t.save()
    assert regola.esecuzioni.count() == 1


def test_fattura_emessa_e_incassata(scena):
    azienda, cliente = scena
    emessa = _regola(azienda, "fattura.emessa", [{"tipo": "nota", "testo": "E"}])
    incassata = _regola(azienda, "fattura.incassata", [{"tipo": "nota", "testo": "I"}])
    f = _scaduta(azienda, cliente)
    assert emessa.esecuzioni.count() == 1 and not incassata.esecuzioni.exists()
    fatture.incassa(f.scadenze.get())
    assert incassata.esecuzioni.count() == 1


def test_azienda_diversa_e_regola_spenta_non_scattano(scena):
    azienda, _ = scena
    altra = Azienda.objects.create(nome="Altra")
    fuori = _regola(altra, "ticket.creato", [{"tipo": "nota", "testo": "x"}])
    spenta = _regola(azienda, "ticket.creato", [{"tipo": "nota", "testo": "x"}], attiva=False)
    _ticket(azienda)
    assert not fuori.esecuzioni.exists() and not spenta.esecuzioni.exists()


def test_azione_saltata_non_ferma_le_altre_e_si_riprova(client, superuser, scena):
    azienda, cliente = scena
    cliente.email = ""
    cliente.save()
    _modello(azienda)
    _scaduta(azienda, cliente)
    regola = _regola(azienda, "fattura.scaduta", [{"tipo": "email", "a": "cliente", "modello": "personale.a"}, {"tipo": "nota", "testo": "Fatto"}], giorni=7)
    record, chiave, extra = motore.in_attesa(regola)[0]
    esecuzione = motore.applica(regola, record, chiave, extra)
    assert esecuzione.esito == Esecuzione.SALTATA and [p["esito"] for p in esecuzione.dettaglio] == ["saltata", "fatta"]
    cliente.email = "nuova@rossi.it"
    cliente.save()
    client.post(f"/automazioni/storico/{esecuzione.pk}/riprova/")
    assert mail.outbox[-1].to == ["nuova@rossi.it"] and regola.esecuzioni.get().esito == Esecuzione.FATTA
    prima = len(mail.outbox)
    client.post(f"/automazioni/storico/{regola.esecuzioni.get().pk}/riprova/")   # riuscita: non si rimanda
    assert len(mail.outbox) == prima


def test_salvare_il_record_non_si_rompe_se_il_motore_si_rompe(scena, monkeypatch):
    azienda, _ = scena
    _regola(azienda, "ticket.creato", [{"tipo": "nota", "testo": "x"}])
    monkeypatch.setattr(motore.lavori, "accoda", lambda *a, **k: 1 / 0)
    assert _ticket(azienda).pk


# ---------- simulazione

def test_la_simulazione_non_manda_e_non_scrive(client, superuser, scena):
    azienda, cliente = scena
    _modello(azienda)
    f = _scaduta(azienda, cliente)
    regola = _regola(azienda, "fattura.scaduta", [{"tipo": "email", "a": "cliente", "modello": "personale.a"}, {"tipo": "nota", "testo": "N"}], giorni=7, attiva=False)
    prima, note = len(mail.outbox), Messaggio.objects.count()
    html = client.get(f"/automazioni/{regola.pk}/prova/").content.decode()
    assert "amm@rossi.it" in html and str(f) in html and "122,00" in html
    assert len(mail.outbox) == prima and Messaggio.objects.count() == note and not regola.esecuzioni.exists()


# ---------- costruttore e permessi

def _invia(client, **dati):
    base = {"nome": "Mia", "evento": "ticket.creato", "giorni": "", "condizioni": "[]", "azioni": "[]"}
    return client.post("/automazioni/nuova/", {**base, **dati})


def test_il_costruttore_salva_spenta_e_rifiuta_il_resto(client, superuser, scena):
    azienda, _ = scena
    assert client.get("/automazioni/nuova/").status_code == 200
    assert _invia(client).status_code == 200 and not Regola.objects.exists()                  # niente azioni
    assert _invia(client, evento="non.esiste", azioni='[{"tipo":"nota","testo":"x"}]').status_code == 200
    assert _invia(client, azioni='[{"tipo":"nota","testo":"{{ inventato }}"}]').status_code == 200
    assert _invia(client, azioni='[{"tipo":"email","a":"cliente","modello":"di.altri"}]').status_code == 200
    assert _invia(client, azioni='[{"tipo":"assegna","utente":99999}]').status_code == 200
    assert _invia(client, azioni='[{"tipo":"sistema","comando":"rm"}]').status_code == 200
    assert _invia(client, condizioni='[{"campo":"password","op":"uguale","valore":"x"}]', azioni='[{"tipo":"nota","testo":"x"}]').status_code == 200
    assert not Regola.objects.exists()
    assert _invia(client, azioni='[{"tipo":"nota","testo":"Ciao {{ numero }}"}]', condizioni='[{"campo":"priorita","op":"uguale","valore":"alta"}]').status_code == 302
    r = Regola.objects.get()
    assert not r.attiva and r.creata_da == superuser and r.azioni[0]["testo"] == "Ciao {{ numero }}"
    assert client.get(f"/automazioni/{r.pk}/modifica/").status_code == 200


def test_modello_di_un_altra_azienda_non_si_usa(client, superuser, scena):
    altra = Azienda.objects.create(nome="Altra")
    _modello(altra, dominio="ticket", codice="personale.b")
    assert _invia(client, azioni='[{"tipo":"email","a":"cliente","modello":"personale.b"}]').status_code == 200
    assert not Regola.objects.exists()


def test_regola_di_un_altra_azienda_non_si_vede(client, superuser, scena):
    altra = Azienda.objects.create(nome="Altra")
    r = _regola(altra, "ticket.creato", [{"tipo": "nota", "testo": "x"}])
    assert client.get(f"/automazioni/{r.pk}/").status_code == 404
    assert client.post(f"/automazioni/{r.pk}/elimina/").status_code == 404


def test_servono_i_permessi(client, db, scena):
    utente = User.objects.create_user("semplice", password="x")
    client.force_login(utente)
    assert client.get("/automazioni/").status_code == 403
    assert client.get("/automazioni/modelli/").status_code == 403
    assert client.post("/automazioni/modelli/anteprima/").status_code == 403


def test_tutte_le_ricette_sono_valide_e_si_aprono(client, superuser, scena):
    azienda, _ = scena
    from automazioni import regole as controlli
    assert len(ricette.disponibili()) >= 8
    for voce in ricette.disponibili():
        assert client.post(f"/automazioni/pronte/{voce['codice']}/").status_code == 302
    assert Regola.objects.filter(attiva=True).count() == 0
    for r in Regola.objects.all():
        assert controlli.descrivi_azioni(r), r
        for a in r.azioni:
            if a["tipo"] == "email":
                m = ModelloEmail.objects.get(codice=a["modello"])
                d = motore.catalogo.dominio_di(r.evento)
                assert modelli_email.errori(m.oggetto, m.corpo, {**modelli_email.CAMPI_SEMPRE, **d.campi}) == [], m
            elif "testo" in a:
                assert controlli._testo_campi(a["testo"], motore.catalogo.dominio_di(r.evento)) == set(), a
    assert client.get("/automazioni/").status_code == 200
    assert client.get("/automazioni/storico/").status_code == 200
    html = client.get("/automazioni/modelli/").content.decode()
    assert "Sollecito gentile" in html and "Invio della fattura" in html
