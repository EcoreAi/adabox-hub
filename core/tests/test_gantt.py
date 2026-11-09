"""Vista Gantt: barre nella finestra di mesi, tagli ai bordi, senza fine fino al bordo, selettore delle viste."""
import datetime

import pytest
from django.contrib.auth.models import User

from core.models import Azienda
from progetti.models import Progetto

OGGI = datetime.date.today()


@pytest.mark.django_db
def test_gantt_dei_progetti(client):
    azienda = Azienda.objects.get(pk=1)
    Progetto.objects.create(azienda=azienda, nome="Sito", inizio=OGGI - datetime.timedelta(days=10), fine=OGGI + datetime.timedelta(days=20))
    Progetto.objects.create(azienda=azienda, nome="Senza fine", inizio=OGGI)
    Progetto.objects.create(azienda=azienda, nome="Vecchio", inizio=OGGI.replace(year=OGGI.year - 3), fine=OGGI.replace(year=OGGI.year - 3))
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get("/progetti/progetti/gantt/").content.decode()
    assert "Sito" in html and "Senza fine" in html and "Vecchio" not in html and "gt-oggi" in html and "is-dopo" in html
    assert "/progetti/progetti/gantt/" in client.get("/progetti/progetti/").content.decode()
    assert client.get("/progetti/progetti/gantt/?da=2020-01").status_code == 200
