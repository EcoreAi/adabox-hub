"""Le voci di «Forma» nel costruttore dei grafici (Barre, Barre orizzontali, Linee…): con la classe .an-tipo prendevano
anche le regole del bollino del tipo nella libreria (una pillola alta 22px con lo sfondo colorato), e il riquadro della
voce, più alto, ne usciva. Si calcola la cascata vera sulla pagina resa (grafici.tests.aiuti.cascata)."""
import pytest
from django.urls import reverse

from grafici.tests.aiuti import cascata

pytestmark = pytest.mark.django_db

TRASPARENTE = {"", "transparent", "none", "rgba(0,0,0,0)"}


@pytest.fixture
def forme(client, superuser):
    client.force_login(superuser)
    radice, valore = cascata(client.get(reverse("grafici:costruttore")).content.decode())
    voci = [el.parent for el in radice.query_all('input[type="radio"][name="tipo"]')]
    assert len(voci) >= 6
    return voci, valore


def test_la_voce_non_e_una_pillola_alta_22px(forme):
    voci, valore = forme
    for voce in voci:
        assert voce.etree_element.tag == "label"
        assert valore(voce, "height") is None                       # alta quanto il suo riquadro
        assert (valore(voce, "background-color", "background") or "").replace(" ", "") in TRASPARENTE
        assert valore(voce, "display") == "flex"                    # il riquadro la riempie: voci di una riga alte uguali


def test_il_riquadro_della_voce_riempie_l_etichetta(forme):
    voci, valore = forme
    riquadro = next(voce.query_all("span") for voce in voci)
    riquadro = next(riquadro)
    assert valore(riquadro, "flex") == "1" and valore(riquadro, "border") and valore(riquadro, "align-items") == "center"


def test_il_bollino_della_libreria_resta_com_era(client, superuser):
    """L'altro uso di .an-tipo: il tipo di ogni grafico nella libreria di Statistiche."""
    from grafici.models import Grafico
    Grafico.objects.create(utente=superuser, titolo="Prova", tipo=Grafico.BARRE, spec={"vista": "todo.attivita", "per": "stato", "misura": "count"})
    client.force_login(superuser)
    radice, valore = cascata(client.get(reverse("grafici:pagine")).content.decode())
    bollino = next(radice.query_all("span.an-tipo"))
    assert valore(bollino, "height") == "22px" and valore(bollino, "border-radius") == "999px"
