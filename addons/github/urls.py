"""Webhook di GitHub (pubblico, firmato) e apertura delle issue dai compiti."""
from django.urls import path

from . import views, webhook

urlpatterns = [
    path("webhook/<int:pk>/", webhook.ricevi, name="webhook"),
    path("compito/<int:pk>/issue/", views.crea_issue, name="crea_issue"),
]
