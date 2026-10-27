from django.urls import include, path

from . import views
from .viste import registry

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("stile/", views.stile, name="stile"),
    path("profilo/", views.profilo, name="profilo"),
    path("profilo/token/", views.token_nuovo, name="token_nuovo"),
    path("profilo/token/<int:pk>/revoca/", views.token_revoca, name="token_revoca"),
    path("azienda/cambia/", views.cambia_azienda, name="cambia_azienda"),
    path("moduli/", views.moduli, name="moduli"),
    path("moduli/azione/", views.moduli_azione, name="moduli_azione"),
    path("moduli/stato/", views.moduli_stato, name="moduli_stato"),
]
# viste generate dalle ModelView del kernel, sotto /core/ come i moduli sotto /<slug>/
urlpatterns += [path("core/", include(registry.urlpatterns("core")))]
