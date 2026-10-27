from django.urls import include, path

from . import views
from .viste import registry

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("stile/", views.stile, name="stile"),
    path("profilo/", views.profilo, name="profilo"),
    path("azienda/cambia/", views.cambia_azienda, name="cambia_azienda"),
]
# viste generate dalle ModelView del kernel, sotto /core/ come i moduli sotto /<slug>/
urlpatterns += [path("core/", include(registry.urlpatterns("core")))]
