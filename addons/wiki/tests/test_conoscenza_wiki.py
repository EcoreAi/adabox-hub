"""La wiki come base di conoscenza dell'assistente: pagine intere divise per sezioni, citazioni alla sezione, indice
aggiornato al salvataggio, «Chiedi alla wiki» e domande senza risposta."""
import pytest
from django.contrib.auth.models import Permission, User

from ai import conoscenza, markdown
from ai.models import Conversazione, Frammento
from ai.strumenti import Contesto
from ai.strumenti import conoscenza as strumenti_conoscenza
from core import chatter
from core.models import Azienda
from wiki.models import DomandaWiki, MembroWiki, PaginaWiki, SpazioWiki

pytestmark = pytest.mark.django_db

RESI = """Come si gestiscono i resi dei clienti.

# Autorizzazione
Il commerciale apre il reso dalla consegna e indica il motivo.

## Controllo merce
Il magazzino controlla i colli entro due giorni lavorativi.

# Rimborso
""" + ("Dopo il controllo l'amministrazione prepara la nota di credito parziale. " * 40) + """

Il rimborso con bonifico parte entro trenta giorni dalla nota di credito: la parola chiave è zibaldone.

```
# questo non è un titolo
```
"""


def _utente(nome, *permessi):
    u = User.objects.create_user(nome, f"{nome}@x.it", "x")
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_spaziowiki", "view_paginawiki", "add_paginawiki",
                                                                   "change_paginawiki", *permessi]))
    u.profilo.aziende.set([Azienda.objects.get(pk=1)])
    u.profilo.azienda_predefinita_id = 1
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def w(db):
    azienda = Azienda.objects.get(pk=1)
    anna, luca = _utente("anna", "add_conversazione"), _utente("luca")
    procedure = SpazioWiki.objects.create(azienda=azienda, nome="Procedure")
    hr = SpazioWiki.objects.create(azienda=azienda, nome="HR", aperto=False)
    MembroWiki.objects.create(spazio=hr, utente=anna, ruolo="legge")
    magazzino = PaginaWiki.objects.create(azienda=azienda, spazio=procedure, titolo="Magazzino", testo="Le procedure del magazzino.")
    resi = PaginaWiki.objects.create(azienda=azienda, spazio=procedure, padre=magazzino, titolo="Resi", testo=RESI)
    stipendi = PaginaWiki.objects.create(azienda=azienda, spazio=hr, titolo="Stipendi", testo="# Premi\nIl premio di produzione zibaldone.")
    return {"azienda": azienda, "anna": anna, "luca": luca, "resi": resi, "stipendi": stipendi, "magazzino": magazzino}


def _cerca(utente, azienda, domanda, ambito=""):
    contesto = Contesto(utente=utente, azienda=azienda, conversazione=Conversazione.objects.create(utente=utente, ambito=ambito))
    return strumenti_conoscenza.cerca_conoscenza(contesto, domanda)


# --- sezioni e ancore --------------------------------------------------------------------------------------------

def test_sezioni_con_percorso_ancore_e_codice():
    voci = markdown.sezioni(RESI)
    assert [(t, a) for t, a, _ in voci] == [([], ""), (["Autorizzazione"], "autorizzazione"),
                                             (["Autorizzazione", "Controllo merce"], "controllo-merce"), (["Rimborso"], "rimborso")]
    assert "# questo non è un titolo" in voci[-1][2]
    assert [a for _, a, _ in markdown.sezioni("# Note\nuno\n# Note\ndue\n# Più *chiaro*\ntre")] == ["note", "note-2", "piu-chiaro"]


def test_la_pagina_mostrata_ha_le_stesse_ancore():
    html = markdown.rendi("# Rimborso\nx\n## Controllo merce\ny\n# Rimborso\nz", ancore=True)
    assert 'id="rimborso"' in html and 'id="controllo-merce"' in html and 'id="rimborso-2"' in html
    assert "id=" not in markdown.rendi("# Rimborso\nx")                       # la chat di Ada resta com'era


def test_la_pagina_della_wiki_mostra_le_ancore(client, w):
    client.force_login(w["anna"])
    assert 'id="controllo-merce"' in client.get(f"/wiki/pagine/{w['resi'].pk}/").content.decode()


# --- indice ---------------------------------------------------------------------------------------------------------

def test_pagina_intera_divisa_per_sezioni_con_il_percorso(w):
    conoscenza.indicizza()
    pezzi = list(Frammento.objects.filter(object_id=w["resi"].pk, content_type__model="paginawiki").order_by("chiave"))
    assert len(pezzi) >= 5 and all(p.chiave for p in pezzi)                   # niente più un solo frammento troncato
    assert pezzi[1].titolo == "Pagina della wiki «Procedure › Magazzino › Resi › Autorizzazione»"
    assert any("zibaldone" in p.testo for p in pezzi)                          # anche la fine della pagina lunga
    assert all(p.testo.startswith("Procedure › Magazzino › Resi") for p in pezzi)


def test_la_risposta_cita_la_sezione_e_rispetta_gli_spazi(w):
    conoscenza.indicizza()
    luca = _cerca(w["luca"], w["azienda"], "zibaldone")["risultati"]
    assert [r["titolo"].split(",")[0] for r in luca] == ["Pagina della wiki «Procedure › Magazzino › Resi › Rimborso»"]
    assert luca[0]["url"].endswith(f"/wiki/pagine/{w['resi'].pk}/#rimborso")
    anna = _cerca(w["anna"], w["azienda"], "zibaldone")["risultati"]
    assert any("Stipendi" in r["titolo"] for r in anna)                        # anna è membro di HR


def test_salvare_o_eliminare_aggiorna_subito_l_indice(w, django_capture_on_commit_callbacks):
    conoscenza.indicizza()
    with django_capture_on_commit_callbacks(execute=True):
        w["magazzino"].testo = "# Inventario\nLa conta si fa il 31 dicembre con la squadra quadrifoglio."
        w["magazzino"].save()
    assert _cerca(w["luca"], w["azienda"], "quadrifoglio")["risultati"]
    with django_capture_on_commit_callbacks(execute=True):
        w["stipendi"].delete()
    assert not Frammento.objects.filter(content_type__model="paginawiki", object_id=w["stipendi"].pk).exists()


# --- Chiedi alla wiki ------------------------------------------------------------------------------------------------

def test_chiedi_alla_wiki_cerca_solo_nella_wiki_e_segna_le_domande_senza_risposta(w):
    chatter.scrivi(w["azienda"], w["anna"], "Nota sull'azienda: zibaldone.", tipo="nota")
    conoscenza.indicizza()
    assert all("Pagina della wiki" in r["titolo"] for r in _cerca(w["anna"], w["azienda"], "zibaldone", ambito="wiki")["risultati"])
    _cerca(w["luca"], w["azienda"], "orario della mensa aziendale", ambito="wiki")
    _cerca(w["luca"], w["azienda"], "aziendale orario mensa", ambito="wiki")          # stesse parole: stessa riga
    _cerca(w["luca"], w["azienda"], "parcheggio dei visitatori")                      # chat normale: non conta
    domanda, = DomandaWiki.objects.all()
    assert domanda.volte == 2 and domanda.domanda == "orario della mensa aziendale" and domanda.azienda == w["azienda"]


def test_la_pagina_chiedi_e_il_riquadro_mandano_la_domanda_all_assistente(client, w):
    client.force_login(w["anna"])
    html = client.get("/wiki/chiedi/").content.decode()
    assert 'action="/ai/chat/invia/"' in html and 'name="ambito" value="wiki"' in html
    assert 'name="ambito" value="wiki"' in client.get(f"/wiki/pagine/{w['resi'].pk}/").content.decode()
    client.force_login(w["luca"])                                                     # senza l'assistente
    assert "serve l'assistente" in client.get("/wiki/chiedi/").content.decode()
    assert 'name="ambito"' not in client.get(f"/wiki/pagine/{w['resi'].pk}/").content.decode()


def test_le_domande_senza_risposta_sono_dei_responsabili(client, w):
    DomandaWiki.objects.create(azienda=w["azienda"], domanda="Orari della mensa", chiave="x")
    client.force_login(w["luca"])
    assert client.get("/wiki/domande/").status_code == 403
    capo = _utente("capo", "view_domandawiki", "change_domandawiki")
    client.force_login(capo)
    assert "Orari della mensa" in client.get("/wiki/domande/").content.decode()
