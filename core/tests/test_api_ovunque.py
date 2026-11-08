"""PLT-14 / INT-08: l'API è accesa per ogni vista tranne quelle con segreti, non fa mai uscire campi segreti, ha gli
schemi OpenAPI dei record e un limite di richieste al minuto per token."""
import pytest
from django.core.cache import cache

from core.api.modelli import SEGRETI, campi_api
from core.models import TokenApi
from core.viste import registry

SENZA_API = {"ai.provider", "ai.chiavi", "ai.mcp", "ai.voce", "core.profili", "core.lavoro", "connettori.webhook",
             "connettori.consegne", "pagamenti.fornitori", "discuss.connessioni", "portale.provider",
             "portale.account_collegati", "rivendita.istanze"}


def _viste():
    return [v for vv in registry._viste.values() for v in vv]


@pytest.mark.django_db
def test_ogni_vista_risponde_tranne_quelle_con_segreti(client, superuser):
    cache.clear()
    provate = 0
    for v in _viste():
        nome = f"{v.modulo}.{v.slug}"
        r = client.get(f"/api/v1/{v.modulo}/{v.slug}/")
        if nome in SENZA_API:
            assert r.status_code == 404, nome
            continue
        if not v.api:
            continue
        assert r.status_code in (200, 403), (nome, r.status_code, r.content[:300])
        provate += 1
    assert provate > 80


def test_nessun_campo_segreto_esce():
    for v in _viste():
        if v.api:
            assert not [c for c in campi_api(v) if SEGRETI.search(c)], f"{v.modulo}.{v.slug}"


@pytest.mark.django_db
def test_schema_openapi_dei_record(client, superuser):
    cache.clear()
    doc = client.get("/api/v1/openapi.json").json()
    crea = doc["paths"]["/api/v1/core/aziende/"]["post"]
    corpo = crea["requestBody"]["content"]["application/json"]["schema"]
    assert corpo["properties"]["nome"]["type"] == "string" and "nome" in corpo["required"]
    leggi = doc["paths"]["/api/v1/core/aziende/{pk}/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert leggi["properties"]["id"]["type"] == "integer" and leggi["properties"]["attiva"]["type"] == "boolean"
    lista = doc["paths"]["/api/v1/core/aziende/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert lista["properties"]["results"]["items"]["properties"]["nome"]["title"].lower() == "nome"
    assert "/api/v1/ai/provider/" not in doc["paths"]


@pytest.mark.django_db
def test_limite_di_richieste_per_token(client, superuser, settings):
    cache.clear()
    settings.API_LIMITE = "3/m"
    client.logout()                                                     # solo il token, niente sessione
    _, chiaro = TokenApi.genera(superuser, "integrazione")
    intestazioni = {"HTTP_AUTHORIZATION": f"Bearer {chiaro}"}
    stati = [client.get("/api/v1/core/aziende/", **intestazioni).status_code for _ in range(4)]
    assert stati == [200, 200, 200, 429]
    r = client.get("/api/v1/core/aziende/", **intestazioni)
    assert r.status_code == 429 and int(r["Retry-After"]) >= 1
    _, altro = TokenApi.genera(superuser, "altra")                      # un altro token ha il suo conto
    assert client.get("/api/v1/core/aziende/", HTTP_AUTHORIZATION=f"Bearer {altro}").status_code == 200
