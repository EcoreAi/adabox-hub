"""Prova contro un Odoo 19 vero, solo se indicato (la CI non lo raggiunge):

    ODOO_PROVA_URL=http://172.29.0.3:8069 ODOO_PROVA_DB=ichnohub ODOO_PROVA_CHIAVI=/percorso/chiavi.json pytest …

Il file delle chiavi: {"adabox.test.mario": {"uid": 28, "chiave": "…"}, "adabox.test.lucia": {"uid": 29, "chiave": "…"}};
in Odoo Mario vede solo le sue opportunità, Lucia tutte; i dati di prova hanno «[adabox-test]» nel nome."""
import json
import os
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.test import RequestFactory

import crm
from connettori import sincronia, sistemi
from connettori.models import AccountEsterno, CollegamentoEsterno
from connettori.sistemi import odoo
from contatti.models import Contatto
from core import cifratura
from core.models import Azienda, Sequenza
from core.viste import registry
from crm.models import Opportunita

pytestmark = [pytest.mark.django_db, pytest.mark.skipif(not os.environ.get("ODOO_PROVA_URL"), reason="serve un Odoo vero (ODOO_PROVA_URL)")]


def test_con_un_odoo_vero_ognuno_vede_il_suo(monkeypatch):
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    chiavi = json.load(open(os.environ["ODOO_PROVA_CHIAVI"]))
    azienda = Azienda.objects.get(pk=1)
    Sequenza.objects.get_or_create(codice="contatti.contatto", azienda=azienda, defaults={"formato": "C{numero:05d}"})
    c = CollegamentoEsterno.objects.create(azienda=azienda, sistema="odoo", modalita="vera", comanda="esterno", per_utente=True,
                                           indirizzo=os.environ["ODOO_PROVA_URL"], database=os.environ.get("ODOO_PROVA_DB", ""))
    # l'indirizzo di prova è http sulla rete Docker: si salta il controllo https, il resto è il codice vero
    monkeypatch.setattr(sistemi, "client", lambda coll, account=None: odoo.Odoo(coll.indirizzo, coll.database, account.chiave()))
    utenti = {}
    for login, nome in (("adabox.test.mario", "mario"), ("adabox.test.lucia", "lucia")):
        u = User.objects.create_user(nome, f"{nome}@x.it", "x")
        u.user_permissions.set(Permission.objects.filter(codename__in=["view_opportunita", "view_contatto"]))
        u.profilo.aziende.set([azienda])
        u.profilo.azienda_predefinita = azienda
        u.profilo.save()
        utenti[nome] = User.objects.get(pk=u.pk)
        account = AccountEsterno.objects.create(collegamento=c, utente=u, chiave_cifrata=cifratura.cifra(chiavi[login]["chiave"]))
        account.id_utente_esterno = sistemi.client(c, account).utente()
        account.save()
        assert account.id_utente_esterno == str(chiavi[login]["uid"])
    for nome in ("mario", "lucia"):
        esito = sincronia.giro_account(AccountEsterno.objects.get(utente=utenti[nome]).pk)
        assert esito.startswith("Creati") or esito.startswith("Creati 0"), esito

    def vede(nome):
        request = RequestFactory().get("/")
        request.user, request.azienda = utenti[nome], azienda
        return {o for o in registry.per_modello(Opportunita).get_queryset(request).values_list("titolo", flat=True) if "adabox-test" in o}
    assert vede("mario") == {"[adabox-test] Impianto Verdi (di Mario)"}
    assert {"[adabox-test] Impianto Verdi (di Mario)", "[adabox-test] Manutenzione Verdi (di Lucia)"} <= vede("lucia")
    verdi = Contatto.objects.get(nome="[adabox-test] Verdi Srl")
    anna = Contatto.objects.get(nome="[adabox-test] Anna Verdi")
    assert verdi.partita_iva == "01234567897" and anna.societa == verdi and anna.partita_iva == ""
    assert Opportunita.objects.get(titolo="[adabox-test] Impianto Verdi (di Mario)").commerciale == utenti["mario"]
    assert not Contatto.objects.filter(nome__startswith="[adabox-test] Mario Venditore").exists()       # gli utenti di Odoo no


def test_con_un_odoo_vero_la_scrittura_usa_i_permessi_di_chi_salva(monkeypatch, django_capture_on_commit_callbacks):
    from core import registro
    from core.models import Messaggio
    test_con_un_odoo_vero_ognuno_vede_il_suo(monkeypatch)
    c = CollegamentoEsterno.objects.get()
    CollegamentoEsterno.objects.filter(pk=c.pk).update(scrive_da_adabox=True)
    mario = User.objects.get(username="mario")
    chiavi = json.load(open(os.environ["ODOO_PROVA_CHIAVI"]))
    lettore = odoo.Odoo(c.indirizzo, c.database, chiavi["adabox.test.lucia"]["chiave"])

    def nome_in_odoo():
        return [r["name"] for r in lettore._chiama("crm.lead", "search_read", domain=[["name", "like", "adabox-test"]], fields=["name"])]
    mia = Opportunita.objects.get(titolo="[adabox-test] Impianto Verdi (di Mario)")
    for titolo in ("[adabox-test] Impianto Verdi (di Mario) – rivisto", "[adabox-test] Impianto Verdi (di Mario)"):   # e si rimette com'era
        with django_capture_on_commit_callbacks(execute=True), registro.origine("ui", mario):
            mia.titolo = titolo
            mia.save()
        assert titolo in nome_in_odoo()
    sua = Opportunita.objects.get(titolo="[adabox-test] Manutenzione Verdi (di Lucia)")
    with django_capture_on_commit_callbacks(execute=True), registro.origine("ui", mario):
        sua.titolo = "[adabox-test] tentativo di Mario"
        sua.save()
    assert "[adabox-test] tentativo di Mario" not in nome_in_odoo()
    assert Messaggio.objects.filter(object_id=sua.pk, tipo=Messaggio.SISTEMA, corpo__contains="Non scritto in Odoo").exists()


def test_con_un_odoo_vero_arrivano_gli_appuntamenti(monkeypatch):
    from calendario.models import Evento
    test_con_un_odoo_vero_ognuno_vede_il_suo(monkeypatch)
    c = CollegamentoEsterno.objects.get()
    CollegamentoEsterno.objects.filter(pk=c.pk).update(calendario=True)
    mario = User.objects.get(username="mario")
    esito = sincronia.giro_account(AccountEsterno.objects.get(utente=mario).pk)
    assert "appuntamenti: creati" in esito, esito
    visita = Evento.objects.get(titolo="[adabox-test] Visita da Verdi")
    assert visita.organizzatore == mario and visita.luogo == "Bergamo" and visita.descrizione == "Portare il catalogo"
    assert [x.nome for x in visita.contatti.all()] == ["[adabox-test] Anna Verdi"]
    fiera = Evento.objects.get(titolo="[adabox-test] Fiera")
    assert fiera.tutto_il_giorno


def test_con_un_odoo_vero_arrivano_gli_ordini_in_sola_lettura(monkeypatch):
    import fiscale
    import prodotti
    from core import esterni
    from vendite.models import OrdineVendita
    call_command("loaddata", str(Path(fiscale.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    call_command("loaddata", str(Path(prodotti.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    test_con_un_odoo_vero_ognuno_vede_il_suo(monkeypatch)
    c = CollegamentoEsterno.objects.get()
    CollegamentoEsterno.objects.filter(pk=c.pk).update(ordini=True)
    mario = User.objects.get(username="mario")
    esito = sincronia.giro_account(AccountEsterno.objects.get(utente=mario).pk)
    assert "ordini di vendita: creati" in esito, esito
    o = OrdineVendita.objects.get(riferimento_cliente="adabox-test")
    assert o.numero.startswith("S") and o.cliente.nome == "[adabox-test] Verdi Srl" and o.commerciale == mario
    righe = list(o.righe.order_by("pk"))
    assert [r.prodotto.codice if r.prodotto else r.descrizione for r in righe] == ["ADB-TEST-1", "Servizi", "ADB-TEST-2"]
    assert righe[0].aliquota.codice == "22" and str(o.imponibile) == "516.00"
    assert esterni.gestito_da(o) == "Odoo"
