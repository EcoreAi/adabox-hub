from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_dati_demo_si_generano_e_si_tolgono_senza_lasciare_tracce(superuser, tmp_path, monkeypatch):
    from core.management.commands import dati_demo
    from contatti.models import Contatto
    from crm.models import Opportunita
    from fatturazione.models import Fattura, Incasso
    from helpdesk.models import Ticket
    from magazzino.models import Movimento
    from progetti.models import Compito
    from vendite.models import OrdineVendita
    monkeypatch.setattr(dati_demo, "_percorso", lambda: tmp_path / "dati_demo.json")
    prima = {M: M.objects.count() for M in (Contatto, Opportunita, Fattura, Incasso, Ticket, Movimento, Compito, OrdineVendita, User)}
    out = StringIO()
    call_command("dati_demo", "genera", "--scala", "0.15", "--mesi", "8", stdout=out)
    assert "Fatto" in out.getvalue() and (tmp_path / "dati_demo.json").exists()
    assert Opportunita.objects.filter(stato="vinta").exists() and Opportunita.objects.filter(stato="persa").exists()
    assert OrdineVendita.objects.filter(stato="confermato", numero_ordine__gt="").exists()
    assert Fattura.objects.filter(stato="emessa", numero__gt="").exists() and Incasso.objects.exists()
    assert Ticket.objects.filter(chiuso_il__isnull=False).exists() and Ticket.objects.filter(chiuso_il__isnull=True).exists()
    assert Movimento.objects.filter(tipo="carico").exists() and Compito.objects.filter(completato_il__isnull=False).exists()
    assert User.objects.filter(username="giulia.verdi").exists()
    # le fatture emesse hanno numeri crescenti con le date
    emesse = sorted(Fattura.objects.filter(stato="emessa").values_list("numero", "data"), key=lambda x: int(x[0].split("/")[0]))
    assert [d for _, d in emesse] == sorted(d for _, d in emesse)
    with pytest.raises(CommandError):
        call_command("dati_demo", "genera", stdout=StringIO())
    call_command("dati_demo", "azzera", stdout=out)
    assert not (tmp_path / "dati_demo.json").exists()
    assert {M: M.objects.count() for M in prima} == prima
    with pytest.raises(CommandError):
        call_command("dati_demo", "azzera", stdout=StringIO())
