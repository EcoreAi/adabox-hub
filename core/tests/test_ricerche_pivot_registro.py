"""Ricerche salvate, ricerca in tutte le app, pivot e registro delle modifiche: sempre con permessi e azienda."""
import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from acquisti.models import OrdineAcquisto
from contatti.models import Contatto
from core import registro
from core.models import Azienda, Lavoro, RegistroModifica, RicercaSalvata
from core.viste import salvate
from todo.models import Attivita

pytestmark = pytest.mark.django_db
LISTA = "/todo/attivita/"


def _utente(nome, azienda, *permessi):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(codename__in=permessi))
    u.profilo.aziende.set([azienda] if azienda else [])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(client):
    a, b = Azienda.objects.first(), Azienda.objects.create(nome="Azienda B")
    u = _utente("mario", a, "view_attivita", "add_attivita", "change_attivita", "view_contatto")
    client.force_login(u)
    return {"a": a, "b": b, "u": u}


def _salva(client, nome="Aperte", parametri="f_stato=aperta&q=x", **extra):
    return client.post(reverse("core:ricerca_salva"), {"vista": "todo.attivita", "nome": nome, "parametri": parametri, **extra})


# --- ricerche salvate ---

def test_salvo_e_ritrovo_la_ricerca(client, s):
    assert _salva(client).status_code == 302
    r = RicercaSalvata.objects.get()
    assert r.utente == s["u"] and r.azienda == s["a"] and r.vista == "todo.attivita" and r.parametri == "f_stato=aperta&q=x"
    assert "Aperte" in client.get(LISTA).content.decode()


def test_solo_ricerca_filtri_ordine_e_gruppo_si_salvano():
    assert salvate.pulisci("q=a&f_stato=b&g=c&o=d&p=3&partial=1&altro=x&formato=csv") == "q=a&f_stato=b&g=c&o=d"


def test_lo_stesso_nome_aggiorna(client, s):
    _salva(client)
    _salva(client, parametri="q=nuovo")
    assert RicercaSalvata.objects.get().parametri == "q=nuovo"


def test_una_vista_che_non_posso_vedere_non_si_salva(client, s):
    assert client.post(reverse("core:ricerca_salva"), {"vista": "acquisti.ordini", "nome": "X", "parametri": ""}).status_code == 404
    assert client.post(reverse("core:ricerca_salva"), {"vista": "inesistente.x", "nome": "X"}).status_code == 404
    assert not RicercaSalvata.objects.exists()


def test_personale_condivisa_e_altra_azienda(client, s):
    collega = _utente("collega", s["a"], "view_attivita")
    esterno = _utente("esterno", s["b"], "view_attivita")
    _salva(client, nome="PERSONALE")
    _salva(client, nome="CONDIVISA", condivisa="1")
    client.get(LISTA)                                           # consuma i messaggi «salvata»
    client.force_login(collega)
    pagina = client.get(LISTA).content.decode()
    assert "CONDIVISA" in pagina and "PERSONALE" not in pagina
    client.force_login(esterno)
    pagina = client.get(LISTA).content.decode()
    assert "CONDIVISA" not in pagina and "PERSONALE" not in pagina


def test_solo_il_proprietario_elimina(client, s):
    _salva(client, condivisa="1")
    r = RicercaSalvata.objects.get()
    client.force_login(_utente("collega", s["a"], "view_attivita"))
    assert client.post(reverse("core:ricerca_elimina", args=[r.pk])).status_code == 404
    assert client.post(reverse("core:ricerca_predefinita", args=[r.pk])).status_code == 404
    assert RicercaSalvata.objects.exists()
    client.force_login(s["u"])
    assert client.post(reverse("core:ricerca_elimina", args=[r.pk])).status_code == 302
    assert not RicercaSalvata.objects.exists()


def test_la_predefinita_si_apre_da_sola_e_si_puo_uscire(client, s):
    _salva(client, nome="A", parametri="q=a")
    _salva(client, nome="B", parametri="q=b")
    a, b = RicercaSalvata.objects.get(nome="A"), RicercaSalvata.objects.get(nome="B")
    client.post(reverse("core:ricerca_predefinita", args=[a.pk]))
    client.post(reverse("core:ricerca_predefinita", args=[b.pk]))
    a.refresh_from_db(), b.refresh_from_db()
    assert not a.predefinita and b.predefinita                  # una sola per lista
    r = client.get(LISTA)
    assert r.status_code == 302 and r.url.endswith("?q=b")
    assert client.get(LISTA + "?tutti=1").status_code == 200
    client.post(reverse("core:ricerca_predefinita", args=[b.pk]))
    assert client.get(LISTA).status_code == 200


def test_senza_azienda_niente_ricerche(client, s):
    _salva(client, nome="RICERCAX")
    client.get(LISTA)                                           # consuma il messaggio «salvata»
    u = s["u"]
    u.profilo.aziende.clear()
    u.profilo.azienda_predefinita = None
    u.profilo.save()
    client.force_login(u)
    assert "RICERCAX" not in client.get(LISTA).content.decode()
    _salva(client, nome="Y")
    assert RicercaSalvata.objects.count() == 1


# --- ricerca in tutte le app ---

def test_cerca_in_piu_app_con_permessi_e_azienda(client, s):
    Attivita.objects.create(azienda=s["a"], titolo="PAROLARARA nostra")
    Attivita.objects.create(azienda=s["b"], titolo="PAROLARARA altrui")
    Contatto.objects.create(azienda=s["a"], nome="PAROLARARA Srl")
    Contatto.objects.create(azienda=s["b"], nome="PAROLARARA Concorrente")
    fornitore = Contatto.objects.create(azienda=s["a"], nome="Forn")
    OrdineAcquisto.objects.create(azienda=s["a"], fornitore=fornitore, numero="PAROLARARA-ORD")
    pagina = client.get("/cerca/", {"q": "parolarara"}).content.decode()
    assert "PAROLARARA nostra" in pagina and "PAROLARARA Srl" in pagina
    assert "altrui" not in pagina and "Concorrente" not in pagina
    assert "PAROLARARA-ORD" not in pagina                       # senza il permesso sugli ordini


def test_cerca_senza_azienda_non_trova_nulla(client, s):
    Attivita.objects.create(azienda=s["a"], titolo="PAROLARARA")
    client.force_login(_utente("senza", None, "view_attivita"))
    assert "PAROLARARA" not in client.get("/cerca/", {"q": "parolarara"}).content.decode().replace('value="parolarara"', "")


def test_cerca_testo_corto_e_login(client, s):
    assert "almeno due caratteri" in client.get("/cerca/", {"q": "a"}).content.decode()
    client.logout()
    assert client.get("/cerca/", {"q": "abc"}).status_code == 302


# --- pivot ---

@pytest.fixture
def ordini(s):
    f1 = Contatto.objects.create(azienda=s["a"], nome="Rossi", fornitore=True)
    f2 = Contatto.objects.create(azienda=s["a"], nome="Bianchi", fornitore=True)
    f3 = Contatto.objects.create(azienda=s["b"], nome="ALTRUI", fornitore=True)
    for f, stato, n in ((f1, "bozza", "1"), (f1, "bozza", "2"), (f1, "confermato", "3"), (f2, "bozza", "4")):
        OrdineAcquisto.objects.create(azienda=s["a"], fornitore=f, numero=n, stato=stato)
    OrdineAcquisto.objects.create(azienda=s["b"], fornitore=f3, numero="9", stato="bozza")
    s["u"].user_permissions.add(Permission.objects.get(codename="view_ordineacquisto"))
    return s


def test_pivot_righe_colonne_totali_e_azienda(client, ordini):
    client.force_login(User.objects.get(pk=ordini["u"].pk))
    r = client.get("/acquisti/ordini/pivot/", {"riga": "fornitore", "colonna": "stato", "misura": "count"})
    d = r.context["dati"]
    righe = {x["etichetta"]: x for x in d["righe"]}
    assert set(righe) == {"Rossi", "Bianchi"} and "ALTRUI" not in r.content.decode()
    assert righe["Rossi"]["totali"] == [3] and righe["Bianchi"]["totali"] == [1] and d["totale"] == [4]
    i = d["colonne"].index("Bozza") if "Bozza" in d["colonne"] else 0
    assert righe["Rossi"]["celle"][i] == [2]
    assert sum(c[0] for c in d["totali_colonne"]) == 4


def test_pivot_rispetta_i_filtri_della_lista(client, ordini):
    client.force_login(User.objects.get(pk=ordini["u"].pk))
    d = client.get("/acquisti/ordini/pivot/", {"riga": "fornitore", "misura": "count", "f_stato": "confermato"}).context["dati"]
    assert d["totale"] == [1] and [x["etichetta"] for x in d["righe"]] == ["Rossi"]


def test_pivot_piu_misure_ed_excel(client, ordini):
    client.force_login(User.objects.get(pk=ordini["u"].pk))
    d = client.get("/acquisti/ordini/pivot/", {"riga": "fornitore", "misura": ["count", "sum:totale"]}).context["dati"]
    assert len(d["totale"]) == 2
    r = client.get("/acquisti/ordini/pivot/", {"riga": "fornitore", "misura": "count", "formato": "xlsx"})
    assert r.status_code == 200 and r["Content-Type"].endswith("spreadsheetml.sheet") and r.content[:2] == b"PK"


def test_pivot_assi_e_misure_non_ammessi_si_ignorano(client, ordini):
    client.force_login(User.objects.get(pk=ordini["u"].pk))
    r = client.get("/acquisti/ordini/pivot/", {"riga": "password", "colonna": "fornitore__password", "misura": "sum:password"})
    assert r.status_code == 200 and r.context["riga"] != "password" and r.context["colonna"] == "" and r.context["misure"] != ["sum:password"]


def test_pivot_senza_permesso_o_senza_azienda(client, ordini):
    client.force_login(_utente("nessuno", ordini["a"]))
    assert client.get("/acquisti/ordini/pivot/").status_code == 403
    client.force_login(_utente("senza", None, "view_ordineacquisto"))
    r = client.get("/acquisti/ordini/pivot/", {"riga": "fornitore"})
    assert r.status_code == 200 and "Rossi" not in r.content.decode()


def test_pivot_nel_selettore(client, ordini):
    client.force_login(User.objects.get(pk=ordini["u"].pk))
    assert "/acquisti/ordini/pivot/" in client.get("/acquisti/ordini/").content.decode()


# --- registro delle modifiche ---

def _voci(obj):
    return list(RegistroModifica.objects.filter(content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk).order_by("pk"))


def test_creazione_modifica_eliminazione(s):
    c = Contatto.objects.create(azienda=s["a"], nome="Rossi", citta="Roma")
    pk = c.pk
    c.citta = "Milano"
    c.save()
    c.save()                                                    # nessun cambiamento: nessuna riga
    voci = _voci(c)
    assert [v.azione for v in voci] == ["creato", "aggiornato"] and voci[0].azienda == s["a"]
    assert {"campo": "città", "prima": "Roma", "dopo": "Milano"} in voci[1].modifiche
    c.delete()
    assert RegistroModifica.objects.filter(object_id=pk, azione="eliminato", oggetto="Rossi").exists()


def test_le_relazioni_si_leggono_col_nome(s):
    f1, f2 = Contatto.objects.create(azienda=s["a"], nome="Rossi"), Contatto.objects.create(azienda=s["a"], nome="Bianchi")
    o = OrdineAcquisto.objects.create(azienda=s["a"], fornitore=f1, numero="1")
    o.fornitore = f2
    o.save()
    m = _voci(o)[-1].modifiche[0]
    assert m["prima"] == "Rossi" and m["dopo"] == "Bianchi"


def test_chi_e_da_dove_dalle_pagine(client, s):
    client.post("/todo/attivita/nuovo/", {"titolo": "Da pagina", "stato": "aperta"})
    a = Attivita.objects.get(titolo="Da pagina")
    v = _voci(a)[0]
    assert v.utente == s["u"] and v.utente_nome == "mario" and v.origine == "ui"


def test_chi_e_da_dove_dall_api(client, s):
    from core.models import TokenApi
    _, token = TokenApi.genera(s["u"], "t")
    client.logout()
    r = client.post("/api/v1/todo/attivita/", '{"titolo": "Da API", "stato": "aperta"}', content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 201
    v = _voci(Attivita.objects.get(titolo="Da API"))[0]
    assert v.origine == "api" and v.utente == s["u"]


def test_dal_lavoro_in_background(s):
    from core import lavori
    lavori.accoda("core.tests.test_ricerche_pivot_registro.lavoro_di_prova", azienda_id=s["a"].pk, utente=s["u"])
    v = _voci(Contatto.objects.get(nome="Dal lavoro"))[0]
    assert v.origine == "worker" and v.utente == s["u"]


def lavoro_di_prova(azienda_id):
    Contatto.objects.create(azienda_id=azienda_id, nome="Dal lavoro")


def test_senza_richiesta_e_sistema_e_l_origine_si_ripristina(s):
    c = Contatto.objects.create(azienda=s["a"], nome="X")
    assert _voci(c)[0].origine == "sistema"
    with registro.origine("ai", s["u"]):
        d = Contatto.objects.create(azienda=s["a"], nome="Y")
    assert _voci(d)[0].origine == "ai" and registro._autore.get() == (None, "sistema")


def test_i_segreti_non_entrano(s):
    from connettori.models import Webhook
    w = Webhook.objects.create(azienda=s["a"], nome="W", url="https://x.example.com/", eventi="*")
    w.nuovo_segreto()
    w.save()
    assert not [m for v in _voci(w) for m in v.modifiche if "segreto" in m["campo"].lower()]
    assert not any(n in str(_voci(w)) for n in ("gAAAA",))


def test_i_testi_lunghi_si_tagliano(s):
    c = Contatto.objects.create(azienda=s["a"], nome="X", note="a")
    c.note = "b" * 5000
    c.save()
    m = _voci(c)[-1].modifiche[0]
    assert len(m["dopo"]) == registro.LUNGHEZZA_VALORE


def test_le_righe_finiscono_sotto_il_documento(s):
    from acquisti.models import RigaAcquisto
    f = Contatto.objects.create(azienda=s["a"], nome="Rossi")
    o = OrdineAcquisto.objects.create(azienda=s["a"], fornitore=f, numero="1")
    r = RigaAcquisto.objects.create(ordine=o, descrizione="Vite", quantita=1, prezzo=2)
    r.quantita = 5
    r.save()
    ultima = _voci(o)[-1]
    assert ultima.azienda == s["a"] and any(m.get("riga") and m.get("campo") for m in ultima.modifiche)


def test_i_lavori_non_finiscono_nel_registro(s):
    Lavoro.objects.create(funzione="x.y", argomenti={})
    assert not RegistroModifica.objects.filter(content_type=ContentType.objects.get_for_model(Lavoro)).exists()


def test_salvataggio_annullato_non_lascia_righe(s):
    from django.db import transaction
    try:
        with transaction.atomic():
            Contatto.objects.create(azienda=s["a"], nome="ANNULLATO")
            raise ValueError
    except ValueError:
        pass
    assert not RegistroModifica.objects.filter(oggetto="ANNULLATO").exists()


def test_un_errore_del_registro_non_blocca_il_salvataggio(s, monkeypatch):
    from django.db import DatabaseError
    monkeypatch.setattr(RegistroModifica.objects, "create", lambda **k: (_ for _ in ()).throw(DatabaseError("giù")))
    c = Contatto.objects.create(azienda=s["a"], nome="Salvo")
    assert Contatto.objects.filter(pk=c.pk).exists()


def _admin(azienda):
    return _utente("revisore", azienda, "view_registromodifica", "view_contatto")


def test_pagina_del_registro_per_azienda_e_sola_lettura(client, s):
    Contatto.objects.create(azienda=s["a"], nome="NOSTRO")
    Contatto.objects.create(azienda=s["b"], nome="ALTRUI")
    assert client.get("/core/registro/").status_code == 403
    client.force_login(_admin(s["a"]))
    pagina = client.get("/core/registro/").content.decode()
    assert "NOSTRO" in pagina and "ALTRUI" not in pagina
    v = RegistroModifica.objects.filter(oggetto="NOSTRO").first()
    assert client.get(f"/core/registro/{v.pk}/").status_code == 200
    assert client.get(f"/core/registro/{v.pk}/modifica/").status_code == 403
    assert client.post(f"/core/registro/{v.pk}/elimina/").status_code == 403
    assert client.get("/core/registro/nuovo/").status_code == 403
    assert RegistroModifica.objects.filter(pk=v.pk).exists()


def test_storico_sul_dettaglio_solo_con_il_permesso(client, s):
    c = Contatto.objects.create(azienda=s["a"], nome="Rossi", citta="Roma")
    c.citta = "Milano"
    c.save()
    url = f"/contatti/contatti/{c.pk}/"
    assert "Storico delle modifiche" not in client.get(url).content.decode()
    client.force_login(_admin(s["a"]))
    pagina = client.get(url).content.decode()
    assert "Storico delle modifiche" in pagina and "Milano" in pagina



def test_un_nome_che_non_si_calcola_non_blocca_il_salvataggio(s, monkeypatch):
    monkeypatch.setattr(Contatto, "__str__", lambda self: 1 / 0)
    c = Contatto.objects.create(azienda=s["a"], nome="Rotto")
    assert Contatto.objects.filter(pk=c.pk).exists() and _voci(c)[0].oggetto == f"Contatto {c.pk}"


def test_cancellare_un_documento_con_le_righe_non_fallisce(s):
    from acquisti.models import RigaAcquisto
    f = Contatto.objects.create(azienda=s["a"], nome="Rossi")
    o = OrdineAcquisto.objects.create(azienda=s["a"], fornitore=f, numero="1")
    RigaAcquisto.objects.create(ordine=o, descrizione="Vite", quantita=1, prezzo=2)
    pk = o.pk
    o.delete()
    assert not OrdineAcquisto.objects.filter(pk=pk).exists()
    assert RegistroModifica.objects.filter(object_id=pk, azione="eliminato", content_type=ContentType.objects.get_for_model(OrdineAcquisto)).exists()


def test_il_registro_non_entra_nella_conoscenza_di_ada(s):
    from ai import conoscenza
    Contatto.objects.create(azienda=s["a"], nome="Rossi")
    assert RegistroModifica not in [v.model for v, _ in conoscenza._viste_indicizzabili()]
