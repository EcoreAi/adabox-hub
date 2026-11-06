"""Attività pianificate dentro un progetto e sessione di lavoro nel calendario."""
from datetime import time as ora

from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai import pianificate
from ai.gateway import finto
from ai.models import Pianificata, ProgettoChat
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)


def _progetto(s, **extra):
    return ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Migrazione Rossi", istruzioni="Rispondi in tre punti.", **extra)


def test_l_attivita_lavora_nel_progetto(s):
    p = _progetto(s)
    attivita = Pianificata.objects.create(utente=s["u"], azienda=s["az"], nome="Stato settimanale", istruzioni="Scrivi lo stato.",
                                          ricorrenza="giorni", alle=ora(9), progetto=p)
    with finto.con_copione([["Stato: tutto in ordine."]]) as chiamate:
        pianificate.esegui(attivita)
    attivita.refresh_from_db()
    assert attivita.conversazione.progetto == p
    assert "Rispondi in tre punti." in str(chiamate[0]["messaggi"])                 # le istruzioni del progetto arrivano
    attivita.progetto = None
    attivita.save()
    with finto.con_copione([["ok"]]):
        pianificate.esegui(attivita)
    attivita.conversazione.refresh_from_db()
    assert attivita.conversazione.progetto is None                                 # tolto il progetto, la chat ne esce


def test_un_progetto_di_un_altro_non_si_usa(s):
    altro = User.objects.create_user("bruno", password="x")
    loro = ProgettoChat.objects.create(utente=altro, azienda=s["az"], nome="Loro", istruzioni="SEGRETO")
    attivita = Pianificata.objects.create(utente=s["u"], azienda=s["az"], nome="x", istruzioni="x", ricorrenza="giorni", alle=ora(9), progetto=loro)
    with finto.con_copione([["ok"]]) as chiamate:
        pianificate.esegui(attivita)
    attivita.refresh_from_db()
    assert attivita.conversazione.progetto is None and "SEGRETO" not in str(chiamate[0]["messaggi"])


def test_form_e_testata_del_progetto(client, s):
    p = _progetto(s)
    ProgettoChat.objects.create(utente=User.objects.create_user("bruno", password="x"), azienda=s["az"], nome="Progetto di Bruno")
    form = client.get(f"{reverse('ai:pianificate_nuovo')}?progetto={p.pk}").content.decode()
    assert f'<option value="{p.pk}" selected>Migrazione Rossi</option>' in form and "Progetto di Bruno" not in form
    Pianificata.objects.create(utente=s["u"], azienda=s["az"], nome="Stato settimanale", istruzioni="x", ricorrenza="giorni", alle=ora(9), progetto=p)
    s["u"].user_permissions.add(*Permission.objects.filter(content_type__app_label="calendario", codename="add_evento"))
    client.force_login(User.objects.get(pk=s["u"].pk))
    testa = client.get(reverse("ai:progetto", args=[p.pk])).content.decode()
    assert "Stato settimanale" in testa and f"{reverse('ai:pianificate_nuovo')}?progetto={p.pk}" in testa
    assert reverse("calendario:eventi_nuovo") + "?titolo=" in testa and "Sessione in calendario" in testa


def test_attivita_nuova_con_i_giorni_feriali_gia_spuntati(client, s):
    import re
    form = client.get(reverse("ai:pianificate_nuovo")).content.decode()
    spuntati = {int(v) for v in re.findall(r'<input type="checkbox" name="giorni" value="(\d)"[^>]*checked', form)}
    assert spuntati == {0, 1, 2, 3, 4}
