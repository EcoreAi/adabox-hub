"""Pagine del connettore, sotto /connettore_ai/, e gli indirizzi che uno standard vuole alla radice dell'istanza:
il server MCP (`/mcp`, quello che l'utente incolla nella chat) e i metadati (`/.well-known/…`, RFC 9728 e RFC 8414).
Gli indirizzi di OAuth non hanno la barra finale: i client li chiamano così come sono scritti nei metadati."""
from django.urls import path

from . import mcp, pagine, viste_oauth

urlpatterns = [
    path("", pagine.mie, name="mie"),
    path("scollega/<int:pk>/", pagine.scollega, name="scollega"),
    path("credenziali/", pagine.credenziali, name="credenziali"),
    path("oauth/authorize", viste_oauth.autorizza, name="autorizza"),
    path("oauth/token", viste_oauth.token, name="token"),
    path("oauth/register", viste_oauth.registra, name="registra"),
    path("oauth/revoke", viste_oauth.revoca, name="revoca"),
]

urlpatterns_radice = [
    path("mcp", mcp.mcp, name="connettore_ai_mcp"),
    path("mcp/", mcp.mcp),
    path(".well-known/oauth-protected-resource/mcp", viste_oauth.metadati_risorsa, name="connettore_ai_metadati_risorsa"),
    path(".well-known/oauth-protected-resource", viste_oauth.metadati_risorsa),
    path(".well-known/oauth-authorization-server", viste_oauth.metadati_server, name="connettore_ai_metadati_server"),
]
