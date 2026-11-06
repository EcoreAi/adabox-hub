import email.message

import pytest
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.urls import reverse

from core import chatter
from core.chatter import email as posta_core
from core.chatter import entrata
from core.generici import ct_di
from core.models import Azienda, EmailRicevuta, Modulo, TipoAttivita
from core.models import Messaggio as MessaggioChatter
from discuss import notifiche, posta_canali, schede, servizi
from discuss.models import Canale, Collegamento, Notifica
from todo.models import Attivita


def _utente(nome, *permessi):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_canale", "add_messaggio", *permessi]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def persone(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    settings.SITO_URL = "https://erp.esempio.it"
    return _utente("anna", "view_attivita", "add_attivita", "change_attivita"), _utente("bruno", "view_attivita"), _utente("carla")


@pytest.fixture
def record(db):
    return Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="Rinnovo contratto Rossi", descrizione="segreta")


def _url(record):
    return reverse("todo:attivita_dettaglio", args=[record.pk])


def test_link_a_un_record_diventa_scheda_coi_permessi_di_chi_legge(client, persone, record):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna, [bruno, carla])
    m = servizi.invia(canale, anna, f"guarda https://erp.esempio.it{_url(record)} grazie")
    assert Collegamento.objects.filter(messaggio=m, object_id=record.pk).exists()
    # chi può vedere trova titolo, azioni e il link; chi può modificare anche «Modifica»
    client.force_login(anna)
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert "Rinnovo contratto Rossi" in html.split('class="ds-scheda"')[1] and reverse("todo:attivita_modifica", args=[record.pk]) in html
    client.force_login(bruno)
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert 'class="ds-scheda-titolo"' in html and reverse("todo:attivita_modifica", args=[record.pk]) not in html
    # chi non ha il permesso non vede nemmeno il titolo nella scheda
    client.force_login(carla)
    pezzo = client.get(reverse("discuss:scheda", args=[ct_di(record).pk, record.pk])).content.decode()
    assert "non puoi vedere" in pezzo and "Rinnovo" not in pezzo
    # la scheda è viva: legge il record di adesso
    Attivita.objects.filter(pk=record.pk).update(titolo="Rinnovo firmato")
    client.force_login(bruno)
    assert "Rinnovo firmato" in client.get(reverse("discuss:scheda", args=[ct_di(record).pk, record.pk])).content.decode()
    # record eliminato
    pk, ct = record.pk, ct_di(record).pk
    record.delete()
    assert "non c'è più" in client.get(reverse("discuss:scheda", args=[ct, pk])).content.decode()


def test_link_esterni_e_pagine_che_non_sono_record_non_fanno_schede(persone, record):
    anna, *_ = persone
    assert schede.riconosci(f"https://altro.it{_url(record)} e https://erp.esempio.it/dashboard/") == []
    assert schede.riconosci(f"http://127.0.0.1:8096{_url(record)}", host="127.0.0.1:8096") == [(Attivita, record.pk)]


def test_cronologia_del_record_non_svela_le_conversazioni_private(persone, record):
    anna, bruno, _ = persone
    pubblico = servizi.crea_canale("team", Canale.PUBBLICO, anna)
    servizi.invia(pubblico, anna, "serve **una mano**", record=[record])
    voce = chatter.messaggi_di(record).filter(tipo=MessaggioChatter.SISTEMA).first()
    assert "#team" in voce.corpo and "serve una mano" in voce.corpo
    diretto = servizi.diretto([anna, bruno])
    servizi.invia(diretto, anna, "confidenziale", record=[record])
    corpi = [v.corpo for v in chatter.messaggi_di(record).filter(tipo=MessaggioChatter.SISTEMA)]
    assert any(c == "Citato in una conversazione privata." for c in corpi) and not any("confidenziale" in c for c in corpi)


def test_condividi_da_un_record(client, persone, record):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna)
    privato = servizi.crea_canale("altrui", Canale.PRIVATO, bruno)
    client.force_login(anna)
    assert "discuss:condividi" not in client.get(_url(record)).content.decode()
    pagina = client.get(_url(record)).content.decode()
    url = reverse("discuss:condividi", args=[ct_di(record).pk, record.pk])
    assert url in pagina and reverse("discuss:canale_record", args=[ct_di(record).pk, record.pk]) in pagina
    html = client.get(url).content.decode()
    assert "# team" in html and "altrui" not in html
    r = client.post(url, {"messaggio": "ci pensi tu?", "persone": [bruno.pk, carla.pk], "canali": [canale.pk, privato.pk]}, follow=True)
    avviso = r.content.decode()
    assert "Carla" in avviso and "senza i dati" in avviso                         # carla non ha il permesso, ed è detto
    assert canale.messaggi.filter(corpo="ci pensi tu?").count() == 1 and not privato.messaggi.exists()
    assert servizi.diretto([anna, bruno]).messaggi.get().collegamenti.get().object_id == record.pk
    assert Notifica.objects.filter(utente=bruno, tipo="diretto").exists()
    assert client.post(url, {}).status_code == 302 and canale.messaggi.count() == 1
    # senza accesso al record non si condivide
    client.force_login(carla)
    assert client.get(url).status_code == 403


def test_conversazione_dedicata_al_record(client, persone, record):
    anna, bruno, carla = persone
    chatter.segui(record, bruno)
    chatter.segui(record, carla)                                                  # non vede il record: non entra
    client.force_login(anna)
    url = reverse("discuss:canale_record", args=[ct_di(record).pk, record.pk])
    r = client.post(url)
    canale = Canale.objects.get(record_id=record.pk)
    assert r.url == f"/discuss/c/{canale.pk}/" and canale.tipo == Canale.PRIVATO
    assert set(canale.membri.values_list("username", flat=True)) == {"anna", "bruno"}
    assert servizi.fissati(canale)[0].collegamenti.get().object_id == record.pk
    assert client.post(url).url == r.url and Canale.objects.filter(record_id=record.pk).count() == 1
    client.force_login(carla)
    assert client.post(url).status_code == 403


def test_dal_messaggio_a_un_attivita_e_a_un_record_nuovo(client, persone, record):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna, [bruno])
    tipo = TipoAttivita.objects.create(nome="Chiamata prova")
    m = servizi.invia(canale, anna, "chiamare **Rossi** domani", record=[record])
    client.force_login(anna)
    html = client.get(reverse("discuss:da_messaggio", args=[m.pk])).content.decode()
    assert "Rinnovo contratto Rossi" in html and 'value="todo:attivita"' in html and "chiamare Rossi domani" in html
    r = client.post(reverse("discuss:attivita_da", args=[m.pk]), {"record": f"{ct_di(record).pk}:{record.pk}", "tipo": tipo.pk,
                                                                  "assegnatario": bruno.pk, "scadenza": "2030-01-15", "riepilogo": "Chiamata"})
    assert r.status_code == 204
    att = record and chatter and Notifica.objects.get(utente=bruno, tipo="attivita")
    assert "Chiamata" in att.testo and att.url == _url(record)
    assert canale.messaggi.filter(tipo="sistema", corpo__contains="ha creato un'attività").exists()
    # un record nuovo: modulo precompilato, poi si lega al messaggio una volta sola
    r = client.get(reverse("discuss:crea_da", args=[m.pk]), {"vista": "todo:attivita"})
    assert r.url.startswith(reverse("todo:attivita_nuovo")) and "titolo=chiamare+Rossi+domani" in r.url
    assert "chiamare Rossi domani" in client.get(r.url).content.decode()
    nuovo = Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="Nata dal messaggio")
    client.get(_url(record))                                                     # un altro record, più vecchio: non si lega
    assert m.collegamenti.count() == 1
    client.get(_url(nuovo))
    assert m.collegamenti.filter(object_id=nuovo.pk).exists() and canale.messaggi.filter(corpo__contains="Nata dal messaggio").exists()
    n = m.collegamenti.count()
    client.get(_url(nuovo))
    assert m.collegamenti.count() == n and canale.messaggi.filter(corpo__contains="Nata dal messaggio").count() == 1
    # chi non può creare non arriva al modulo; un messaggio di un canale privato altrui nemmeno
    client.force_login(bruno)
    assert client.get(reverse("discuss:crea_da", args=[m.pk]), {"vista": "todo:attivita"}).status_code == 404
    segreto = servizi.invia(servizi.crea_canale("x", Canale.PRIVATO, anna), anna, "no")
    assert client.get(reverse("discuss:da_messaggio", args=[segreto.pk])).status_code == 404


def test_la_posta_raccoglie_tutto_cio_che_si_segue_con_i_filtri(client, persone, record):
    anna, bruno, _ = persone
    chatter.segui(record, bruno)
    chatter.scrivi(record, anna, tipo=MessaggioChatter.TRACCIAMENTO, modifiche=[{"campo": "stato", "label": "Stato", "prima": "Aperta", "dopo": "Fatta"}])
    n = Notifica.objects.get(utente=bruno)
    assert n.tipo == "record" and "ha modificato" in n.titolo and n.testo == "Stato: Aperta → Fatta"
    servizi.invia(servizi.crea_canale("t", Canale.PUBBLICO, anna, [bruno]), anna, "@bruno ciao")
    client.force_login(bruno)
    assert "Stato: Aperta" in client.get("/discuss/posta/?filtro=record").content.decode()
    html = client.get("/discuss/posta/?filtro=menzioni").content.decode()
    assert "Stato: Aperta" not in html and "@bruno ciao" in html
    # le modifiche non partono per email: resterebbero troppe
    Notifica.objects.update(creata="2020-01-01T00:00:00Z")
    notifiche.invia_email()
    assert len(mail.outbox) == 1 and "ciao" in mail.outbox[0].body


def _risposta(da, a, testo, mid="<r1@fuori>"):
    msg = email.message.EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = da, a, "Re", mid
    msg.set_content(testo)
    return msg.as_bytes()


def test_canale_lista_email_esce_e_rientra(persone, settings, django_capture_on_commit_callbacks):
    anna, bruno, carla = persone
    settings.EMAIL_RISPOSTE = "risposte@esempio.it"
    canale = servizi.crea_canale("annunci", Canale.PUBBLICO, anna, [bruno])
    Canale.objects.filter(pk=canale.pk).update(lista_email=True)
    canale.refresh_from_db()
    m = servizi.invia(canale, anna, "**Riunione** alle 15")
    posta_canali.invia_lista(m.pk)
    assert [e.to for e in mail.outbox] == [["bruno@example.com"]]
    uscita = mail.outbox[0]
    assert uscita.subject == "[annunci] Riunione alle 15" and uscita.reply_to[0].startswith("risposte+")
    # risponde dalla sua casella: entra nel canale come suo messaggio
    riga = entrata.ricevi(_risposta("bruno@example.com", uscita.reply_to[0], "Ci sono!"))
    assert riga.stato == EmailRicevuta.ABBINATA and canale.messaggi.filter(autore=bruno, corpo="Ci sono!").exists()
    assert not chatter.messaggi_di(canale).exists()                               # non finisce nel chatter del canale
    # chi non è iscritto, o un estraneo, resta fuori
    riga = entrata.ricevi(_risposta("carla@example.com", uscita.reply_to[0], "Intrusa", "<r2@fuori>"))
    assert riga.stato == EmailRicevuta.RIFIUTATA and not canale.messaggi.filter(corpo="Intrusa").exists()
    riga = entrata.ricevi(_risposta("x@fuori.it", uscita.reply_to[0], "Spam", "<r3@fuori>"))
    assert riga.stato == EmailRicevuta.RIFIUTATA
    # token falsificato: non abbinata
    riga = entrata.ricevi(_risposta("bruno@example.com", "risposte+99-1-0000000000000000@esempio.it", "x", "<r4@fuori>"))
    assert riga.stato == EmailRicevuta.NON_ABBINATA


def test_risposta_per_email_a_un_avviso_di_messaggio_diretto(persone, settings):
    anna, bruno, _ = persone
    settings.EMAIL_RISPOSTE = "risposte@esempio.it"
    diretto = servizi.diretto([anna, bruno])
    servizi.invia(diretto, anna, "ci sei?")
    Notifica.objects.update(creata="2020-01-01T00:00:00Z")
    notifiche.invia_email()
    avviso = mail.outbox[0]
    assert avviso.reply_to == [posta_core.indirizzo_risposta(ct_di(diretto).pk, diretto.pk)]
    entrata.ricevi(_risposta("bruno@example.com", avviso.reply_to[0], "sì"))
    assert diretto.messaggi.filter(autore=bruno, corpo="sì").exists()


def test_modulo_spento_niente_azioni_sui_record_e_niente_notifiche(client, persone, record):
    anna, bruno, _ = persone
    client.force_login(anna)
    Modulo.objects.update_or_create(slug="discuss", defaults={"nome": "Discuss", "versione_installata": "1.2.0", "stato": "installato", "disattivato": True})
    html = client.get(_url(record)).content.decode()
    assert "discuss" not in html.lower().split("<main")[1].split("</main")[0] and "Condividi" not in html
    tipo = TipoAttivita.objects.create(nome="Prova spenta")
    from core import attivita
    attivita.pianifica(record, tipo, bruno, creato_da=anna)
    chatter.segui(record, bruno)
    chatter.scrivi(record, anna, tipo=MessaggioChatter.TRACCIAMENTO, modifiche=[{"campo": "x", "label": "X", "prima": "a", "dopo": "b"}])
    assert not Notifica.objects.exists()
    # e una risposta via email resta fuori
    canale = servizi.crea_canale("c", Canale.PUBBLICO, anna, [bruno])
    riga = entrata.ricevi(_risposta("bruno@example.com", f"r+{posta_core.token_risposta(ct_di(canale).pk, canale.pk)}@esempio.it", "x"))
    assert riga.stato == EmailRicevuta.RIFIUTATA and "disattivato" in riga.motivo
