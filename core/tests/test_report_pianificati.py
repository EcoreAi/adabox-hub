"""RPT-06: liste filtrate e pagine di Analisi mandate per email a intervalli, nel worker, con i permessi del
proprietario; esito registrato, errori al proprietario, prossimo invio calcolato."""
import csv
import datetime
import io
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.utils import timezone

from core import report_pianificati as rp
from core.models import Azienda, ReportPianificato

ROMA = ZoneInfo("Europe/Rome")


@pytest.fixture
def s(db, superuser):
    az = Azienda.objects.get(pk=1)
    superuser.profilo.aziende.set([az])
    for nome in ("Acme Uno", "Acme Due", "Beta"):
        Azienda.objects.create(nome=nome, partita_iva=nome[-3:])
    return {"az": az, "io": superuser}


def _report(s, **kw):
    dati = {"utente": s["io"], "azienda": s["az"], "nome": "Aziende Acme", "tipo": "lista", "riferimento": "core.aziende",
            "parametri": "q=acme", "formato": "csv", "frequenza": "settimana", "giorno_settimana": 0,
            "ora": datetime.time(7, 0), "destinatari": "capo@example.com, socio@example.com"}
    dati.update(kw)
    return ReportPianificato.objects.create(**dati)


def test_prossimo_invio(s):
    r = _report(s)
    dom = datetime.datetime(2026, 11, 8, 12, 0, tzinfo=ROMA)                    # domenica
    assert rp.prossimo(r, dom) == datetime.datetime(2026, 11, 9, 7, 0, tzinfo=ROMA)
    r.frequenza = "giorno"
    assert rp.prossimo(r, dom) == datetime.datetime(2026, 11, 9, 7, 0, tzinfo=ROMA)
    assert rp.prossimo(r, datetime.datetime(2026, 11, 8, 6, 0, tzinfo=ROMA)).day == 8
    r.frequenza, r.giorno_mese = "mese", 3
    assert rp.prossimo(r, dom) == datetime.datetime(2026, 12, 3, 7, 0, tzinfo=ROMA)


def test_lista_filtrata_per_email(s):
    r = _report(s)
    esito = rp.esegui(r)
    assert esito.startswith("Inviato a 2")
    (email,) = mail.outbox
    assert sorted(email.to) == ["capo@example.com", "socio@example.com"] and "Aziende Acme" in email.subject
    nome, contenuto, _ = email.attachments[0]
    righe = list(csv.reader(io.StringIO(contenuto.decode("utf-8-sig") if isinstance(contenuto, bytes) else contenuto, newline=""), delimiter=";"))
    testo = "\n".join(";".join(x) for x in righe)
    assert nome.endswith(".csv") and "Acme Uno" in testo and "Acme Due" in testo and "Beta" not in testo
    r.refresh_from_db()
    assert r.ultimo_invio and r.prossimo_invio > timezone.now() and r.ultimo_esito.startswith("Inviato")


def test_errori_al_proprietario(s):
    r = _report(s, riferimento="nessuna.vista")
    assert rp.esegui(r).startswith("Errore")
    assert [m.to for m in mail.outbox] == [[s["io"].email]] and "non inviato" in mail.outbox[0].subject
    mail.outbox.clear()
    s["io"].is_active = False
    s["io"].save()
    assert "non è più attivo" in rp.esegui(_report(s))


def test_con_i_permessi_del_proprietario(s):
    anna = User.objects.create_user("anna", "anna@example.com", "x")             # nessun permesso sulle aziende
    anna.profilo.aziende.set([s["az"]])
    assert rp.esegui(_report(s, utente=anna)).startswith("Errore")
    assert not any("capo@example.com" in m.to for m in mail.outbox)


def test_solo_quelli_dovuti(s):
    dovuto = _report(s)
    ReportPianificato.objects.filter(pk=dovuto.pk).update(prossimo_invio=timezone.now() - datetime.timedelta(minutes=1))
    futuro = _report(s, nome="Futuro")
    ReportPianificato.objects.filter(pk=futuro.pk).update(prossimo_invio=timezone.now() + datetime.timedelta(days=1))
    _report(s, nome="Spento", attivo=False)
    assert rp.esegui_dovuti() == 1 and len(mail.outbox) == 1


def test_dalla_lista_al_report(client, s):
    html = client.get("/core/aziende/?q=acme").content.decode()
    assert "Invia per email periodicamente" in html
    form = client.get("/core/report_pianificati/nuovo/?tipo=lista&riferimento=core.aziende&parametri=q%3Dacme&formato=csv").content.decode()
    assert 'value="q=acme"' in form or "q=acme" in form
    client.post("/core/report_pianificati/nuovo/", {"nome": "Acme", "tipo": "lista", "riferimento": "core.aziende", "parametri": "q=acme",
                                                    "formato": "pdf", "frequenza": "giorno", "giorno_settimana": 0, "giorno_mese": 1,
                                                    "ora": "08:00", "destinatari": "x@example.com", "attivo": "on"})
    assert not ReportPianificato.objects.exists()                                   # una lista non va in PDF
    client.post("/core/report_pianificati/nuovo/", {"nome": "Acme", "tipo": "lista", "riferimento": "core.aziende", "parametri": "q=acme",
                                                    "formato": "xlsx", "frequenza": "giorno", "giorno_settimana": 0, "giorno_mese": 1,
                                                    "ora": "08:00", "destinatari": "x@example.com", "attivo": "on"})
    r = ReportPianificato.objects.get()
    assert r.utente == s["io"] and r.prossimo_invio is not None
    client.post(f"/core/report_pianificati/{r.pk}/bottone/invia_ora/")
    assert mail.outbox and mail.outbox[0].attachments[0][0].endswith(".xlsx")


def test_pagina_di_analisi(s, monkeypatch):
    from django.apps import apps
    if not apps.is_installed("grafici"):
        pytest.skip("grafici non installato")
    from core import report
    from grafici import motore
    from grafici.models import Grafico
    p = motore.nuova_pagina(s["io"], "Direzione")
    g = Grafico.objects.create(utente=s["io"], titolo="Aziende per provincia", tipo="barre",
                               spec={"vista": "core.aziende", "per": "provincia", "misura": "count"})
    p.layout = {"widget": [{"id": g.id_widget, "w": 2}]}
    p.save()
    catturato = []
    monkeypatch.setattr(report, "pdf", lambda html: catturato.append(html) or b"%PDF-finto")
    r = _report(s, tipo="analisi", riferimento=str(p.pk), formato="pdf", nome="Direzione settimanale")
    assert rp.esegui(r).startswith("Inviato")
    assert "Aziende per provincia" in catturato[0] and "<svg" in catturato[0]
    assert mail.outbox[0].attachments[0][0].startswith("Direzione")


@pytest.mark.pdf
def test_pagina_di_analisi_pdf_vero(s):
    from io import BytesIO

    from django.apps import apps
    from pypdf import PdfReader

    from core import report
    if not apps.is_installed("grafici") or not report.disponibile():
        pytest.skip("serve WeasyPrint: deploy/test-pdf.sh")
    from grafici import motore
    from grafici.models import Grafico
    p = motore.nuova_pagina(s["io"], "Direzione")
    g = Grafico.objects.create(utente=s["io"], titolo="Aziende per provincia", tipo="barre",
                               spec={"vista": "core.aziende", "per": "provincia", "misura": "count"})
    p.layout = {"widget": [{"id": g.id_widget, "w": 2}]}
    p.save()
    rp.esegui(_report(s, tipo="analisi", riferimento=str(p.pk), formato="pdf"))
    contenuto = mail.outbox[0].attachments[0][1]
    assert contenuto.startswith(b"%PDF") and "Aziende per provincia" in PdfReader(BytesIO(contenuto)).pages[0].extract_text()
