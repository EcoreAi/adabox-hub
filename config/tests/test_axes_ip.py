"""IP del client per django-axes dietro nginx.

nginx (proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for) aggiunge
in coda all'header l'indirizzo reale del client: tutto cio' che sta a sinistra
l'ha scritto il client e puo' essere falso. L'IP giusto e' quindi l'ultimo
elemento di X-Forwarded-For; REMOTE_ADDR e' nginx stesso (127.0.0.1).
"""
import pytest
from axes.helpers import get_client_ip_address
from django.test import RequestFactory, override_settings

from config.tests.test_settings import _carica


@pytest.fixture
def impostazioni_produzione():
    s = _carica("False")
    with override_settings(
        AXES_IPWARE_PROXY_COUNT=s.AXES_IPWARE_PROXY_COUNT,
        AXES_IPWARE_META_PRECEDENCE_ORDER=s.AXES_IPWARE_META_PRECEDENCE_ORDER,
        IPWARE_STRICT=s.IPWARE_STRICT,
    ):
        yield


def _ip(xff=None):
    meta = {"REMOTE_ADDR": "127.0.0.1"}
    if xff is not None:
        meta["HTTP_X_FORWARDED_FOR"] = xff
    return get_client_ip_address(RequestFactory().get("/", **meta))


def test_ipware_installato():
    from axes import helpers

    assert helpers.IPWARE_INSTALLED is True


def test_client_normale_dietro_nginx(impostazioni_produzione):
    assert _ip("10.1.2.3") == "10.1.2.3"


def test_header_falsificato_dal_client_ignorato(impostazioni_produzione):
    assert _ip("6.6.6.6, 10.1.2.3") == "10.1.2.3"
    assert _ip("6.6.6.6, 7.7.7.7, 10.1.2.3") == "10.1.2.3"
    assert _ip("spazzatura, 10.1.2.3") == "10.1.2.3"


def test_senza_proxy_usa_remote_addr(impostazioni_produzione):
    assert _ip() == "127.0.0.1"
