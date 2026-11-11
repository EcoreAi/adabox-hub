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
