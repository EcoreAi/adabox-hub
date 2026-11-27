"""Chat riservate nel ciclo della risposta: dopo una lettura riservata solo modelli locali (piano 2026-11-18)."""
import pytest
from django.contrib.auth.models import User

from ai import motore, riservatezza
from ai.gateway import finto
from ai.models import AnelloCatena, Conversazione, Modello, Profilo, Provider, Turno
from core import parametri
from core.models import Azienda

LETTURA = [("strumento", "aggrega_record", {"vista": "core.aziende"})]


@pytest.fixture
def s(base, monkeypatch):
    from ai.motore import titoli
    monkeypatch.setattr(titoli, "genera", lambda *a, **k: None)       # i titoli hanno il loro test (Task 4)
    return base


@pytest.fixture
def base(db):
    cloud_p = Provider.objects.create(nome="Cloud finto", tipo="finto", locale=False)
    locale_p = Provider.objects.create(nome="Locale finto", tipo="finto", locale=True)
    cloud = Modello.objects.create(provider=cloud_p, id_api="finto-cloud", etichetta="Cloud", sceglibile=True)
    locale = Modello.objects.create(provider=locale_p, id_api="finto-locale", etichetta="Locale")
    profilo = Profilo.objects.create(nome="Chat", compito="chat")
    AnelloCatena.objects.create(profilo=profilo, modello=cloud, ordine=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    azienda = Azienda.objects.get(pk=1)
    parametri.scrivi("ai.app_riservate", "core", azienda)
    return {"cloud": cloud, "locale": locale, "profilo": profilo, "capo": capo, "azienda": azienda}


def _turno(s, conversazione, copione):
    with finto.con_copione(copione) as chiamate:
        turno = motore.avvia(conversazione, "Quante aziende ci sono?", s["capo"], s["azienda"], sincrono=True)
    turno.refresh_from_db()
    conversazione.refresh_from_db()
    return turno, [c["modello"] for c in chiamate]


def test_dopo_una_lettura_riservata_risponde_il_locale(s):
    c = Conversazione.objects.create(utente=s["capo"])
    turno, modelli = _turno(s, c, [LETTURA, ["Sono una."]])
    assert modelli == ["finto-cloud", "finto-locale"]
    assert c.riservata and c.riservata_motivo == "app «core»"
    assert turno.stato == Turno.COMPLETATO


def test_senza_locale_si_ferma_senza_inviare(s):
    Provider.objects.filter(locale=True).update(attivo=False)
    c = Conversazione.objects.create(utente=s["capo"])
    turno, modelli = _turno(s, c, [LETTURA, ["Non devo arrivare qui."]])
    assert modelli == ["finto-cloud"]                     # il risultato riservato non è uscito
    assert turno.stato == Turno.ERRORE
    assert riservatezza.MESSAGGIO_SENZA_LOCALE in turno.testo


def test_locale_fuori_dalla_catena(s):
    """Il locale non è nella catena del profilo ma è attivo nell'istanza: si usa quello (Review Focus 2)."""
    c = Conversazione.objects.create(utente=s["capo"])
    _, modelli = _turno(s, c, [LETTURA, ["Una."]])
    assert modelli[-1] == "finto-locale"


def test_chat_riservata_ignora_il_modello_scelto(s, monkeypatch):
    from ai import funzioni
    monkeypatch.setattr(funzioni, "attiva", lambda nome: True)
    c = Conversazione.objects.create(utente=s["capo"], modello=s["cloud"], riservata=True, riservata_motivo="x")
    _, modelli = _turno(s, c, [["Rispondo io."]])
    assert modelli == ["finto-locale"]


def test_risultato_in_errore_non_rende_riservata(s):
    c = Conversazione.objects.create(utente=s["capo"])
    _, modelli = _turno(s, c, [[("strumento", "aggrega_record", {"vista": "core.inesistente"})], ["Non trovo."]])
    assert not c.riservata and modelli == ["finto-cloud", "finto-cloud"]


# --- Task 4: nessuna uscita dietro le quinte ---

from ai.models import Evento, MessaggioChat


def _riservata(base, **altro):
    return Conversazione.objects.create(utente=base["capo"], riservata=True, riservata_motivo="app «core»", **altro)


def _senza_locali():
    Provider.objects.filter(locale=True).update(attivo=False)


def test_titolo_di_chat_riservata_solo_in_locale(base):
    from ai.motore import titoli
    c = _riservata(base)
    MessaggioChat.objects.create(conversazione=c, ruolo=MessaggioChat.UTENTE, testo="Stipendio di Rossi?")
    MessaggioChat.objects.create(conversazione=c, ruolo=MessaggioChat.ASSISTENTE, testo="2.100 €")
    _senza_locali()
    with finto.con_copione([["Stipendi"]]) as chiamate:
        titoli.genera(c, base["capo"], base["azienda"])
    c.refresh_from_db()
    assert chiamate == [] and c.titolo == "Nuova chat"
    Provider.objects.filter(locale=True).update(attivo=True)
    with finto.con_copione([["Stipendi"]]) as chiamate:
        titoli.genera(c, base["capo"], base["azienda"])
    assert [x["modello"] for x in chiamate] == ["finto-locale"]


def test_compattazione_di_chat_riservata_in_locale(base):
    from ai.motore import compattazione
    c = _riservata(base)
    vecchio = Turno.objects.create(conversazione=c, utente=base["capo"], azienda=base["azienda"])
    Evento.objects.create(conversazione=c, turno=vecchio, tipo=Evento.UTENTE,
                          dati={"ruolo": "utente", "testo": "x" * (compattazione.SOGLIA + 10)})
    nuovo = Turno.objects.create(conversazione=c, utente=base["capo"], azienda=base["azienda"])
    Evento.objects.create(conversazione=c, turno=nuovo, tipo=Evento.UTENTE, dati={"ruolo": "utente", "testo": "e poi?"})
    with finto.con_copione([["Riassunto."]]) as chiamate:
        compattazione.se_serve(nuovo)
    assert [x["modello"] for x in chiamate] == ["finto-locale"]


def test_chat_riservata_senza_locale_non_chiama_nessuno(base):
    """Il blocco arriva prima di riassunto e risposta: nessuna chiamata al cloud."""
    _senza_locali()
    c = _riservata(base)
    with finto.con_copione([["No."]]) as chiamate:
        turno = motore.avvia(c, "Ancora?", base["capo"], base["azienda"], sincrono=True)
    turno.refresh_from_db()
    assert chiamate == [] and turno.stato == Turno.ERRORE
    assert riservatezza.MESSAGGIO_SENZA_LOCALE in turno.testo


def test_verifica_saltata_senza_locale(base):
    from ai import verifica
    _senza_locali()
    c = _riservata(base)
    turno = Turno.objects.create(conversazione=c, utente=base["capo"], azienda=base["azienda"])
    with finto.con_copione([["1. SUPPORTATA"]]) as chiamate:
        assert verifica._revisore(turno, [("Rossi guadagna 2.100 €.", "busta paga di Rossi: 2.100 €")]) is None
    assert chiamate == []


def test_riassunto_documento_riservato(base):
    from ai import conoscenza
    from ai.models import IndiceDocumento
    from documenti.models import Cartella, Documento
    cartella = Cartella.objects.create(azienda=base["azienda"], nome="Personale", riservata=True)
    d = Documento.objects.create(azienda=base["azienda"], cartella=cartella, nome="busta.pdf", proprietario=base["capo"])
    indice = IndiceDocumento.objects.create(documento_id=d.pk, azienda=base["azienda"], nome=d.nome,
                                            stato=IndiceDocumento.INDICIZZATO, impronta="a")
    _senza_locali()
    with finto.con_copione([["Riassunto."]]) as chiamate:
        conoscenza.riassumi(d, {"indice": indice, "testo": "Busta paga di Rossi: 2.100 €"})
    assert chiamate == []
    indice.impronta_riassunto = ""
    Provider.objects.filter(locale=True).update(attivo=True)
    with finto.con_copione([["Riassunto."]]) as chiamate:
        conoscenza.riassumi(d, {"indice": indice, "testo": "Busta paga di Rossi: 2.100 €"})
    assert [x["modello"] for x in chiamate] == ["finto-locale"]


def test_esperto_eredita_e_propaga(s):
    from ai.models import Assistente
    from ai.strumenti import Contesto
    from ai.strumenti.esperti import chiedi_esperto
    Assistente.objects.create(nome="Aziende")
    chiamante = Conversazione.objects.create(utente=s["capo"])
    turno = Turno.objects.create(conversazione=chiamante, utente=s["capo"], azienda=s["azienda"])
    contesto = Contesto(utente=s["capo"], azienda=s["azienda"], conversazione=chiamante, turno=turno)
    with finto.con_copione([LETTURA, ["Una azienda."]]):
        chiedi_esperto(contesto, "Aziende", "Quante aziende ci sono?")
    chiamante.refresh_from_db()
    assert chiamante.riservata and chiamante.riservata_motivo == "app «core»"
    interna = Conversazione.objects.filter(nascosta=True).latest("pk")
    with finto.con_copione([["Va bene."]]) as chiamate:
        chiedi_esperto(contesto, "Aziende", "E poi?")
    assert Conversazione.objects.filter(nascosta=True).latest("pk").riservata and interna.pk
    assert [x["modello"] for x in chiamate] == ["finto-locale"]


# --- Revisione finale: dati nel primo messaggio, aree, strumenti verso l'esterno, riassunti per app ---

@pytest.fixture
def sincroni(settings):
    settings.AI_TURNI_SINCRONI = True


def test_riassunto_di_record_riservato_in_locale(s, sincroni):
    from ai import aiuto_testi
    from core.viste import registry
    vista = registry.per_modello(Azienda)
    with finto.con_copione([["Riassunto."]]) as chiamate:
        turno = aiuto_testi.avvia_riassunto(s["capo"], s["azienda"], vista, s["azienda"])
    assert turno.conversazione.riservata and [c["modello"] for c in chiamate] == ["finto-locale"]


def test_scrivi_con_ada_con_record_riservato(client, s, sincroni):
    from django.contrib.contenttypes.models import ContentType
    from django.urls import reverse
    client.force_login(s["capo"])
    ct = ContentType.objects.get_for_model(Azienda)
    with finto.con_copione([["Testo."]]) as chiamate:
        r = client.post(reverse("ai:scrivi_con_ada", args=["libero"]),
                        {"testo": "", "istruzione": "Scrivi una nota", "record": f"{ct.pk}:{s['azienda'].pk}"})
    assert r.status_code == 200
    assert Conversazione.objects.latest("pk").riservata and [c["modello"] for c in chiamate] == ["finto-locale"]


def test_chiedi_ad_ada_su_pagina_riservata(client, s, sincroni):
    client.force_login(s["capo"])
    with finto.con_copione([["È la pagina delle aziende."]]) as chiamate:
        r = client.post("/askada/chiedi/", {"testo": "Cosa mostra?", "url": "/core/aziende/", "titolo": "Aziende",
                                            "pagina": "Adabox Hub, partita IVA 123"})
    assert r.status_code == 200
    assert Conversazione.objects.latest("pk").riservata and [c["modello"] for c in chiamate] == ["finto-locale"]


def test_area_con_cartella_riservata(s):
    from ai.models import ProgettoChat
    from documenti.models import Cartella
    cartella = Cartella.objects.create(azienda=s["azienda"], nome="Personale", riservata=True)
    area = ProgettoChat.objects.create(utente=s["capo"], azienda=s["azienda"], nome="HR", cartella_documenti=cartella.pk)
    c = Conversazione.objects.create(utente=s["capo"], progetto=area)
    _, modelli = _turno(s, c, [["Ciao."]])
    assert c.riservata and c.riservata_motivo == "cartella «Personale»" and modelli == ["finto-locale"]


def test_area_collegata_a_un_record_di_un_app_riservata(s):
    """La nota dell'area dice tipo e titolo dei record collegati e va al modello con il primo messaggio: se l'app del
    record è riservata la chat lo diventa prima di partire (prima il titolo arrivava a un modello cloud)."""
    from django.contrib.contenttypes.models import ContentType

    from ai.models import CollegamentoProgetto, ProgettoChat
    area = ProgettoChat.objects.create(utente=s["capo"], azienda=s["azienda"], nome="Capogruppo")
    CollegamentoProgetto.objects.create(progetto=area, content_type=ContentType.objects.get_for_model(Azienda), object_id=s["azienda"].pk)
    c = Conversazione.objects.create(utente=s["capo"], progetto=area)
    _, modelli = _turno(s, c, [["Ciao."]])
    assert c.riservata and c.riservata_motivo == "app «core»" and modelli == ["finto-locale"]


def test_strumenti_verso_l_esterno_tolti_nelle_chat_riservate(s):
    c = Conversazione.objects.create(utente=s["capo"])
    with finto.con_copione([LETTURA, ["Una."]]) as chiamate:
        motore.avvia(c, "Quante aziende?", s["capo"], s["azienda"], sincrono=True)
    dopo = chiamate[1]["strumenti"]                  # il web può essere spento nei test: copre anche senza_uscite
    assert not {"cerca_web", "leggi_pagina"} & set(dopo)
    assert not [n for n in dopo if n.startswith("mcp")]


def test_strumenti_web_tolti_dal_primo_passo(s, monkeypatch):
    from ai import riservatezza as r
    ammessi = {"cerca_web": 1, "leggi_pagina": 2, "mcp3_cerca": 3, "cerca_record": 4}
    assert set(r.senza_uscite(ammessi, Conversazione(riservata=True))) == {"cerca_record"}
    assert r.senza_uscite(ammessi, Conversazione()) == ammessi


def test_riassunto_documento_con_app_documenti_riservata(base):
    from ai import conoscenza
    from ai.models import IndiceDocumento
    from documenti.models import Cartella, Documento
    parametri.scrivi("ai.app_riservate", "documenti", base["azienda"])
    d = Documento.objects.create(azienda=base["azienda"], cartella=Cartella.objects.create(azienda=base["azienda"], nome="X"),
                                 nome="listino.pdf", proprietario=base["capo"])
    indice = IndiceDocumento.objects.create(documento_id=d.pk, azienda=base["azienda"], nome=d.nome,
                                            stato=IndiceDocumento.INDICIZZATO, impronta="a")
    with finto.con_copione([["Riassunto."]]) as chiamate:
        conoscenza.riassumi(d, {"indice": indice, "testo": "Listino riservato"})
    assert [x["modello"] for x in chiamate] == ["finto-locale"]


def test_riassunti_di_discuss_riservata_in_locale(base, monkeypatch):
    from discuss import ia
    monkeypatch.setattr(ia, "disponibile", lambda utente: True)
    parametri.scrivi("ai.app_riservate", "discuss", base["azienda"])
    with finto.con_copione([["Sintesi."]]) as chiamate:
        ia.genera("Riassumi.", "Messaggi del canale riservato", base["capo"], base["azienda"])
    assert [x["modello"] for x in chiamate] == ["finto-locale"]
