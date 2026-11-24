"""Il grafico o la tabella sotto una risposta si ricalcola lì dov'è (↻), con i dati di oggi e l'ora dei dati."""
from django.contrib.auth.models import User

from ai import artifact, strumenti
from ai.models import Artifact, Conversazione
from core.models import Azienda


def _grafico(utente):
    c = strumenti.Contesto(utente=utente, azienda=Azienda.objects.get(pk=1),
                           conversazione=Conversazione.objects.create(utente=utente))
    return Artifact.objects.get(pk=artifact.grafico(c, "core.aziende", per="provincia")["artifact"])


def test_aggiorna_artifact_in_chat(client, superuser):
    Azienda.objects.filter(pk=1).update(provincia="MI")
    a = _grafico(superuser)
    assert a.dati["serie"] == [["MI", 1]]
    Azienda.objects.create(nome="Beta", provincia="RM")
    r = client.post(f"/ai/artifact/{a.pk}/aggiorna/", HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert r.status_code == 200 and f'id="ai-artifact-{a.pk}"' in html and "RM" in html
    a.refresh_from_db()
    assert ["RM", 1] in a.dati["serie"] and a.aggiornato is not None
    assert "Aggiorna con i dati di oggi" in html and "dati delle" in html


def test_aggiorna_artifact_solo_il_proprietario(client, superuser):
    bruno = User.objects.create_user("bruno", "b@example.com", "x")
    a = Artifact.objects.create(conversazione=Conversazione.objects.create(utente=bruno), utente=bruno, tipo="grafico",
                                titolo="Di Bruno", spec={"tipo": "grafico", "vista": "core.aziende", "per": "provincia"}, dati={})
    assert client.post(f"/ai/artifact/{a.pk}/aggiorna/").status_code == 404


def test_senza_piu_accesso_all_azienda_il_grafico_non_si_ricalcola(client, superuser):
    """Il grafico resta di chi l'ha chiesto, ma i dati di oggi di un'azienda a cui non accede più non li legge: la
    richiesta finta degli strumenti prende l'azienda dall'artifact, senza il controllo del middleware."""
    Azienda.objects.filter(pk=1).update(provincia="MI")
    altra = Azienda.objects.create(nome="Beta", provincia="RM")
    a = _grafico(superuser)
    fotografia = a.dati["serie"]
    superuser.profilo.aziende.set([altra])                    # spostato su un'altra azienda del gruppo
    Azienda.objects.filter(pk=1).update(provincia="ZQ")       # un dato nuovo, che non deve più vedere da qui
    r = client.post(f"/ai/artifact/{a.pk}/aggiorna/", follow=True)
    a.refresh_from_db()
    assert a.dati["serie"] == fotografia and "non hai più accesso" in r.content.decode()
    assert "ZQ" not in client.get(f"/ai/artifact/{a.pk}/csv/?oggi=1").content.decode()
    pagina = client.get(f"/ai/artifact/{a.pk}/").content.decode()
    assert "non hai più accesso" in pagina and "ZQ" not in pagina


def test_un_grafico_con_valori_non_numerici_non_rompe_la_chat(client, superuser):
    """min e max di una data danno una data: il grafico si salvava e da lì la pagina della chat rispondeva 500."""
    from pathlib import Path

    import crm
    import pytest
    from crm.models import Opportunita
    from django.core.management import call_command

    from ai.templatetags.ai import serie_artifact, svg_artifact
    call_command("loaddata", str(Path(crm.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    Opportunita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="Fornitura")
    c = strumenti.Contesto(utente=superuser, azienda=Azienda.objects.get(pk=1), conversazione=Conversazione.objects.create(utente=superuser))
    with pytest.raises(strumenti.ErroreStrumento, match="misura numerica"):
        artifact.grafico(c, "crm.opportunita", per="stato", misura="max:creata_il")
    assert not Artifact.objects.exists()
    # uno salvato prima della correzione: la pagina si apre, senza il disegno
    vecchio = Artifact.objects.create(conversazione=c.conversazione, utente=superuser, azienda=c.azienda, tipo="grafico", titolo="Ultima data",
                                      spec={"tipo": "grafico", "vista": "crm.opportunita", "per": "stato", "misura": "max:creata_il"},
                                      dati={"serie": [["Aperta", "2026-11-20"]], "totale": 1})
    assert serie_artifact(vecchio) is None and svg_artifact(vecchio) == ""


def test_il_csv_non_contiene_formule(superuser):
    """Il nome di un record lo scrive chiunque: «=HYPERLINK(...)» in testa a una cella per Excel è una formula."""
    a = Artifact(tipo="tabella", titolo="Clienti", spec={})
    righe = artifact.csv_di(a, {"colonne": ["Nome", "Saldo"], "righe": [['=HYPERLINK("http://x";"Apri")', "-12,50"], ["@SUM(1)", 5],
                                                                        ["+39 070 123", -3], ["Rossi Srl", "+15 %"]]}).splitlines()
    assert righe[1].startswith("'=HYPERLINK") or righe[1].startswith("\"'=HYPERLINK")
    assert righe[1].endswith(";-12,50") and righe[2] == "'@SUM(1);5" and righe[3] == "'+39 070 123;-3" and righe[4] == "Rossi Srl;+15 %"
    grafico = artifact.csv_di(Artifact(tipo="grafico", titolo="x", spec={}), {"serie": [["=1+1", 3]]}).splitlines()
    assert grafico[1] == "'=1+1;3"


def test_una_tabella_arriva_davvero_a_duecento_righe(superuser):
    Azienda.objects.bulk_create([Azienda(nome=f"Azienda {n:03d}") for n in range(150)])
    c = strumenti.Contesto(utente=superuser, azienda=Azienda.objects.get(pk=1), conversazione=Conversazione.objects.create(utente=superuser))
    assert artifact.tabella(c, "core.aziende", limite=150)["righe"] == 150      # prima: 100, senza dirlo


def test_l_ora_dei_dati_non_cambia_solo_guardando(client, superuser):
    """«dati delle 10:32» sotto il grafico: la segna chi aggiorna l'istantanea, non chi apre la pagina o scarica il CSV."""
    a = _grafico(superuser)
    client.get(f"/ai/artifact/{a.pk}/")
    client.get(f"/ai/artifact/{a.pk}/csv/?oggi=1")
    a.refresh_from_db()
    assert a.aggiornato is None
    client.post(f"/ai/artifact/{a.pk}/aggiorna/")
    a.refresh_from_db()
    assert a.aggiornato is not None
