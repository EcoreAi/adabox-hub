import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from ai import specialisti, strumenti
from ai.models import Conversazione
from ai.strumenti import specialisti as strumenti_specialisti
from core.models import Azienda, Lavoro


@pytest.fixture
def servizi(monkeypatch):
    """Il decisore finto: le chiamate in ordine, (chiave, percorso, dati)."""
    chiamate = []

    def chiama(chiave, percorso, dati, nome):
        chiamate.append((chiave, percorso, dati))
        return {"answers": {"d": {"type": "noul", "noul": 0.91, "backend": "embed_sim"}}}
    monkeypatch.setattr(specialisti, "chiama", chiama)
    return chiamate


@pytest.fixture
def scena(db, client):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    mese = timezone.localdate().replace(day=10)
    for _ in range(9):
        lavoro = Lavoro.objects.create(funzione="prova.lavoro")
        Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(
            datetime.datetime.combine(mese, datetime.time(9))))
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client,
            "conversazione": Conversazione.objects.create(utente=capo)}


def _contesto(scena):
    return strumenti.Contesto(utente=scena["capo"], azienda=scena["azienda"], conversazione=scena["conversazione"])


def test_classifica(scena, servizi):
    r = strumenti_specialisti.classifica(_contesto(scena), "Il server è fermo", "È urgente?")
    assert r["noul"] == 0.91 and "indicative" in r["nota"]
    assert servizi[0][2]["questions"]["d"] == {"type": "noul", "instructions": "È urgente?"}
    with pytest.raises(strumenti.ErroreStrumento, match="opzioni"):
        strumenti_specialisti.classifica(_contesto(scena), "x", "y", tipo="scelta")


def test_filtro_con_data_su_campo_data_e_ora(scena, recwarn):
    from ai.strumenti import viste
    oggi = timezone.localdate()
    r = viste.aggrega_record(_contesto(scena), "core.lavoro", filtri={"creato__gte": oggi.replace(day=1).isoformat()})
    assert r["totale"] == 9 and not [w for w in recwarn if "naive datetime" in str(w.message)]


@pytest.mark.parametrize("modulo", ["ai.specialisti", "ai.pianificate", "ai.conoscenza", "ai.protezione",
                                    "ai.artifact", "ai.strumenti"])
def test_ogni_modulo_si_importa_per_primo(modulo):
    """Il worker e i comandi caricano i moduli in ordini diversi: nessun import circolare a seconda di chi parte."""
    import subprocess
    import sys

    from django.conf import settings
    esito = subprocess.run([sys.executable, "-c", f"import django; django.setup(); import {modulo}"],
                           cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=120)
    assert esito.returncode == 0, esito.stderr[-1500:]


def test_l_affidabilita_va_sotto_la_risposta():
    import json
    from django.template.loader import render_to_string
    from ai import provenienza
    contenuto = json.dumps({"titolo": "Previsione fatturato", "modello": "Timestral",
                            "affidabilita": {"livello": "bassa", "motivi": ["Storia: 10 mesi"]}})
    p = provenienza._affidabilita(contenuto)
    assert p == {"titolo": "Previsione fatturato", "livello": "bassa", "motivi": ["Storia: 10 mesi"], "modello": "Timestral"}
    assert provenienza._affidabilita("non è json") is None
    html = render_to_string("ai/_provenienza.html", {"pv": {"esito": "verificato", "fonti": [], "previsioni": [p]}})
    assert "Affidabilità: bassa" in html and "is-avviso" in html and "Storia: 10 mesi" in html
