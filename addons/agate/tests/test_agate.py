"""Le proposte dell'assistente passano da Agate: consentite, bloccate, da approvare, in osservazione."""
import hashlib
import hmac
import json
import time

import pytest
from django.contrib.auth.models import User

from agate import cliente, lavori
from agate.models import Collegamento, Valutazione
from ai import motore
from ai.gateway import finto
from ai.models import AnelloCatena, Conversazione, Modello, Profilo, Proposta, Provider
from core.models import Azienda

CHIAVE = "agt_test_adabox0000000000000000"
SEGRETO = "whsec_" + "s" * 40


class AgateFinto:
    """Risponde come il gateway di Agate alle rotte che il modulo usa."""

    def __init__(self):
        self.verdetto = {"verdict": "allow"}
        self.approvazione = "pending"
        self.decisione = {}
        self.chiamate = []
        self.giu = False

    def __call__(self, metodo, url, intestazioni, corpo):
        if self.giu:
            raise OSError("connessione rifiutata")
        assert intestazioni["Authorization"] == f"Bearer {CHIAVE}"
        dati = json.loads(corpo) if corpo else None
        self.chiamate.append((metodo, url, dati))
        if url.endswith("/v1/evaluate"):
            risposta = {"evaluation_id": "evl_1", "risk": {"factors": []}, "policies_hit": [],
                        "normalized_params": dati["proposal"]["params"], "observed": False, **self.verdetto}
            if risposta["verdict"] == "require_approval":
                risposta["approval"] = {"id": "apr_1", "status": "pending"}
            return 200, json.dumps(risposta).encode()
        if "/v1/evaluations/" in url:
            return 200, json.dumps({"approval": {"id": "apr_1", "status": self.approvazione, **self.decisione}}).encode()
        if url.endswith("/v1/llm/models"):
            return 200, json.dumps({"data": [{"id": "vendite-eu"}, {"id": "solo-locale"}]}).encode()
        return 404, b'{"title": "Rotta sconosciuta"}'


@pytest.fixture
def agate(monkeypatch):
    finto_agate = AgateFinto()
    monkeypatch.setattr(cliente, "trasporto", finto_agate)
    return finto_agate


@pytest.fixture
def scena(db, client, agate):
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    c = Collegamento(gateway_url="https://agate.test", console_url="https://console.agate.test",
                     modalita=Collegamento.ATTIVO)
    c.imposta_chiave(CHIAVE)
    c.imposta_segreto(SEGRETO)
    c.save()
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client, "collegamento": c,
            "conversazione": Conversazione.objects.create(utente=capo, titolo="Prova")}


def proposta(scena, nome="Delta Spa"):
    copione = [[("strumento", "crea_record", {"vista": "core.aziende", "campi": {"nome": nome, "citta": "Bari"}})],
               ["Ecco la proposta."]]
    with finto.con_copione(copione):
        motore.avvia(scena["conversazione"], "Crea l'azienda", scena["capo"], scena["azienda"])
    return Proposta.objects.order_by("-pk").first()


def conferma(scena, p):
    return scena["client"].post(f"/ai/proposta/{p.pk}/conferma/", HTTP_HX_REQUEST="true")


def test_consentita_si_esegue_e_agate_vede_lo_strumento_giusto(scena, agate):
    p = proposta(scena)
    conferma(scena, p)
    p.refresh_from_db()
    assert p.stato == "eseguita" and Azienda.objects.filter(nome="Delta Spa").exists()
    metodo, url, dati = agate.chiamate[0]
    assert url == "https://agate.test/v1/evaluate"
    assert dati["proposal"]["tool"] == "adabox.crea_record"
    assert dati["proposal"]["params"]["campi"]["nome"] == "Delta Spa"
    assert Valutazione.objects.get(proposta=p).stato == "consentita"


def test_bloccata_dalle_regole_non_tocca_nulla(scena, agate):
    agate.verdetto = {"verdict": "deny", "policies_hit": [{"id": "x", "effect": "deny",
                                                           "detail": "Nuove aziende solo dall'ufficio"}]}
    p = proposta(scena)
    risposta = conferma(scena, p)
    p.refresh_from_db()
    assert p.stato == "fallita" and "Nuove aziende solo dall'ufficio" in p.esito
    assert not Azienda.objects.filter(nome="Delta Spa").exists()
    assert "Fermata dalle regole di Agate" in risposta.content.decode()


def test_da_approvare_aspetta_e_si_esegue_quando_una_persona_approva(scena, agate):
    agate.verdetto = {"verdict": "require_approval"}
    p = proposta(scena)
    pagina = conferma(scena, p).content.decode()
    p.refresh_from_db()
    assert p.stato == "in_attesa" and "console.agate.test/console/approvals/apr_1/" in p.esito
    assert "approvazione di una persona" in pagina
    conferma(scena, p)                                     # un secondo clic non rivaluta
    assert len([c for c in agate.chiamate if c[1].endswith("/v1/evaluate")]) == 1
    assert lavori.controlla_approvazioni() == 0            # ancora in attesa in Agate
    agate.approvazione = "approved"
    assert lavori.controlla_approvazioni() == 1
    p.refresh_from_db()
    assert p.stato == "eseguita" and Azienda.objects.filter(nome="Delta Spa").exists()
    assert Valutazione.objects.get(proposta=p).stato == "approvata"


def test_rifiutata_in_agate_dal_webhook_firmato(scena, agate):
    agate.verdetto = {"verdict": "require_approval"}
    p = proposta(scena)
    conferma(scena, p)
    corpo = json.dumps({"type": "approval.decided", "data": {"approval_id": "apr_1", "decision": "rejected",
                                                              "reason": "Non questo mese"}}).encode()
    t = int(time.time())
    firma = hmac.new(SEGRETO.encode(), f"{t}.".encode() + corpo, hashlib.sha256).hexdigest()
    sbagliata = scena["client"].post("/agate/webhook/", corpo, content_type="application/json",
                                     HTTP_X_AGATE_SIGNATURE=f"t={t},v1={'0' * 64}")
    assert sbagliata.status_code == 401
    vecchia = hmac.new(SEGRETO.encode(), f"{t - 900}.".encode() + corpo, hashlib.sha256).hexdigest()
    assert scena["client"].post("/agate/webhook/", corpo, content_type="application/json",
                                HTTP_X_AGATE_SIGNATURE=f"t={t - 900},v1={vecchia}").status_code == 401
    ok = scena["client"].post("/agate/webhook/", corpo, content_type="application/json",
                              HTTP_X_AGATE_SIGNATURE=f"t={t},v1={firma}")
    assert ok.status_code == 200
    p.refresh_from_db()
    assert p.stato == "fallita" and "Non approvata in Agate" in p.esito and "«Non questo mese»" in p.esito
    assert not Azienda.objects.filter(nome="Delta Spa").exists()


def test_chi_ha_confermato_legge_chi_ha_rifiutato_e_perche_oppure_che_e_scaduta(scena, agate):
    agate.verdetto = {"verdict": "require_approval"}
    p = proposta(scena)
    conferma(scena, p)
    agate.approvazione = "rejected"
    agate.decisione = {"decided_by": "olga", "reason": "Ne abbiamo già una uguale"}
    assert lavori.controlla_approvazioni() == 1
    p.refresh_from_db()
    assert p.esito == "Non approvata in Agate da olga: «Ne abbiamo già una uguale». Non è cambiato nulla."
    assert Valutazione.objects.get(proposta=p).motivo == "Ne abbiamo già una uguale"

    p2 = proposta(scena, "Epsilon Srl")
    conferma(scena, p2)
    agate.approvazione, agate.decisione = "expired", {}
    lavori.controlla_approvazioni()
    p2.refresh_from_db()
    assert p2.stato == "fallita" and "scaduta" in p2.esito and "chiedila di nuovo" in p2.esito


def test_limite_di_agate_chiede_di_rifare(scena, agate):
    p = proposta(scena)
    agate.verdetto = {"verdict": "modify", "normalized_params": {"vista": "core.aziende", "campi": {"nome": "X"}},
                      "policies_hit": [{"id": "tetto", "effect": "modify", "detail": "tetto"}]}
    conferma(scena, p)
    p.refresh_from_db()
    assert p.stato == "fallita" and "entro il limite" in p.esito


def test_osservazione_registra_ma_non_ferma_e_agate_giu(scena, agate):
    c = scena["collegamento"]
    c.modalita = Collegamento.OSSERVAZIONE
    c.save()
    agate.verdetto = {"verdict": "deny"}
    p = proposta(scena)
    conferma(scena, p)
    p.refresh_from_db()
    assert p.stato == "eseguita" and Valutazione.objects.get(proposta=p).stato == "osservata"

    agate.giu = True
    p2 = proposta(scena, "Epsilon Srl")
    conferma(scena, p2)
    p2.refresh_from_db()
    assert p2.stato == "eseguita"                       # in osservazione Agate giù non ferma
    c.modalita = Collegamento.ATTIVO
    c.save()
    p3 = proposta(scena, "Zeta Srl")
    conferma(scena, p3)
    p3.refresh_from_db()
    assert p3.stato == "fallita" and "non risponde" in p3.esito
    assert not Azienda.objects.filter(nome="Zeta Srl").exists()


def test_spento_non_chiama_agate(scena, agate):
    scena["collegamento"].modalita = Collegamento.SPENTO
    scena["collegamento"].save()
    p = proposta(scena)
    conferma(scena, p)
    p.refresh_from_db()
    assert p.stato == "eseguita" and agate.chiamate == []


def test_pagina_di_collegamento_e_modelli_attraverso_agate(scena, agate):
    pagina = scena["client"].get("/agate/").content.decode()
    assert CHIAVE not in pagina and "••••" in pagina and "/agate/webhook/" in pagina
    r = scena["client"].post("/agate/", {"azione": "modelli"})
    assert r.status_code == 302
    provider = Provider.objects.get(nome="Agate")
    assert provider.tipo == "openai_compat" and provider.base_url == "https://agate.test/v1/llm"
    assert provider.chiave_per() == CHIAVE
    assert sorted(provider.modelli.values_list("id_api", flat=True)) == ["solo-locale", "vendite-eu"]
    salva = scena["client"].post("/agate/", {"azione": "salva", "gateway_url": "https://agate2.test",
                                            "console_url": "", "prefisso": "hub", "modalita": "attivo"})
    assert salva.status_code == 302
    c = Collegamento.attuale()
    assert c.gateway_url == "https://agate2.test" and c.chiave() == CHIAVE and c.prefisso == "hub"
    assert scena["client"].get("/agate/valutazioni/").status_code == 200


def test_gli_strumenti_per_agate_sono_solo_le_scritture(scena, capsys):
    from django.core.management import call_command

    call_command("agate_strumenti")
    definizioni = json.loads(capsys.readouterr().out)
    nomi = {d["slug"]: d for d in definizioni}
    assert "adabox.crea_record" in nomi and "adabox.cerca_record" not in nomi
    assert nomi["adabox.crea_record"]["side_effect"] == "write"
    assert any(d["side_effect"] == "irreversible" for d in definizioni)
    assert all(len(d["description"]) <= 300 for d in definizioni)


def test_un_utente_senza_permesso_non_vede_il_collegamento(scena, client):
    utente = User.objects.create_user("mario", "m@example.com", "pass12345!")
    client.force_login(utente)
    assert client.get("/agate/").status_code == 403
