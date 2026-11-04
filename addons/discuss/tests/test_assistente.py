import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse

from core.models import Azienda, Modulo
from discuss import assistente_sito as a
from discuss import ia, livechat, servizi
from discuss.models import ConversazioneEsterna, DomandaSenzaRisposta, FrammentoPubblico, Messaggio, Notifica, Sportello, VoceConoscenza
from todo.models import Attivita


def _utente(nome, *altri):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_messaggio", *altri]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db, monkeypatch):
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    op = _utente("olga")
    x = Sportello.objects.create(nome="Assistenza", modalita=Sportello.AI, nome_ai="Ada sito", domini="sito.it")
    x.operatori.add(op)
    VoceConoscenza.objects.create(sportello=x, titolo="Quanto costa il piano Essenziale", testo="Il piano Essenziale costa 390 euro al mese.")
    VoceConoscenza.objects.create(sportello=x, titolo="Orari di assistenza", testo="Assistenza dal lunedì al venerdì.")
    return x


@pytest.fixture
def modello(monkeypatch):
    stato = {"risposta": "Costa 390 euro al mese.", "chiamate": []}

    def genera(sistema, testo, utente, azienda=None, titolo="", di_servizio=False):
        stato["chiamate"].append({"sistema": sistema, "testo": testo, "utente": utente, "di_servizio": di_servizio, "azienda": azienda})
        if isinstance(stato["risposta"], Exception):
            raise stato["risposta"]
        return stato["risposta"]
    monkeypatch.setattr(ia, "genera", genera)
    return stato


def _url(n, x):
    return reverse(f"discuss:lc_{n}", args=[x.chiave])


def _avvia(x, testo="Quanto costa il piano Essenziale?", ip="1.1.1.1", **k):
    token = Client(REMOTE_ADDR=ip).post(_url("avvia", x), {"testo": testo, **k}).json()["token"]
    return ConversazioneEsterna.objects.select_related("sportello", "canale").get(token=token)


def test_risponde_dalla_conoscenza_e_senza_disturbare_gli_operatori(s, modello):
    c = _avvia(s)
    assert c.gestita_da == "ai" and c.nome == "Visitatore"
    chiamata = modello["chiamate"][0]
    assert "390 euro" in chiamata["sistema"] and "Quanto costa" in chiamata["testo"] and chiamata["di_servizio"] is True
    m = c.canale.messaggi.filter(da_ai=True).get()
    assert m.corpo == "Costa 390 euro al mese." and m.fonti == ["Quanto costa il piano Essenziale"]
    assert not Notifica.objects.exists()
    j = Client().get(_url("messaggi", s), headers={"X-Token": c.token}).json()
    assert j["con_ai"] is True and j["chiedi_persona"] is True and j["ai_scrive"] is False
    assert j["messaggi"][1] == {"id": m.pk, "mio": False, "nome": "Ada sito", "testo": "Costa 390 euro al mese.", "ai": True}
    # la trasparenza è nella pagina
    assert "intelligenza artificiale" in Client().get(_url("finestra", s)).content.decode()


def test_per_l_operatore_visitatore_e_ai_restano_distinti(client, s, modello):
    c = _avvia(s)
    client.force_login(s.operatori.get())
    html = client.get(f"/discuss/c/{c.canale.pk}/").content.decode()
    assert html.count("is-continua") == 0 and "<strong>Ada sito</strong>" in html and "<strong>Visitatore</strong>" in html
    assert ">AI</span>" in html and "Ha consultato:" in html


def test_solo_la_conoscenza_del_suo_sportello_e_mai_i_dati_interni(s, modello):
    Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="Piano Essenziale segreto: margine 70 per cento")
    altro = Sportello.objects.create(nome="Altro")
    VoceConoscenza.objects.create(sportello=altro, titolo="Piano Essenziale altrui", testo="Il piano Essenziale di un altro sportello costa 1 euro.")
    VoceConoscenza.objects.create(sportello=s, titolo="Piano Essenziale spento", testo="Il piano Essenziale costa 999 euro.", attiva=False)
    _avvia(s)
    sistema = modello["chiamate"][0]["sistema"]
    assert "390 euro" in sistema and "margine" not in sistema and "1 euro" not in sistema and "999" not in sistema
    # il modello non riceve strumenti: la chiamata è solo testo, e cerca() legge una tabella sola
    assert all(f.voce.sportello_id == s.pk for _, f in a.cerca(s, "piano essenziale"))


def test_non_sa_rispondere_passa_a_una_persona_e_resta_la_domanda(s, modello):
    modello["risposta"] = a.MARCATORE
    c = _avvia(s, "Avete un connettore per il mio trattore?")
    c.refresh_from_db()
    assert c.gestita_da == "persona"
    assert DomandaSenzaRisposta.objects.get().testo == "Avete un connettore per il mio trattore?"
    n = Notifica.objects.get(utente=s.operatori.get())
    assert "ha bisogno di una persona" in n.titolo
    testi = [m["testo"] for m in Client().get(_url("messaggi", s), headers={"X-Token": c.token}).json()["messaggi"]]
    assert a.MARCATORE not in " ".join(testi) and s.assenza in testi              # nessun operatore online
    # da qui in poi il messaggio va alle persone, l'AI non risponde più
    prima = len(modello["chiamate"])
    Client().post(_url("scrivi", s), {"testo": "Ci siete?"}, headers={"X-Token": c.token})
    assert len(modello["chiamate"]) == prima and Notifica.objects.filter(titolo__contains="Visitatore", tipo="diretto").count() >= 1


def test_il_visitatore_chiede_una_persona_e_l_operatore_subentra(s, modello):
    c = _avvia(s)
    assert Client().post(_url("persona", s), headers={"X-Token": "falso"}).status_code == 403
    assert Client().post(_url("persona", s), headers={"X-Token": c.token}).status_code == 204
    c.refresh_from_db()
    assert c.gestita_da == "persona" and not DomandaSenzaRisposta.objects.exists()
    # un operatore che scrive prende la chat
    d = _avvia(s, ip="2.2.2.2")
    servizi.invia(d.canale, s.operatori.get(), "Ci penso io")
    d.refresh_from_db()
    assert d.gestita_da == "persona"
    prima = len(modello["chiamate"])
    Client().post(_url("scrivi", s), {"testo": "ok"}, headers={"X-Token": d.token})
    assert len(modello["chiamate"]) == prima


def test_solo_ai_non_passa_a_nessuno(s, modello):
    Sportello.objects.filter(pk=s.pk).update(modalita=Sportello.SOLO_AI)
    s.refresh_from_db()
    modello["risposta"] = a.MARCATORE
    c = _avvia(s, "Domanda difficile")
    c.refresh_from_db()
    assert c.gestita_da == "ai" and not Notifica.objects.exists() and DomandaSenzaRisposta.objects.count() == 1
    assert Client().get(_url("messaggi", s), headers={"X-Token": c.token}).json()["chiedi_persona"] is False
    Client().post(_url("persona", s), headers={"X-Token": c.token})
    c.refresh_from_db()
    assert c.gestita_da == "ai"


def test_tetti_ed_errori_non_lasciano_il_visitatore_senza_risposta(s, modello):
    Sportello.objects.filter(pk=s.pk).update(risposte_per_chat=1)
    s.refresh_from_db()
    c = _avvia(s)
    Client().post(_url("scrivi", s), {"testo": "E il piano Crescita?"}, headers={"X-Token": c.token})
    c.refresh_from_db()
    assert c.gestita_da == "persona" and len(modello["chiamate"]) == 1
    # tetto del giorno: nessuna chiamata a pagamento
    Sportello.objects.filter(pk=s.pk).update(risposte_per_chat=20, risposte_al_giorno=1)
    s.refresh_from_db()
    d = _avvia(s, ip="3.3.3.3")
    d.refresh_from_db()
    assert d.gestita_da == "persona" and len(modello["chiamate"]) == 1
    # modello giù o tetto di spesa
    Sportello.objects.filter(pk=s.pk).update(risposte_al_giorno=300)
    s.refresh_from_db()
    modello["risposta"] = ia.NonDisponibile("tetto di spesa")
    e = _avvia(s, ip="4.4.4.4")
    e.refresh_from_db()
    assert e.gestita_da == "persona" and "tetto" not in " ".join(e.canale.messaggi.values_list("corpo", flat=True))


def test_piu_messaggi_ravvicinati_una_risposta_sola(s, modello, settings):
    settings.LAVORI_SINCRONI = False
    c = _avvia(s)
    primo = c.canale.messaggi.get()
    v = Client()
    v.post(_url("scrivi", s), {"testo": "Ci sei?"}, headers={"X-Token": c.token})
    secondo = c.canale.messaggi.order_by("-pk").first()
    assert v.get(_url("messaggi", s), headers={"X-Token": c.token}).json()["ai_scrive"] is True
    assert a.rispondi(c.pk, primo.pk) == "ne è arrivato un altro" and not modello["chiamate"]
    assert a.rispondi(c.pk, secondo.pk) == "risposto" and len(modello["chiamate"]) == 1


def test_assistente_spento_rispondono_le_persone(s, modello):
    Modulo.objects.update_or_create(slug="ai", defaults={"nome": "ai", "versione_installata": "1", "stato": "installato", "disattivato": True})
    assert "intelligenza artificiale" not in Client().get(_url("finestra", s)).content.decode()
    c = _avvia_con_nome(s)
    assert c.gestita_da == "persona" and not modello["chiamate"] and Notifica.objects.filter(utente=s.operatori.get()).exists()


def _avvia_con_nome(s):
    token = Client().post(_url("avvia", s), {"nome": "Mario", "testo": "Ciao"}).json()["token"]
    return ConversazioneEsterna.objects.get(token=token)


def test_gestione_conoscenza_e_domande(client, s, modello):
    s.refresh_from_db()
    assert FrammentoPubblico.objects.filter(voce__sportello=s).count() == 2       # indice aggiornato al salvataggio
    voce = s.conoscenza.first()
    voce.testo = "Testo nuovo diverso"
    voce.save()
    assert FrammentoPubblico.objects.filter(voce=voce).get().testo.endswith("Testo nuovo diverso")
    DomandaSenzaRisposta.objects.create(sportello=s, testo="Avete la app?")
    r = _utente("rino", "view_sportello", "change_sportello", "view_voceconoscenza", "add_voceconoscenza", "change_voceconoscenza")
    client.force_login(r)
    html = client.get(reverse("discuss:sportelli_dettaglio", args=[s.pk])).content.decode()
    assert "Avete la app?" in html and "Aggiungi la risposta" in html and "Prova la chat" in html
    from django.core.files.uploadedfile import SimpleUploadedFile
    client.post(reverse("discuss:lc_carica", args=[s.pk]), {"file": [SimpleUploadedFile("orari.txt", "Siamo aperti il sabato".encode()), SimpleUploadedFile("vuoto.bin", b"\x00\x01")]})
    assert VoceConoscenza.objects.get(titolo="orari.txt").testo == "Siamo aperti il sabato"
    client.post(reverse("discuss:lc_domanda_risolta", args=[DomandaSenzaRisposta.objects.get().pk]))
    assert DomandaSenzaRisposta.objects.get().risolta
    # senza permesso no
    altro = Client()
    altro.force_login(_utente("ugo"))
    assert altro.post(reverse("discuss:lc_carica", args=[s.pk]), {}).status_code == 403
    assert altro.get(reverse("discuss:conoscenza_lista")).status_code == 403


def test_comando_demo_crea_e_toglie(db, monkeypatch):
    from django.core.management import call_command
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    User.objects.create_superuser("capo", "c@e.it", "x")
    User.objects.create_superuser("collega", "d@e.it", "x")
    call_command("livechat_demo", "genera")
    x = Sportello.objects.get(nome__contains="prova")
    assert x.conoscenza.filter(tipo="faq").count() == 15 and x.conoscenza.filter(tipo="documento").count() == 7
    assert x.operatori.count() == 1
    assert x.modalita == "ai" and FrammentoPubblico.objects.filter(voce__sportello=x).exists()
    call_command("livechat_demo", "azzera")
    assert not Sportello.objects.filter(nome__contains="prova").exists()
