from django.test import RequestFactory, override_settings

from theme.context_processors import theme


def test_default_senza_settings():
    with override_settings(THEME={}):
        ctx = theme(RequestFactory().get("/"))
    assert ctx["theme"]["brand"] == "Progetto"
    assert ctx["theme"]["mark"] == "PR"
    assert ctx["theme"]["nav"] == []


def test_settings_sovrascrivono_i_default():
    with override_settings(THEME={"brand": "Acme", "mark": "AC"}):
        ctx = theme(RequestFactory().get("/"))
    assert ctx["theme"]["brand"] == "Acme"
    assert ctx["theme"]["company"] == ""
