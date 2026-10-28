from django.urls import include, path

from . import views
from .viste import allegati as allegati_viste
from .viste import chatter as chatter_viste
from .viste import registry

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("app/", views.launcher, name="launcher"),
    path("stile/", views.stile, name="stile"),
    path("profilo/", views.profilo, name="profilo"),
    path("profilo/azienda/", views.azienda_predefinita, name="azienda_predefinita"),
    path("profilo/token/", views.token_nuovo, name="token_nuovo"),
    path("profilo/token/<int:pk>/revoca/", views.token_revoca, name="token_revoca"),
    path("azienda/cambia/", views.cambia_azienda, name="cambia_azienda"),
    path("impostazioni/", views.impostazioni, name="impostazioni"),
    path("chatter/<int:ct>/<int:pk>/", chatter_viste.pannello, name="chatter"),
    path("chatter/<int:ct>/<int:pk>/messaggi/", chatter_viste.altri_messaggi, name="chatter_messaggi"),
    path("chatter/<int:ct>/<int:pk>/scrivi/", chatter_viste.scrivi, name="chatter_scrivi"),
    path("chatter/<int:ct>/<int:pk>/segui/", chatter_viste.segui, name="chatter_segui"),
    path("chatter/<int:ct>/<int:pk>/pianifica/", chatter_viste.pianifica, name="chatter_pianifica"),
    path("attivita/", views.attivita_mie, name="attivita"),
    path("attivita/<int:pk>/fatta/", chatter_viste.attivita_fatta, name="attivita_fatta"),
    path("attivita/<int:pk>/annulla/", chatter_viste.attivita_annulla, name="attivita_annulla"),
    path("allegati/elenco/<int:ct>/<int:pk>/", allegati_viste.elenco, name="allegati_elenco"),
    path("allegati/carica/<int:ct>/<int:pk>/", allegati_viste.carica, name="allegato_carica"),
    path("allegati/<int:pk>/", allegati_viste.scarica, name="allegato_scarica"),
    path("allegati/<int:pk>/elimina/", allegati_viste.elimina, name="allegato_elimina"),
    path("moduli/", views.moduli, name="moduli"),
    path("moduli/azione/", views.moduli_azione, name="moduli_azione"),
    path("moduli/carica/", views.moduli_carica, name="moduli_carica"),
    path("moduli/scarica/", views.moduli_scarica, name="moduli_scarica"),
    path("moduli/stato/", views.moduli_stato, name="moduli_stato"),
]
# viste generate dalle ModelView del kernel, sotto /core/ come i moduli sotto /<slug>/
urlpatterns += [path("core/", include(registry.urlpatterns("core")))]
