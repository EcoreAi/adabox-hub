import datetime
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.utils import timezone

from ai import motore, proposte, strumenti
from ai.gateway import finto
from ai.models import AnelloCatena, Conversazione, Evento, MessaggioChat, Modello, Profilo, Proposta, Provider
from core.models import Azienda, Messaggio, TipoAttivita


@pytest.fixture
def scena(db, client):
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    azienda = Azienda.objects.get(pk=1)
    beta = Azienda.objects.create(nome="Beta Srl", citta="Roma", attiva=False)
    return {"capo": capo, "azienda": azienda, "beta": beta, "client": client,
            "conversazione": Conversazione.objects.create(utente=capo, titolo="Prova")}


def _turno(scena, chiamate, testo="Fai pure", risposta="Ecco la proposta."):
    with finto.con_copione([[("strumento", nome, argomenti) for nome, argomenti in chiamate], [risposta]]) as registro:
        motore.avvia(scena["conversazione"], testo, scena["capo"], scena["azienda"])
    return registro


def _risultati():
    return Evento.objects.filter(tipo="strumento").last().dati["risultati"]


def _conferma(scena, p, **dati):
    return scena["client"].post(f"/ai/proposta/{p.pk}/conferma/", dati, HTTP_HX_REQUEST="true")


def test_crea_propone_senza_salvare_e_conferma_una_volta_sola(scena):
    _turno(scena, [("crea_record", {"vista": "core.aziende", "campi": {"nome": "Delta Spa", "citta": "Bari"}})])
    p = Proposta.objects.get()
    assert not Azienda.objects.filter(nome="Delta Spa").exists()
    assert p.stato == "in_attesa" and p.titolo == "Crea azienda «Delta Spa»" and p.rischio == "scrittura"
    assert {"campo": "Nome", "dopo": "Delta Spa"} in p.dettagli
    assert "NON è ancora eseguita" in _risultati()[0]["contenuto"] and not _risultati()[0]["errore"]
    messaggio = MessaggioChat.objects.filter(ruolo="assistente").get()
    assert messaggio.turno_id == p.turno_id
    pagina = scena["client"].get(f"/ai/chat/{scena['conversazione'].pk}/").content.decode()
    assert "Crea azienda «Delta Spa»" in pagina and f"/ai/proposta/{p.pk}/conferma/" in pagina

    r = _conferma(scena, p)
    delta = Azienda.objects.get(nome="Delta Spa")
    p.refresh_from_db()
    assert r.status_code == 200 and "Eseguita" in r.content.decode()
    assert p.stato == "eseguita" and p.url == f"/core/aziende/{delta.pk}/" and "Delta Spa" in p.esito
    assert Messaggio.objects.filter(object_id=delta.pk, corpo__contains="Tramite l'assistente AI").exists()
    _conferma(scena, p)
    assert Azienda.objects.filter(nome="Delta Spa").count() == 1

    with finto.con_copione([["Bene."]]) as registro:                      # l'esito arriva al modello
        motore.avvia(scena["conversazione"], "Grazie", scena["capo"], scena["azienda"])
    domanda = registro[0]["messaggi"][-1]["testo"]
    assert f"Proposta n. {p.pk} «Crea azienda «Delta Spa»»: eseguita" in domanda
    p.refresh_from_db()
    assert p.comunicata
    with finto.con_copione([["Ok."]]) as registro:                        # una volta sola
        motore.avvia(scena["conversazione"], "Altro", scena["capo"], scena["azienda"])
    assert "Esiti delle proposte" not in registro[0]["messaggi"][-1]["testo"]


def test_dati_non_validi_niente_proposta(scena):
    _turno(scena, [("crea_record", {"vista": "core.aziende", "campi": {"citta": "Bari"}}),
                   ("crea_record", {"vista": "core.aziende", "campi": {"nome": "X", "inventato": 1}}),
                   ("modifica_record", {"vista": "core.aziende", "id": scena["beta"].pk, "campi": {"citta": "Roma"}})])
    errori = [r["contenuto"] for r in _risultati()]
    assert all(r["errore"] for r in _risultati()) and not Proposta.objects.exists()
    assert "Nome:" in errori[0] and "non si può impostare" in errori[1] and "Nessuna modifica" in errori[2]


def test_modifica_con_prima_e_dopo_e_rifiuto_se_il_record_cambia(scena):
    beta = scena["beta"]
    _turno(scena, [("modifica_record", {"vista": "core.aziende", "id": beta.pk, "campi": {"citta": "Napoli"}}),
                   ("modifica_record", {"vista": "core.aziende", "id": beta.pk, "campi": {"provincia": "NA"}})])
    prima, seconda = Proposta.objects.all()
    assert prima.dettagli == [{"campo": "Città", "prima": "Roma", "dopo": "Napoli"}]
    _conferma(scena, prima)
    beta.refresh_from_db()
    assert beta.citta == "Napoli" and beta.provincia == ""
    Azienda.objects.filter(pk=beta.pk).update(provincia="SA")                 # cambiata da qualcun altro
    _conferma(scena, seconda)
    seconda.refresh_from_db()
    beta.refresh_from_db()
    assert seconda.stato == "fallita" and "cambiato" in seconda.esito and beta.provincia == "SA"


def test_elimina_irreversibile_vuole_la_spunta(scena):
    beta = scena["beta"]
    _turno(scena, [("elimina_record", {"vista": "core.aziende", "id": beta.pk})])
    p = Proposta.objects.get()
    assert p.rischio == "irreversibile" and "non si può annullare" in p.riepilogo
    r = _conferma(scena, p)
    assert "Spunta la casella" in r.content.decode() and Azienda.objects.filter(pk=beta.pk).exists()
    _conferma(scena, p, consapevole="1")
    p.refresh_from_db()
    assert p.stato == "eseguita" and not Azienda.objects.filter(pk=beta.pk).exists()


def test_bottone_e_azione(scena, monkeypatch):
    beta, azienda = scena["beta"], scena["azienda"]
    _turno(scena, [("esegui_bottone", {"vista": "core.aziende", "id": beta.pk, "bottone": "attiva"}),
                   ("esegui_bottone", {"vista": "core.aziende", "id": beta.pk, "bottone": "inventato"}),
                   ("esegui_azione", {"vista": "core.aziende", "azione": "disattiva", "ids": [azienda.pk]})])
    assert "Disponibili: attiva" in _risultati()[1]["contenuto"]
    bottone, azione = Proposta.objects.all()
    assert bottone.titolo == "Attiva: azienda «Beta Srl»" and azione.dettagli == [{"campo": "Record",
                                                                                 "dopo": str(azienda)}]
    _conferma(scena, bottone)
    _conferma(scena, azione)
    bottone.refresh_from_db()
    azione.refresh_from_db()
    assert bottone.esito == "Azienda «Beta Srl» attivata." and azione.esito == "Aziende disattivate: 1."
    assert Azienda.objects.get(pk=beta.pk).attiva and not Azienda.objects.get(pk=azienda.pk).attiva
    from core.views import AziendaView
    monkeypatch.setattr(AziendaView.attiva, "ai", False, raising=False)       # i download non li vede
    d = strumenti.viste.descrivi_vista(strumenti.Contesto(utente=scena["capo"], azienda=azienda), "core.aziende")
    assert d["bottoni_del_record"] == []


def test_pianifica_attivita_sul_record(scena):
    TipoAttivita.objects.get_or_create(nome="Chiamata", defaults={"giorni": 2})
    domani = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
    _turno(scena, [("pianifica_attivita", {"vista": "core.aziende", "id": scena["beta"].pk, "tipo": "chiamata",
                                           "scadenza": domani, "riepilogo": "Richiamare per l'offerta"}),
                   ("pianifica_attivita", {"vista": "core.aziende", "id": scena["beta"].pk, "tipo": "Telepatia"})])
    assert "inesistente" in _risultati()[1]["contenuto"]
    p = Proposta.objects.get()
    _conferma(scena, p)
    from core.models import AttivitaPianificata
    a = AttivitaPianificata.objects.get()
    assert a.object_id == scena["beta"].pk and a.scadenza.isoformat() == domani and a.assegnatario == scena["capo"]
    assert a.riepilogo == "Richiamare per l'offerta"


def test_permessi_rispettati_in_anteprima_e_alla_conferma(scena, client):
    lettore = User.objects.create_user("lettore", password="x")
    lettore.user_permissions.add(*Permission.objects.filter(codename__in=["view_azienda", "add_azienda",
                                                                          "view_conversazione"]))
    conversazione = Conversazione.objects.create(utente=lettore)
    contesto = strumenti.Contesto(utente=lettore, azienda=scena["azienda"], conversazione=conversazione)
    ammessi = {s.nome: s for s in strumenti.disponibili(lettore)}
    chiamate = [finto.ChiamataStrumento("1", "modifica_record", {"vista": "core.aziende", "id": scena["beta"].pk,
                                                                 "campi": {"citta": "Bari"}}),
                finto.ChiamataStrumento("2", "crea_record", {"vista": "core.aziende", "campi": {"nome": "Mia"}})]
    nega, crea = strumenti.esegui(chiamate, contesto, ammessi)
    assert nega["errore"] and "Permesso negato" in nega["contenuto"] and not crea["errore"]
    p = Proposta.objects.get()
    client.force_login(scena["capo"])                                       # di un altro utente: 404
    assert client.post(f"/ai/proposta/{p.pk}/conferma/").status_code == 404
    lettore.user_permissions.remove(Permission.objects.get(codename="add_azienda"))
    lettore = User.objects.get(pk=lettore.pk)
    proposte.conferma(p, lettore, scena["azienda"])
    assert p.stato == "fallita" and not Azienda.objects.filter(nome="Mia").exists()


def test_scadenza_azienda_diversa_e_annulla(scena):
    _turno(scena, [("crea_record", {"vista": "core.aziende", "campi": {"nome": "Uno"}}),
                   ("crea_record", {"vista": "core.aziende", "campi": {"nome": "Due"}}),
                   ("crea_record", {"vista": "core.aziende", "campi": {"nome": "Tre"}})])
    uno, due, tre = Proposta.objects.all()
    Proposta.objects.filter(pk=uno.pk).update(creata=timezone.now() - datetime.timedelta(days=2))
    uno.refresh_from_db()
    assert uno.scaduta
    proposte.conferma(uno, scena["capo"], scena["azienda"])
    assert uno.stato == "scaduta" and not Azienda.objects.filter(nome="Uno").exists()
    with pytest.raises(strumenti.ErroreStrumento, match="passa a quell'azienda"):
        proposte.conferma(due, scena["capo"], scena["beta"])
    r = scena["client"].post(f"/ai/proposta/{tre.pk}/annulla/", HTTP_HX_REQUEST="true")
    tre.refresh_from_db()
    assert tre.stato == "annullata" and "Annullata" in r.content.decode()
    _conferma(scena, tre)
    assert not Azienda.objects.filter(nome="Tre").exists()


@pytest.mark.skipif("vendite" not in settings.ADDONS_ATTIVI, reason="serve l'app vendite")
def test_preventivo_con_righe(scena, tmp_path):
    from pathlib import Path

    from django.core.management import call_command

    import fiscale
    import prodotti
    from contatti.models import Contatto
    from prodotti.models import Prodotto
    from vendite.models import OrdineVendita
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    cliente = Contatto.objects.create(azienda=scena["azienda"], nome="Rossi Srl", cliente=True)
    monitor = Prodotto.objects.create(azienda=scena["azienda"], nome="Monitor", prezzo_vendita=Decimal("200"))
    _turno(scena, [("crea_record", {"vista": "vendite.ordini", "campi": {"cliente": {"id": cliente.pk, "nome": "x"}},
                                    "righe": [{"prodotto": monitor.pk, "quantita": 2}, {"inventato": 1}]}),
                   ("crea_record", {"vista": "vendite.ordini", "campi": {"cliente": cliente.pk},
                                    "righe": [{"prodotto": monitor.pk, "quantita": 2},
                                              {"descrizione": "Trasporto", "prezzo": "15"}]})])
    assert "Campi delle righe non validi: inventato" in _risultati()[0]["contenuto"]
    assert not _risultati()[1]["errore"], _risultati()[1]["contenuto"]
    p = Proposta.objects.get()
    assert {"campo": "Cliente", "dopo": "Rossi Srl"} in p.dettagli and any(d["campo"] == "Righe 2" for d in p.dettagli)
    _conferma(scena, p)
    ordine = OrdineVendita.objects.get()
    assert ordine.righe.count() == 2 and ordine.imponibile == Decimal("415.00") and ordine.commerciale == scena["capo"]
    assert ordine.numero and p.__class__.objects.get().stato == "eseguita"
