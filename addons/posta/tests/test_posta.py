"""Posta e calendario: collegamento OAuth, email con i clienti nello storico, calendario nei due versi e feed."""
import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.utils import timezone

import crm
from calendario.models import Evento
from contatti.models import Contatto
from core import cifratura
from core.generici import ct_di
from core.models import Azienda, Lavoro, Messaggio, Sequenza
from crm.models import Opportunita
from posta import agenda, fornitori, sincronia
from posta.fornitori.microsoft import _evento as evento_microsoft
from posta.models import Casella, EmailSincronizzata, EventoCollegato, FeedCalendario, ServizioOAuth

from .finti import FintoGoogle, FintoMicrosoft, messaggio

pytestmark = pytest.mark.django_db
IO = "anna@miaditta.it"


@pytest.fixture
def azienda():
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    a = Azienda.objects.first()
    Sequenza.objects.get_or_create(codice="contatti.contatto", azienda=a, defaults={"formato": "C{numero:05d}"})
    return a


def _utente(azienda, nome="anna", email=IO, *permessi):
    u = User.objects.create_user(nome, email, "x")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="posta", codename__in=["add_casella", *permessi]))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return u


@pytest.fixture
def anna(azienda):
    return _utente(azienda)


@pytest.fixture
def servizi():
    for tipo in ("google", "microsoft"):
        ServizioOAuth.objects.create(tipo=tipo, client_id=f"cid-{tipo}", segreto_cifrato=cifratura.cifra("segreto"))


@pytest.fixture
def google(monkeypatch):
    finto = FintoGoogle(IO)
    monkeypatch.setattr(fornitori, "TRASPORTO", finto.trasporto())
    return finto


@pytest.fixture
def microsoft(monkeypatch):
    finto = FintoMicrosoft(IO)
    monkeypatch.setattr(fornitori, "TRASPORTO", finto.trasporto())
    return finto


def _casella(azienda, utente, tipo="google", **campi):
    return Casella.objects.create(azienda=azienda, utente=utente, tipo=tipo, email=IO, refresh_cifrato=cifratura.cifra("ref-1"), **campi)


@pytest.fixture
def cliente(azienda):
    ditta = Contatto.objects.create(azienda=azienda, codice="C1", nome="Verdi Srl", tipo=Contatto.AZIENDA)
    return Contatto.objects.create(azienda=azienda, codice="C2", nome="Luca Verdi", email="Luca@Verdi.it", tipo=Contatto.PERSONA, societa=ditta)


def _storico(obj):
    return list(Messaggio.objects.filter(content_type=ct_di(obj), object_id=obj.pk).order_by("pk"))


# --- collegamento --------------------------------------------------------------------------------------------------

def test_collegare_google_con_pkce_e_tornare(client, anna, servizi, google):
    client.force_login(anna)
    r = client.post("/posta/collega/google/")
    url = urlsplit(r["Location"])
    p = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "accounts.google.com" and p["client_id"] == "cid-google" and p["code_challenge_method"] == "S256"
    assert p["access_type"] == "offline" and p["prompt"] == "consent" and "gmail.readonly" in p["scope"] and "calendar.events" in p["scope"]
    assert p["redirect_uri"].endswith("/posta/ritorno/")
    r = client.get("/posta/ritorno/", {"state": p["state"], "code": "abc"})
    assert r.status_code == 302
    c = Casella.objects.get()
    assert c.utente == anna and c.email == IO and c.refresh_token() == "ref-1" and "ref-1" not in c.refresh_cifrato
    assert c.azienda == anna.profilo.azienda_predefinita


def test_stato_sbagliato_o_consenso_negato_non_collega(client, anna, servizi, google):
    client.force_login(anna)
    client.post("/posta/collega/google/")
    client.get("/posta/ritorno/", {"state": "altro", "code": "abc"})
    client.post("/posta/collega/google/")
    client.get("/posta/ritorno/", {"error": "access_denied"})
    client.get("/posta/ritorno/", {"state": "x", "code": "abc"})              # senza richiesta in sessione
    assert not Casella.objects.exists()


def test_microsoft_con_tenant_e_indirizzo_da_graph(client, anna, servizi, microsoft):
    ServizioOAuth.objects.filter(tipo="microsoft").update(tenant="contoso.onmicrosoft.com")
    client.force_login(anna)
    r = client.post("/posta/collega/microsoft/")
    url = urlsplit(r["Location"])
    p = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "login.microsoftonline.com" and url.path == "/contoso.onmicrosoft.com/oauth2/v2.0/authorize"
    assert "offline_access" in p["scope"] and "Calendars.ReadWrite" in p["scope"] and "Mail.Read" in p["scope"]
    client.get("/posta/ritorno/", {"state": p["state"], "code": "abc"})
    assert Casella.objects.get().email == IO


def test_senza_servizi_la_pagina_lo_dice(client, anna):
    client.force_login(anna)
    assert "non è ancora configurato" in client.get("/posta/").content.decode()


# --- posta ---------------------------------------------------------------------------------------------------------

def test_solo_le_email_con_i_contatti_si_scaricano_e_finiscono_nello_storico(azienda, anna, servizi, google, cliente):
    collega = User.objects.create_user("bruno", "bruno@miaditta.it")
    o = Opportunita.objects.create(azienda=azienda, titolo="Impianto", contatto=cliente.societa)
    ora = timezone.now() - datetime.timedelta(hours=1)
    google.aggiungi("m1", messaggio("Luca Verdi <luca@verdi.it>", [IO], "Preventivo impianto", "Va bene il prezzo.\n\nIl giorno lun Anna ha scritto:\n> vecchio"),
                    quando=ora)
    google.aggiungi("m2", messaggio(IO, ["bruno@miaditta.it"], "Pranzo?"))                        # solo colleghi
    google.aggiungi("m3", messaggio("news@negozio.example", [IO], "Offerte"))                     # nessun contatto
    google.aggiungi("m4", messaggio(IO, ["luca@verdi.it"], "Re: Preventivo impianto", "Perfetto, procediamo.", cc=[collega.email], allegato=True),
                    quando=ora + datetime.timedelta(minutes=5))
    google.aggiungi("m5", messaggio("luca@verdi.it", [IO], "spam"), etichette=["SPAM"])
    c = _casella(azienda, anna)
    testo = sincronia.giro(c.pk)
    assert "2 nuove" in testo, testo
    assert sorted(google.scaricati) == ["m1", "m4"]                                               # le altre non si leggono
    voci = _storico(cliente)
    assert [v.corpo.splitlines()[0] for v in voci] == ["✉ Preventivo impianto", "✉ Re: Preventivo impianto"]
    assert "Va bene il prezzo." in voci[0].corpo and "vecchio" not in voci[0].corpo and voci[0].autore_email == "luca@verdi.it"
    assert voci[1].autore == anna and "1 allegati restano nella casella" in voci[1].corpo
    assert [v.message_id for v in _storico(o)] == [v.message_id for v in voci]                    # anche l'opportunità aperta
    assert not Lavoro.objects.filter(funzione__icontains="notific").exists()                      # non riparte ai follower
    assert EmailSincronizzata.objects.count() == 2 and not EmailSincronizzata.objects.filter(oggetto__in=["Pranzo?", "Offerte"]).exists()
    c.refresh_from_db()
    assert c.cursore_posta and not c.in_errore
    sincronia.giro(c.pk)
    assert len(_storico(cliente)) == 2 and sorted(google.scaricati) == ["m1", "m4"]               # rileggere non duplica


def test_con_due_opportunita_aperte_non_si_sceglie(azienda, anna, servizi, google, cliente):
    for t in ("Uno", "Due"):
        Opportunita.objects.create(azienda=azienda, titolo=t, contatto=cliente)
    google.aggiungi("m1", messaggio("luca@verdi.it", [IO]))
    sincronia.giro(_casella(azienda, anna).pk)
    assert len(_storico(cliente)) == 1 and not any(_storico(o) for o in Opportunita.objects.all())


def test_la_stessa_email_in_due_caselle_si_scrive_una_volta(azienda, anna, servizi, google, cliente):
    bruno = _utente(azienda, "bruno", "bruno@miaditta.it")
    m = messaggio("luca@verdi.it", [IO, "bruno@miaditta.it"], message_id="<unico@verdi.it>")
    google.aggiungi("m1", m)
    sincronia.giro(_casella(azienda, anna).pk)
    sincronia.giro(Casella.objects.create(azienda=azienda, utente=bruno, tipo="google", email="bruno@miaditta.it",
                                          refresh_cifrato=cifratura.cifra("ref-1")).pk)
    assert len(_storico(cliente)) == 1


def test_contatti_di_un_altra_azienda_non_contano(azienda, anna, servizi, google):
    altra = Azienda.objects.create(nome="Altra")
    Contatto.objects.create(azienda=altra, codice="X1", nome="Estraneo", email="luca@verdi.it", tipo=Contatto.PERSONA)
    google.aggiungi("m1", messaggio("luca@verdi.it", [IO]))
    sincronia.giro(_casella(azienda, anna).pk)
    assert google.scaricati == [] and not Messaggio.objects.exists()


def test_microsoft_pagine_e_refresh_token_rinnovato(azienda, anna, servizi, microsoft, cliente, monkeypatch):
    from posta.fornitori import microsoft as modulo
    monkeypatch.setattr(modulo, "PER_PAGINA", 2)
    for i in range(5):
        microsoft.aggiungi(f"AAMk{i}=", messaggio("luca@verdi.it", [IO], f"Messaggio {i}"))
    c = _casella(azienda, anna, tipo="microsoft")
    assert "5 nuove" in sincronia.giro(c.pk)
    c.refresh_from_db()
    assert c.refresh_token() == "ref-2" and c.accesso_scade > timezone.now()
    assert all(r.url.host in ("graph.microsoft.com", "login.microsoftonline.com") for r in microsoft.chiamate)


def test_token_scaduto_si_rinnova_e_si_riusa(azienda, anna, servizi, google, cliente):
    c = _casella(azienda, anna, accesso_cifrato=cifratura.cifra("vecchio"), accesso_scade=timezone.now() + datetime.timedelta(hours=1))
    sincronia.giro(c.pk)                                    # 401 col vecchio, rinnovo, poi tutto col nuovo
    assert google.rinnovi == 1
    sincronia.giro(c.pk)
    assert google.rinnovi == 1                              # il nuovo è salvato sulla casella


def test_accesso_revocato_la_casella_va_ricollegata(azienda, anna, servizi, google):
    google.revocato = True
    c = _casella(azienda, anna)
    assert "ricollega" in sincronia.giro(c.pk)
    c.refresh_from_db()
    assert c.in_errore and "ricollega" in c.ultimo_esito


# --- calendario ------------------------------------------------------------------------------------------------------

def test_gli_appuntamenti_arrivano_privati_e_con_i_contatti(azienda, anna, servizi, google, cliente):
    google.evento("e1", summary="Visita da Verdi", location="Bergamo", attendees=[{"email": "luca@verdi.it"}, {"email": IO}])
    google.evento("e2", summary="Ferie", start={"date": "2026-12-24"}, end={"date": "2026-12-27"})
    google.evento("e3", summary="Ogni lunedì", recurrence=["RRULE:FREQ=WEEKLY"])
    google.evento("e4", summary="Annullata", status="cancelled")
    c = _casella(azienda, anna, posta=False)
    assert "2 nuovi" in sincronia.giro(c.pk)
    visita, ferie = Evento.objects.get(titolo="Visita da Verdi"), Evento.objects.get(titolo="Ferie")
    assert visita.organizzatore == anna and visita.privato and visita.promemoria == 0 and list(visita.contatti.all()) == [cliente]
    assert visita.inizio == datetime.datetime(2026, 11, 20, 9, 0, tzinfo=datetime.timezone.utc) and visita.luogo == "Bergamo"
    assert ferie.tutto_il_giorno and timezone.localtime(ferie.inizio).date() == datetime.date(2026, 12, 24)
    assert timezone.localtime(ferie.fine).date() == datetime.date(2026, 12, 26)
    assert not Lavoro.objects.filter(funzione="posta.agenda.scrivi_fuori").exists()                  # ciò che arriva non riparte
    google.evento("e1", summary="Visita da Verdi spostata", start={"dateTime": "2026-11-21T10:00:00+01:00"}, end={"dateTime": "2026-11-21T11:00:00+01:00"})
    assert "1 aggiornati" in sincronia.giro(c.pk)
    visita.refresh_from_db()
    assert visita.titolo == "Visita da Verdi spostata" and Evento.objects.count() == 2


def test_gli_eventi_organizzati_qui_partono_e_non_tornano_indietro(azienda, anna, servizi, google, django_capture_on_commit_callbacks):
    c = _casella(azienda, anna, posta=False)
    inizio = timezone.make_aware(datetime.datetime(2026, 11, 25, 15, 0))
    with django_capture_on_commit_callbacks(execute=True):
        e = Evento.objects.create(azienda=azienda, titolo="Demo al cliente", inizio=inizio, fine=inizio + datetime.timedelta(hours=1),
                                  organizzatore=anna, luogo="Sede")
    fuori = google.eventi["g1"]
    assert fuori["summary"] == "Demo al cliente" and fuori["location"] == "Sede"
    assert datetime.datetime.fromisoformat(fuori["start"]["dateTime"]) == inizio
    assert EventoCollegato.objects.get().evento == e
    assert "0 nuovi, 0 aggiornati" in sincronia.giro(c.pk)                                            # torna uguale: nessun rimbalzo
    with django_capture_on_commit_callbacks(execute=True):
        e.titolo = "Demo al cliente (2)"
        e.save()
    assert google.eventi["g1"]["summary"] == "Demo al cliente (2)" and len(google.eventi) == 1
    altro = _utente(azienda, "bruno", "bruno@miaditta.it")
    with django_capture_on_commit_callbacks(execute=True):
        Evento.objects.create(azienda=azienda, titolo="Di Bruno", inizio=inizio, fine=inizio, organizzatore=altro)
    assert len(google.eventi) == 1                                                                    # solo i propri


def test_calendario_microsoft_nei_due_versi(azienda, anna, servizi, microsoft, django_capture_on_commit_callbacks):
    c = _casella(azienda, anna, tipo="microsoft", posta=False)
    microsoft.eventi["AAM9"] = {"id": "AAM9", "subject": "Call", "type": "singleInstance", "isCancelled": False, "isAllDay": False,
                                "start": {"dateTime": "2026-11-20T09:00:00.0000000", "timeZone": "UTC"},
                                "end": {"dateTime": "2026-11-20T09:30:00.0000000", "timeZone": "UTC"},
                                "lastModifiedDateTime": "2026-11-10T10:00:00Z", "body": {"contentType": "text", "content": "Ordine del giorno"}}
    microsoft.eventi["AAM8"] = {**microsoft.eventi["AAM9"], "id": "AAM8", "type": "seriesMaster"}
    sincronia.giro(c.pk)
    call = Evento.objects.get()
    assert call.titolo == "Call" and call.descrizione == "Ordine del giorno" and call.inizio.hour == 9
    giorno = timezone.make_aware(datetime.datetime(2026, 12, 1))
    with django_capture_on_commit_callbacks(execute=True):
        Evento.objects.create(azienda=azienda, titolo="Fiera", inizio=giorno, fine=giorno, tutto_il_giorno=True, organizzatore=anna)
    fiera = next(e for e in microsoft.eventi.values() if e["subject"] == "Fiera")
    assert fiera["isAllDay"] and fiera["start"]["dateTime"] == "2026-12-01T00:00:00" and fiera["end"]["dateTime"] == "2026-12-02T00:00:00"


def test_giornata_intera_di_microsoft_che_torna_alle_23():
    e = evento_microsoft({"id": "x", "subject": "Ferie", "isAllDay": True, "start": {"dateTime": "2026-12-23T23:00:00.0000000"},
                          "end": {"dateTime": "2026-12-26T23:00:00.0000000"}, "lastModifiedDateTime": "2026-11-10T10:00:00Z"})
    assert timezone.localtime(e["inizio"]).date() == datetime.date(2026, 12, 24) and timezone.localtime(e["fine"]).date() == datetime.date(2026, 12, 26)


def test_impronta_ignora_spazi_e_cambia_con_gli_orari():
    inizio = timezone.now()
    d = {"titolo": "A", "inizio": inizio, "fine": inizio, "tutto_il_giorno": False, "luogo": "", "descrizione": "x"}
    assert agenda.impronta(d) == agenda.impronta({**d, "descrizione": "x\n"})
    assert agenda.impronta(d) != agenda.impronta({**d, "fine": inizio + datetime.timedelta(minutes=30)})


# --- feed e pagine ---------------------------------------------------------------------------------------------------

def test_feed_segreto_con_i_propri_appuntamenti(client, azienda, anna):
    bruno = _utente(azienda, "bruno", "bruno@miaditta.it")
    adesso = timezone.now()
    mio = Evento.objects.create(azienda=azienda, titolo="Mio", inizio=adesso, fine=adesso, organizzatore=anna)
    invitata = Evento.objects.create(azienda=azienda, titolo="Invitata", inizio=adesso, fine=adesso, organizzatore=bruno)
    invitata.partecipanti.add(anna)
    Evento.objects.create(azienda=azienda, titolo="Di Bruno", inizio=adesso, fine=adesso, organizzatore=bruno)
    Evento.objects.create(azienda=azienda, titolo="Vecchio", inizio=adesso - datetime.timedelta(days=200), fine=adesso - datetime.timedelta(days=200),
                          organizzatore=anna)
    client.force_login(anna)
    client.post("/posta/feed/rinnova/")
    token = FeedCalendario.objects.get(utente=anna).token
    client.logout()
    r = client.get(f"/posta/feed/{token}.ics")
    testo = r.content.decode()
    assert r.status_code == 200 and r["Content-Type"].startswith("text/calendar") and testo.count("BEGIN:VEVENT") == 2
    assert "SUMMARY:Mio" in testo and "SUMMARY:Invitata" in testo and "Di Bruno" not in testo and "X-WR-CALNAME:" in testo
    assert f"UID:{mio.uid}@" in testo
    assert client.get("/posta/feed/sbagliato.ics").status_code == 404
    client.force_login(anna)
    client.post("/posta/feed/rinnova/")
    assert client.get(f"/posta/feed/{token}.ics").status_code == 404                                   # il vecchio non vale più


def test_ognuno_tocca_solo_la_propria_casella(client, azienda, anna, servizi):
    bruno = _utente(azienda, "bruno", "bruno@miaditta.it")
    sua = _casella(azienda, bruno)
    client.force_login(anna)
    assert client.post(f"/posta/casella/{sua.pk}/scollega/").status_code == 404
    assert client.post(f"/posta/casella/{sua.pk}/imposta/", {"posta": "on"}).status_code == 404
    assert client.get("/posta/caselle_utenti/").status_code == 403                                   # la lista è dell'amministratore
    assert "bruno@miaditta.it" not in client.get("/posta/").content.decode()


def test_preferenze_e_scollegare(client, azienda, anna, servizi):
    c = _casella(azienda, anna)
    client.force_login(anna)
    client.post(f"/posta/casella/{c.pk}/imposta/", {"calendario": "on"})
    c.refresh_from_db()
    assert not c.posta and c.calendario
    client.post(f"/posta/casella/{c.pk}/scollega/")
    assert not Casella.objects.exists()


def test_il_segreto_del_servizio_non_si_rilegge(client, azienda):
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    root.profilo.azienda_predefinita = azienda
    root.profilo.save()
    client.force_login(root)
    r = client.post("/posta/servizi/nuovo/", {"tipo": "google", "client_id": "cid", "tenant": "common", "attivo": "on", "nuovo_segreto": "super-segreto"})
    assert r.status_code == 302
    s = ServizioOAuth.objects.get()
    assert s.segreto() == "super-segreto"
    assert "super-segreto" not in client.get(f"/posta/servizi/{s.pk}/modifica/").content.decode()
    assert "/posta/ritorno/" in client.get("/posta/").content.decode()                               # l'indirizzo da registrare


def test_il_cron_accoda_un_giro_per_casella(azienda, anna):
    _casella(azienda, anna)
    _casella(azienda, _utente(azienda, "spento", "s@miaditta.it"), posta=False, calendario=False)
    Lavoro.objects.all().delete()
    sincronia.giro_di_tutte()
    assert Lavoro.objects.filter(funzione="posta.sincronia.giro").count() == 1
