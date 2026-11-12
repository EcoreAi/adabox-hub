"""Conoscenza: ricerca che filtra prima di classificare, pagine dei PDF, stato dei documenti nell'indice, riassunti,
verifica delle citazioni e valutazione della ricerca."""
import io
import json

import pytest
from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile

from ai import conoscenza, motore, valutazione, verifica
from ai.gateway import finto
from ai.models import AnelloCatena, Conversazione, Frammento, IndiceDocumento, Modello, Profilo, Provider, Turno
from ai.strumenti import conoscenza as strumenti_conoscenza
from ai.tests.test_conoscenza import _contesto, con_servizio, scena, vettore_finto  # noqa: F401 (fixture)
from core.models import Azienda

con_documenti = pytest.mark.skipif("documenti" not in settings.ADDONS_ATTIVI, reason="serve l'app documenti")
con_wiki = pytest.mark.skipif("wiki" not in settings.ADDONS_ATTIVI, reason="serve l'app wiki")


def pdf(pagine):
    """Un PDF vero, una pagina per testo ("" = pagina senza testo, come una scansione)."""
    oggetti = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    figli = []
    for testo in pagine:
        flusso = f"BT /F1 11 Tf 50 750 Td ({testo}) Tj ET" if testo else ""
        oggetti.append(f"<< /Length {len(flusso)} >>\nstream\n{flusso}\nendstream")
        oggetti.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                       f"/Contents {len(oggetti)} 0 R >>")
        figli.append(f"{len(oggetti)} 0 R")
    oggetti[1] = f"<< /Type /Pages /Kids [{' '.join(figli)}] /Count {len(figli)} >>"
    uscita, posizioni = io.BytesIO(), []
    uscita.write(b"%PDF-1.4\n")
    for n, corpo in enumerate(oggetti, start=1):
        posizioni.append(uscita.tell())
        uscita.write(f"{n} 0 obj\n{corpo}\nendobj\n".encode("latin-1"))
    inizio = uscita.tell()
    uscita.write(f"xref\n0 {len(oggetti) + 1}\n0000000000 65535 f \n".encode())
    for p in posizioni:
        uscita.write(f"{p:010d} 00000 n \n".encode())
    uscita.write(f"trailer\n<< /Size {len(oggetti) + 1} /Root 1 0 R >>\nstartxref\n{inizio}\n%%EOF\n".encode())
    return uscita.getvalue()


def _modello_finto(*compiti):
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    for compito in compiti:
        AnelloCatena.objects.create(profilo=Profilo.objects.create(nome=compito, compito=compito), modello=modello)
    return modello


@pytest.fixture
def archivio(scena, settings, tmp_path):
    from documenti.models import Cartella
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    return Cartella.objects.create(azienda=scena["azienda"], nome="Contratti")


# ---------- ricerca: app e permessi prima di tagliare la classifica

def _frammento(obj, testo, chiave=""):
    return Frammento.objects.create(fonte=Frammento.RECORD, content_type=ContentType.objects.get_for_model(obj),
                                    object_id=obj.pk, chiave=chiave, azienda_id=1, titolo=f"«{obj}»", testo=testo,
                                    impronta="x")


def test_i_non_visibili_in_testa_non_nascondono_i_visibili(scena):
    """100 record più pertinenti ma non visibili davanti a quello visibile: prima ne restavano fuori i 64 in testa."""
    aziende = [Azienda.objects.create(nome=f"Riservata {i}") for i in range(100)]
    for a in aziende:
        _frammento(a, "procedura resi rimborso cliente reso merce")
    visibile = Azienda.objects.create(nome="Visibile")
    _frammento(visibile, "procedura resi")
    nascosti = {a.pk for a in aziende}
    trovati = conoscenza.cerca("procedura resi rimborso cliente reso merce", scena["capo"], scena["azienda"],
                               visibile=lambda f: f.object_id not in nascosti)
    assert [f.object_id for f, _ in trovati] == [visibile.pk]


@con_wiki
def test_chiedi_alla_wiki_trova_la_pagina_anche_sotto_tanti_record(scena):
    from wiki.models import PaginaWiki, SpazioWiki
    for i in range(80):
        _frammento(Azienda.objects.create(nome=f"Cliente resi {i}"), "resi rimborso procedura reso cliente")
    spazio = SpazioWiki.objects.create(azienda=scena["azienda"], nome="Procedure")
    pagina = PaginaWiki.objects.create(azienda=scena["azienda"], spazio=spazio, titolo="Resi",
                                       testo="# Rimborso\nIl reso si rimborsa entro 14 giorni.")
    conoscenza.indicizza_record(ContentType.objects.get_for_model(PaginaWiki).pk, pagina.pk)
    c = _contesto(scena["capo"], scena["azienda"])
    c.conversazione.ambito = "wiki"
    risultati = strumenti_conoscenza.cerca_conoscenza(c, "resi rimborso procedura reso cliente")["risultati"]
    assert risultati and all(r["vista"] == "wiki.pagine" for r in risultati)
    assert risultati[0]["url"].endswith("#rimborso")


def test_permessi_controllati_a_blocchi(scena, django_assert_max_num_queries):
    aziende = [Azienda.objects.create(nome=f"Cliente {i}") for i in range(60)]
    for a in aziende:
        _frammento(a, "listino prezzi sconto")
    c = _contesto(User.objects.get(pk=scena["capo"].pk), scena["azienda"])
    visibile = strumenti_conoscenza._visibilita(c)
    frammenti = list(Frammento.objects.all())
    visibile.prepara(frammenti)
    with django_assert_max_num_queries(0):                    # già tutto in cache, una query per tipo di record
        assert all(visibile(f) for f in frammenti)


# ---------- documenti: pagine, stato, riassunti

@con_documenti
def test_pdf_a_pagine_con_il_link_alla_pagina(scena, archivio, con_servizio, client):
    from documenti import servizi
    d = servizi.carica(archivio, ContentFile(pdf(["Premessa generale del contratto.", "Il canone annuo e di 1200 euro.",
                                                  "Recesso con preavviso di 60 giorni."]), name="contratto.pdf"), scena["capo"])
    conoscenza.indicizza_documento(d.pk)
    pagine = dict(Frammento.objects.filter(object_id=d.pk, fonte="documento").values_list("pagina", "titolo"))
    assert pagine == {1: "Documento «contratto.pdf», p. 1", 2: "Documento «contratto.pdf», p. 2",
                      3: "Documento «contratto.pdf», p. 3"}
    indice = IndiceDocumento.objects.get(documento_id=d.pk)
    assert (indice.stato, indice.pagine, indice.frammenti) == ("indicizzato", 3, 3)
    c = _contesto(scena["capo"], scena["azienda"])
    trovato = strumenti_conoscenza.cerca_conoscenza(c, "preavviso recesso", fonti=["documento"])["risultati"][0]
    assert trovato["pagina"] == 3 and trovato["url"].endswith(f"/{d.pk}/?pagina=3")
    letto = strumenti_conoscenza.leggi_documento(c, d.pk, pagina_pdf=2)
    assert letto["testo"].startswith("[pagina 2]\nIl canone") and "[pagina 3]" in letto["testo"]
    assert "[pagina 1]" in strumenti_conoscenza.leggi_documento(c, d.pk)["testo"]
    client.force_login(scena["capo"])
    scheda = client.get(trovato["url"]).content.decode()
    assert "?inline=1#page=3" in scheda and "Per l'assistente" in scheda and "3 pagine" in scheda


@con_documenti
def test_stato_dei_documenti_che_l_assistente_non_legge(scena, archivio, client):
    from documenti import servizi
    scansione = servizi.carica(archivio, ContentFile(pdf(["", ""]), name="scansione.pdf"), scena["capo"])
    immagine = servizi.carica(archivio, ContentFile(b"\x89PNG....", name="foto.png"), scena["capo"])
    rotto = servizi.carica(archivio, ContentFile(b"non sono un pdf", name="rotto.pdf"), scena["capo"])
    conoscenza.indicizza()
    stati = dict(IndiceDocumento.objects.values_list("nome", "stato"))
    assert stati == {"scansione.pdf": "senza_testo", "foto.png": "non_supportato", "rotto.pdf": "illeggibile"}
    assert not Frammento.objects.filter(fonte="documento").exists()
    client.force_login(scena["capo"])
    assert "probabilmente è una scansione" in client.get(f"/documenti/documenti/{scansione.pk}/").content.decode()
    lista = client.get("/ai/indice/").content.decode()
    assert "scansione.pdf" in lista and "foto.png" in lista
    servizi.cestina([immagine])
    conoscenza.indicizza()
    assert not IndiceDocumento.objects.filter(documento_id=immagine.pk).exists()
    rotto.refresh_from_db()
    servizi.cestina([rotto])
    rotto.refresh_from_db()
    servizi.elimina([rotto])
    assert not IndiceDocumento.objects.filter(documento_id=rotto.pk).exists()


@con_documenti
def test_l_indice_mostra_solo_i_documenti_che_si_vedono(scena, archivio, client):
    from documenti import servizi
    from documenti.models import Cartella
    riservata = Cartella.objects.create(azienda=scena["azienda"], nome="Riservata")
    riservata.gruppi_lettura.add(Group.objects.create(name="Capi"))
    servizi.carica(archivio, ContentFile(b"Listino 2027.", name="listino.txt"), scena["capo"])
    servizi.carica(riservata, ContentFile(b"Stipendi.", name="stipendi.txt"), scena["capo"])
    conoscenza.indicizza()
    mario = User.objects.create_user("mario", password="x")
    mario.user_permissions.set(Permission.objects.filter(codename__in=["view_documento", "view_indicedocumento"]))
    mario.profilo.aziende.set([scena["azienda"]])
    mario.profilo.azienda_predefinita = scena["azienda"]
    mario.profilo.save()
    client.force_login(mario)
    lista = client.get("/ai/indice/").content.decode()
    assert "listino.txt" in lista and "stipendi.txt" not in lista


@con_documenti
def test_riassunto_del_documento_una_volta_per_testo(scena, archivio):
    from core import parametri
    from documenti import servizi
    _modello_finto("chat", "riassunti")
    d = servizi.carica(archivio, ContentFile(b"Contratto di manutenzione con Bianchi, rinnovo annuale.", name="bianchi.txt"),
                       scena["capo"])
    conoscenza.indicizza_documento(d.pk)
    assert not IndiceDocumento.objects.get(documento_id=d.pk).riassunto              # spenti di default
    parametri.scrivi("ai.riassunti_documenti", True)
    with finto.con_copione([["Argomento: manutenzione con Bianchi.\nPunti chiave: rinnovo annuale."]]) as chiamate:
        assert json.loads(conoscenza.indicizza_documento(d.pk))["riassunto"] == "fatto"
        assert json.loads(conoscenza.indicizza_documento(d.pk))["riassunto"] == "già fatto"
    assert len(chiamate) == 1 and "rinnovo annuale" in chiamate[0]["messaggi"][0]["testo"]
    riassunto = Frammento.objects.get(object_id=d.pk, chiave="riassunto")
    assert riassunto.titolo == "Documento «bianchi.txt», riassunto" and "manutenzione con Bianchi" in riassunto.testo
    assert Turno.objects.filter(compito="riassunto_documento", azienda=scena["azienda"]).count() == 1
    servizi.nuova_versione(d, ContentFile(b"Contratto chiuso a dicembre.", name="bianchi.txt"), scena["capo"])
    with finto.con_copione([[("errore", "AUTENTICAZIONE")]]):
        risultato = json.loads(conoscenza.indicizza_documento(d.pk))["riassunto"]
    assert risultato not in ("fatto", "già fatto")
    assert not Frammento.objects.filter(object_id=d.pk, chiave="riassunto").exists()   # il vecchio non vale più
    assert conoscenza.accoda_riassunti_arretrati() == 0                                  # fallito: non si riprova a vuoto


# ---------- verifica delle citazioni

def _turno_con_citazioni(scena, risposta, revisore=None):
    _modello_finto("chat", "classificazione")
    conversazione = Conversazione.objects.create(utente=scena["capo"])
    copione = [[("strumento", "cerca_conoscenza", {"domanda": "rinnovo contratto Bianchi disdetta"})], [risposta]]
    if revisore is not None:
        copione.append(revisore)
    with finto.con_copione(copione) as chiamate:
        turno = motore.avvia(conversazione, "Cosa dice il contratto di Bianchi?", scena["capo"], scena["azienda"])
    turno.refresh_from_db()
    return turno, chiamate


def _url_bianchi(scena):
    return f"/core/aziende/{scena['bianchi'].pk}/"


def test_citazioni_sostenute_verificate_senza_modello(scena, con_servizio):
    conoscenza.indicizza()
    url = _url_bianchi(scena)
    turno, chiamate = _turno_con_citazioni(
        scena, f"Il contratto di manutenzione si rinnova ogni anno a gennaio [1]({url}). Serve la disdetta con 60 "
               f"giorni di preavviso [1]({url}).")
    c = turno.provenienza["citazioni"]
    assert (c["totale"], c["verificate"], c["metodo"]) == (2, 2, "confronto locale")
    assert [(e["esito"], e["url"]) for e in c["elenco"]] == [("verificata", url)] * 2
    assert all(e["fonte"].startswith("Nota di capo") or "Bianchi" in e["fonte"] for e in c["elenco"])
    fonti = turno.provenienza["fonti"]                                   # le fonti citate, con il loro link
    assert fonti and all(f["url"] == url for f in fonti) and "Documenti e note" not in [f["titolo"] for f in fonti]
    assert not any(ch["sistema"] == verifica.SISTEMA for ch in chiamate)  # nessuna chiamata al revisore


def test_citazione_con_numero_sbagliato_va_al_revisore(scena, con_servizio):
    conoscenza.indicizza()
    url = _url_bianchi(scena)
    giudizio = json.dumps([{"n": 1, "esito": "non_sostenuta", "motivo": "la fonte dice 60 giorni, non 90"}])
    turno, chiamate = _turno_con_citazioni(
        scena, f"Il contratto si rinnova ogni anno a gennaio [1]({url}).\n- La disdetta va data 90 giorni prima [1]({url}).",
        [giudizio])
    c = turno.provenienza["citazioni"]
    assert (c["totale"], c["verificate"], c["non_sostenute"], c["metodo"]) == (2, 1, 1, "confronto locale e revisore")
    assert c["da_controllare"] == [{"frase": "La disdetta va data 90 giorni prima.", "esito": "non sostenuta",
                                    "motivo": "la fonte dice 60 giorni, non 90", "url": url}]
    revisione = next(ch for ch in chiamate if ch["sistema"] == verifica.SISTEMA)["messaggi"][0]["testo"]
    assert "AFFERMAZIONE: La disdetta va data 90 giorni prima" in revisione and "60 giorni di preavviso" in revisione
    assert Turno.objects.filter(compito="verifica_citazioni").count() == 1


def test_senza_revisore_la_citazione_dubbia_resta_incerta(scena, con_servizio, client):
    conoscenza.indicizza()
    url = _url_bianchi(scena)
    turno, _ = _turno_con_citazioni(scena, f"Bianchi ha chiesto uno sconto del 15% sulla manutenzione [1]({url}).",
                                    [("errore", "AUTENTICAZIONE")])
    c = turno.provenienza["citazioni"]
    assert (c["totale"], c["verificate"], c["incerte"]) == (1, 0, 1)
    assert "15" in c["da_controllare"][0]["motivo"]
    client.force_login(scena["capo"])
    pagina = client.get(f"/ai/chat/{turno.conversazione_id}/").content.decode()
    assert "0 su 1 citazione verificata" in pagina and "Controlla le frasi non verificate" in pagina


def test_link_non_restituiti_dagli_strumenti_non_sono_citazioni(scena, con_servizio):
    conoscenza.indicizza()
    turno, _ = _turno_con_citazioni(scena, "Vedi l'ordine [S00012](/vendite/ordini/12/) per i dettagli del contratto.")
    assert "citazioni" not in turno.provenienza


def test_verifica_spenta(scena, con_servizio):
    from core import parametri
    parametri.scrivi("ai.verifica_citazioni", False)
    conoscenza.indicizza()
    turno, _ = _turno_con_citazioni(scena, f"Si rinnova ogni anno a gennaio [1]({_url_bianchi(scena)}).")
    assert "citazioni" not in turno.provenienza


def test_frasi_citate_e_giudizi():
    fonti = {"/a/1/": [{"testo": "x", "vettore": None}]}
    frasi = verifica.frasi_citate("**Rinnovo**: ogni anno a gennaio [1](/a/1/#rinnovo). Altro senza fonte.\n"
                                  "1. Preavviso di 60 giorni [2](/a/1/?pagina=2)", fonti)
    assert frasi == [("Rinnovo: ogni anno a gennaio.", ["/a/1/#rinnovo"]), ("Preavviso di 60 giorni", ["/a/1/?pagina=2"])]
    assert verifica._leggi_giudizi('Ecco: [{"n": 2, "esito": "incerta", "motivo": "vago"}]', 2) == [
        None, {"esito": "incerta", "motivo": "vago"}]
    assert verifica._leggi_giudizi("non so", 1) is None
    tagliata = '[{"n": 1, "esito": "sostenuta", "motivo": ""}, {"n": 2, "esito": "inc'
    assert verifica._leggi_giudizi(tagliata, 2) == [{"esito": "verificata", "motivo": ""}, None]
    assert verifica.frasi_citate("È solo una bozza ([1](/a/1/)).", fonti) == [("È solo una bozza.", ["/a/1/"])]


# ---------- valutazione

def test_valutazione_della_ricerca(scena, con_servizio, tmp_path, capsys):
    from django.core.management import call_command
    conoscenza.indicizza()
    domande = [{"domanda": "quando si può dare disdetta del contratto di Bianchi?", "fonte": "Bianchi Srl"},
               {"domanda": "proroga manutenzione", "fonte": "Bianchi"},
               {"domanda": "fattura di ottobre", "fonte": "Inesistente"}]
    righe, riepilogo = valutazione.valuta_ricerca(domande, scena["capo"], scena["azienda"])
    assert [r["posizione"] for r in righe][:2] == [1, 1] and righe[2]["posizione"] is None
    assert riepilogo["trovate"] == 2 and riepilogo["totale"] == 3
    file = tmp_path / "ricerca.json"
    file.write_text(json.dumps(domande[:2]), encoding="utf-8")
    call_command("ai_eval", "--ricerca", "--file", str(file))
    assert "Trovate 2 su 2" in capsys.readouterr().out


def test_domanda_d_oro_con_fonte_e_citazioni(scena, con_servizio):
    _modello_finto("chat")
    conoscenza.indicizza()
    url = _url_bianchi(scena)
    domanda = {"domanda": "Cosa dice il contratto di Bianchi sul rinnovo?", "strumenti": ["cerca_conoscenza"],
               "fonte": "Bianchi", "citazioni_verificate": True,
               "copione": [[["strumento", "cerca_conoscenza", {"domanda": "rinnovo contratto Bianchi"}]],
                           [f"Il contratto di manutenzione si rinnova ogni anno a gennaio [1]({url})."]]}
    r, = valutazione.valuta([domanda], scena["capo"], scena["azienda"], copioni=True)
    assert r["ok"], r["problemi"]
    sbagliata = {**domanda, "fonte": "Rossi", "copione": [domanda["copione"][0], ["Si rinnova a gennaio."]]}
    r, = valutazione.valuta([sbagliata], scena["capo"], scena["azienda"], copioni=True)
    assert "fonte «Rossi» non trovata da cerca_conoscenza" in r["problemi"]
    assert "nessuna citazione della conoscenza nella risposta" in r["problemi"]


# ---------- la fonte di una citazione accanto alla chat

def _risposta_con_citazione(scena, domanda, risposta):
    from ai.models import MessaggioChat
    _modello_finto("chat", "classificazione")
    conversazione = Conversazione.objects.create(utente=scena["capo"])
    with finto.con_copione([[("strumento", "cerca_conoscenza", domanda)], [risposta]]):
        motore.avvia(conversazione, "domanda", scena["capo"], scena["azienda"])
    return MessaggioChat.objects.get(conversazione=conversazione, ruolo="assistente")


@con_documenti
def test_fonte_di_un_pdf_con_il_passaggio_evidenziato(scena, archivio, con_servizio, client):
    from documenti import servizi
    d = servizi.carica(archivio, ContentFile(pdf(["Premessa generale del contratto.", "Il canone annuo e di 1200 euro.",
                                                  "Recesso con preavviso di 60 giorni."]), name="contratto.pdf"), scena["capo"])
    conoscenza.indicizza_documento(d.pk)
    url = f"/documenti/documenti/{d.pk}/?pagina=3"
    m = _risposta_con_citazione(scena, {"domanda": "preavviso recesso", "fonti": ["documento"]},
                                f"Il recesso richiede 60 giorni di preavviso [1]({url}).")
    client.force_login(scena["capo"])
    pagina = client.get(f"/ai/fonte/{m.pk}/", {"url": url}).content.decode()
    assert "contratto.pdf" in pagina and "Pagina 1" in pagina and "Pagina 3" in pagina
    assert "<mark>Recesso con preavviso di 60 giorni.</mark>" in pagina and "<mark>Premessa" not in pagina
    assert client.get(f"/ai/fonte/{m.pk}/", {"url": "/vendite/ordini/12/"}).status_code == 404
    chat = client.get(f"/ai/chat/{m.conversazione_id}/").content.decode()
    assert 'id="ai-fonte"' in chat and f'data-url-fonte="/ai/fonte/0/"' in chat


def test_fonte_di_un_record_e_permessi(scena, con_servizio, client):
    conoscenza.indicizza()
    url = _url_bianchi(scena)
    m = _risposta_con_citazione(scena, {"domanda": "rinnovo contratto Bianchi disdetta"},
                                f"Si rinnova ogni anno a gennaio [1]({url}).")
    client.force_login(scena["capo"])
    pagina = client.get(f"/ai/fonte/{m.pk}/", {"url": url}).content.decode()
    assert "Bianchi Srl" in pagina and "<mark>Il contratto di manutenzione si rinnova" in pagina
    assert "Chiamato per la fattura di ottobre." in pagina                 # le altre note del record, non evidenziate
    altro = User.objects.create_user("altro", password="x")
    altro.user_permissions.set(Permission.objects.filter(codename="view_conversazione"))
    client.force_login(altro)
    assert client.get(f"/ai/fonte/{m.pk}/", {"url": url}).status_code == 404       # la chat è di un altro
