from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.api import api
from core.registry.urls import patterns_moduli

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password_change/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("accounts/password_change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    # password dimenticata e impostazione da un link (anche gli inviti dei clienti al portale)
    path("accounts/password_reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("accounts/password_reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("api/v1/", api.urls),
    path("", include("theme.urls")),
    path("", include("core.urls")),
    *patterns_moduli(),   # un prefisso <slug>/ per ogni modulo installato
]
