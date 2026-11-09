"""Automazioni generiche: eventi di qualsiasi vista (nasce, cambia, cambia lo stato), azioni «cambia un campo»,
«premi un bottone» e «chiama un webhook», pagina dei lavori pianificati."""
import json
from decimal import Decimal

import httpx2 as httpx
import pytest
from django.contrib.auth.models import User

from automazioni import catalogo, motore, regole as controlli
from automazioni.models import Esecuzione, Regola
from core.models import Azienda, Pianificazione


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    return {"azienda": azienda, "root": User.objects.create_superuser("root", "r@x.it", "x")}


def test_domini_generici():
    d = catalogo.domini().get("v_magazzino_reso")
    assert d is not None and d.modello == "magazzino.Reso"
    assert {"v_magazzino_reso.creato", "v_magazzino_reso.modificato", "v_magazzino_reso.stato"} <= set(catalogo.eventi())
    assert "stato" in d.condizioni and ("motivo", "Motivo", "scelta") == catalogo.modificabili(d)[[m[0] for m in catalogo.modificabili(d)].index("motivo")][:3]
    assert ("autorizza", "Autorizza") in catalogo.bottoni(d)
    assert "v_fatturazione_fattura" not in catalogo.domini()                    # la fattura ha già il suo dominio


def test_campo_bottone_webhook(s, monkeypatch):
    from pathlib import Path

    from django.core.management import call_command

    import fiscale
    import prodotti
    from contatti.models import Contatto
    from magazzino.models import Magazzino, Reso
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    ricevute = []
    monkeypatch.setattr(motore, "HTTP", httpx.Client(transport=httpx.MockTransport(lambda r: ricevute.append(r) or httpx.Response(200))))
    valori = controlli.pulisci({"nome": "Resi difettosi", "evento": "v_magazzino_reso.creato",
                                "condizioni": json.dumps([{"campo": "motivo", "op": "uguale", "valore": "difettoso"}]),
                                "azioni": json.dumps([{"tipo": "campo", "campo": "descrizione", "valore": "Da controllare: {{ record }}"},
                                                      {"tipo": "bottone", "bottone": "autorizza"},
                                                      {"tipo": "webhook", "url": "https://esempio.it/hook", "segreto": "abc"}])}, s["azienda"])
    regola = Regola.objects.create(azienda=s["azienda"], creata_da=s["root"], attiva=True, **valori)
    cliente = Contatto.objects.create(azienda=s["azienda"], nome="Rossi", cliente=True)
    m = Magazzino.objects.create(azienda=s["azienda"], nome="Sede")
    reso = Reso.objects.create(azienda=s["azienda"], cliente=cliente, magazzino=m, motivo="difettoso")
    reso.righe.create(prodotto=prodotti.models.Prodotto.objects.create(azienda=s["azienda"], nome="X"), quantita=1)
    esecuzione = motore.applica(regola, reso)
    reso.refresh_from_db()
    assert esecuzione.esito == Esecuzione.FATTA, esecuzione.dettaglio
    assert reso.descrizione.startswith("Da controllare") and reso.stato == "autorizzato"
    assert ricevute and ricevute[0].headers["x-adabox-firma"] and json.loads(ricevute[0].content)["id"] == reso.pk
    altro = Reso.objects.create(azienda=s["azienda"], cliente=cliente, magazzino=m, motivo="errato")
    assert motore.applica(regola, altro) is None                               # la condizione non vale


def test_validazione(s):
    with pytest.raises(Exception, match="campo"):
        controlli.pulisci({"nome": "X", "evento": "v_magazzino_reso.creato", "azioni": json.dumps([{"tipo": "campo", "campo": "inventato"}])}, s["azienda"])
    with pytest.raises(Exception, match="https"):
        controlli.pulisci({"nome": "X", "evento": "v_magazzino_reso.creato", "azioni": json.dumps([{"tipo": "webhook", "url": "ftp://x"}])}, s["azienda"])


def test_lavori_pianificati(client, s):
    p = Pianificazione.objects.create(modulo="prova", nome="Lavoro di prova", funzione="x.y", ogni="1h")
    client.force_login(s["root"])
    assert "Lavoro di prova" in client.get("/impostazioni/pianificazioni/").content.decode()
    client.post("/impostazioni/pianificazioni/", {"pk": p.pk, "azione": "interruttore"})
    p.refresh_from_db()
    assert not p.attiva
