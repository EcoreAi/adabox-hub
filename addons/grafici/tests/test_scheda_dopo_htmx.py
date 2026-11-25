"""La card di un grafico salvato rimandata da HTMX (periodo, «Filtra», «Aggiorna»), che sostituisce quella di prima.

Il tema tiene le card a opacity 0 finché non hanno .is-revealed, e le righe delle tabelle invisibili finché la tabella
non ha .is-revealed: le aggiunge ui.js solo al caricamento della pagina. La card arrivata dopo restava invisibile
(sulla dashboard: un buco al posto del grafico, appena premuto «Anno scorso»). Chi rimanda un frammento la scrive già
visibile, come fanno gli altri frammenti del progetto; al caricamento della pagina resta la comparsa graduale."""
import datetime
import re

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import Azienda
from grafici.models import Grafico
from todo.models import Attivita

pytestmark = pytest.mark.django_db

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def capo(client):
    utente = User.objects.create_superuser("capo", "capo@example.com", "x")
    Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="Alfa", stato="aperta", scadenza=datetime.date.today())
    client.force_login(utente)
    return utente


def _classi(html, selettore):
    """Le classi di ogni elemento che ha `selettore` tra le sue (es. "ui-card")."""
    return [c.split() for c in re.findall(r'class="([^"]*)"', html) if selettore in c.split()]


def _grafico(utente, tipo=Grafico.BARRE):
    if tipo == Grafico.TABELLA:
        spec = {"tipo": "tabella", "vista": "todo.attivita", "testo": "", "filtri": {}, "ordina": "titolo", "campi": [], "limite": 50}
    else:
        spec = {"vista": "todo.attivita", "per": "scadenza:mese", "misura": "count"}
    return Grafico.objects.create(utente=utente, titolo="Scadenze", tipo=tipo, spec=spec)


def test_dopo_un_periodo_la_card_e_la_sua_tabella_si_vedono(client, capo):
    g = _grafico(capo)
    html = client.post(reverse("grafici:grafico_periodo", args=[g.pk]), {"periodo": "anno"}, **HTMX).content.decode()
    assert f'id="an-widget-{g.pk}"' in html
    assert _classi(html, "ui-card") and all("is-revealed" in c for c in _classi(html, "ui-card"))
    assert _classi(html, "ui-table") and all("is-revealed" in c for c in _classi(html, "ui-table"))   # quella di «Tabella»


@pytest.mark.parametrize("tipo", [Grafico.BARRE, Grafico.TABELLA])
def test_dopo_aggiorna_la_card_si_vede(client, capo, tipo):
    g = _grafico(capo, tipo)
    html = client.post(reverse("grafici:grafico_aggiorna", args=[g.pk]), **HTMX).content.decode()
    assert _classi(html, "ui-card") and all("is-revealed" in c for c in _classi(html, "ui-card"))
    assert _classi(html, "ui-table") and all("is-revealed" in c for c in _classi(html, "ui-table"))


def test_al_caricamento_della_pagina_le_card_entrano_come_prima(client, capo):
    """Nella pagina intera ci pensa ui.js, con la comparsa graduale: il template non le scrive già visibili."""
    g = _grafico(capo)
    from grafici import motore
    pagina = motore.nuova_pagina(capo, "Prova")
    motore.metti_in(capo, str(pagina.pk), g, "", None)
    html = client.get(reverse("grafici:pagina", args=[pagina.pk])).content.decode()
    sezione = html[html.index(f'id="an-widget-{g.pk}"'):]
    assert "ui-card wd-card" in sezione and "is-revealed" not in sezione.split("</section>", 1)[0]
