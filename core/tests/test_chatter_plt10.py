"""Chatter (PLT-10): messaggi fissati in cima, @menzioni avvisate per email anche senza Discuss, messaggio anche a un
indirizzo esterno scelto al momento (con gli allegati, e la sua risposta torna sul record)."""
from email.message import EmailMessage

import pytest
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from core import chatter
from core.chatter import entrata
from core.generici import ct_di
from core.models import Azienda, EmailRicevuta, Messaggio
from core.registry import modules


@pytest.fixture(autouse=True)
def ambiente(settings, tmp_path, monkeypatch):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    settings.EMAIL_RISPOSTE = "risposte@example.com"
    monkeypatch.setattr(entrata, "_GESTORI", [])


def _utente(nome, *codenames):
    u = User.objects.create_user(nome, f"{nome}@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def acme(db):
    return Azienda.objects.create(nome="Acme", partita_iva="01")


def test_fissare_un_messaggio(client, acme):
    anna = _utente("anna", "view_azienda", "change_azienda")
    client.force_login(anna)
    vecchio = chatter.scrivi(acme, anna, "Il cliente paga solo a 60 giorni", tipo=Messaggio.NOTA)
    for i in range(25):                                         # finisce oltre la prima pagina
        chatter.scrivi(acme, None, f"evento {i}", tipo=Messaggio.SISTEMA)
    r = client.post(f"/chatter/messaggio/{vecchio.pk}/fissa/", HTTP_HX_REQUEST="true")
    pannello = r.content.decode()
    assert Messaggio.objects.get(pk=vecchio.pk).fissato
    assert "Fissati (1)" in pannello and "Il cliente paga solo a 60 giorni" in pannello
    client.post(f"/chatter/messaggio/{vecchio.pk}/fissa/", {"azione": "togli"})
    assert not Messaggio.objects.get(pk=vecchio.pk).fissato

    sistema = Messaggio.objects.filter(tipo=Messaggio.SISTEMA).first()   # gli eventi di sistema no
    assert client.post(f"/chatter/messaggio/{sistema.pk}/fissa/").status_code == 404
    client.force_login(_utente("bruno", "view_azienda"))                 # chi non può modificare il record no
    assert client.post(f"/chatter/messaggio/{vecchio.pk}/fissa/").status_code == 403
    assert "chatter_fissa" not in client.get(f"/chatter/{ct_di(acme).pk}/{acme.pk}/").content.decode()


def test_menzione_per_email_senza_discuss(acme, monkeypatch):
    monkeypatch.setattr(modules, "disattivati", lambda: frozenset({"discuss"}))
    anna = _utente("anna", "view_azienda")
    carlo = _utente("carlo", "view_azienda")
    _utente("dario")                                            # non vede il record: niente avviso
    chatter.scrivi(acme, anna, "@carlo @dario guardate il fido", tipo=Messaggio.NOTA)
    (avviso,) = mail.outbox
    assert avviso.to == [carlo.email] and "anna ti ha menzionato su Acme" in avviso.subject
    assert "guardate il fido" in avviso.body and "ti hanno menzionato con @carlo" in avviso.body
    mail.outbox.clear()
    chatter.scrivi(acme, anna, "@anna promemoria per me", tipo=Messaggio.NOTA)   # sé stessi no
    assert mail.outbox == []


def test_con_discuss_la_menzione_va_nella_posta(acme):
    from django.apps import apps
    if not apps.is_installed("discuss"):
        pytest.skip("Discuss non installato")
    anna, carlo = _utente("anna", "view_azienda"), _utente("carlo", "view_azienda")
    chatter.scrivi(acme, anna, "@carlo guarda", tipo=Messaggio.NOTA)
    assert mail.outbox == []                                    # l'email arriva da Discuss solo se resta non letta
    from discuss.models import Notifica
    assert Notifica.objects.filter(utente=carlo, tipo=Notifica.MENZIONE).exists()


def test_messaggio_anche_a_un_indirizzo_esterno(client, acme):
    anna = _utente("anna", "view_azienda", "change_azienda")
    client.force_login(anna)
    url = f"/chatter/{ct_di(acme).pk}/{acme.pk}/scrivi/"
    client.post(url, {"corpo": "Le mando l'offerta", "tipo": "messaggio", "a": ["Mario@Cliente.it", "mario@cliente.it; laura@cliente.it"],
                      "file": SimpleUploadedFile("offerta.txt", b"prezzi")})
    m = Messaggio.objects.get(corpo="Le mando l'offerta")
    assert m.destinatari == ["Mario@Cliente.it", "laura@cliente.it"]
    esterne = {e.to[0]: e for e in mail.outbox}
    assert set(esterne) == {"Mario@Cliente.it", "laura@cliente.it"}
    email = esterne["laura@cliente.it"]
    assert email.attachments[0][0] == "offerta.txt" and email.attachments[0][1] in ("prezzi", b"prezzi") and "/core/aziende/" not in email.body
    assert email.reply_to[0].startswith("risposte+")
    pannello = client.get(f"/chatter/{ct_di(acme).pk}/{acme.pk}/").content.decode()
    assert "anche a Mario@Cliente.it, laura@cliente.it" in pannello

    risposta = EmailMessage()
    risposta["From"], risposta["To"], risposta["Subject"] = "laura@cliente.it", "risposte@example.com", "Re: Acme"
    risposta["Message-ID"], risposta["In-Reply-To"] = "<r1@cliente.it>", Messaggio.objects.get(pk=m.pk).message_id
    risposta.set_content("Ricevuta, grazie")
    assert entrata.ricevi(risposta.as_bytes()).stato == EmailRicevuta.ABBINATA
    assert chatter.messaggi_di(acme).first().autore_email == "laura@cliente.it"
    estranea = EmailMessage()
    estranea["From"], estranea["To"], estranea["Subject"] = "altro@spam.it", "risposte@example.com", "Re: Acme"
    estranea["Message-ID"], estranea["In-Reply-To"] = "<r2@spam.it>", m.message_id or "<x>"
    estranea.set_content("ciao")
    assert entrata.ricevi(estranea.as_bytes()).stato == EmailRicevuta.RIFIUTATA


def test_indirizzo_esterno_controlli(client, acme):
    client.force_login(_utente("anna", "view_azienda", "change_azienda"))
    url = f"/chatter/{ct_di(acme).pk}/{acme.pk}/scrivi/"
    client.post(url, {"corpo": "x", "tipo": "messaggio", "a": "non-una-email"})
    assert not Messaggio.objects.exists() and mail.outbox == []
    client.post(url, {"corpo": "solo interna", "tipo": "nota", "a": "mario@cliente.it"})   # una nota resta interna
    assert Messaggio.objects.get().destinatari == [] and mail.outbox == []
    client.force_login(_utente("bruno", "view_azienda"))                 # serve poter modificare il record
    assert client.post(url, {"corpo": "y", "tipo": "messaggio", "a": "mario@cliente.it"}).status_code == 403
    assert "Anche a un indirizzo esterno" not in client.get(f"/chatter/{ct_di(acme).pk}/{acme.pk}/").content.decode()


def test_chatter_sulle_scadenze_con_l_email_del_cliente(client, superuser):
    from django.apps import apps
    if not apps.is_installed("fatturazione"):
        pytest.skip("fatturazione non installata")
    import datetime

    from contatti.models import Contatto
    from fatturazione.models import Fattura, Scadenza
    az = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(nome="Rossi Srl", email="amministrazione@rossi.it", azienda=az) \
        if any(f.name == "azienda" for f in Contatto._meta.fields) else Contatto.objects.create(nome="Rossi Srl", email="amministrazione@rossi.it")
    campi = {f.name for f in Fattura._meta.fields}
    fattura = Fattura.objects.create(cliente=cliente, data=datetime.date(2026, 11, 1),
                                     **({"azienda": az} if "azienda" in campi else {}))
    s = Scadenza.objects.create(fattura=fattura, data=datetime.date(2026, 12, 1), importo=100)
    html = client.get(f"/fatturazione/scadenze/{s.pk}/").content.decode()
    assert 'id="chatter"' in html and 'value="amministrazione@rossi.it"' in html
