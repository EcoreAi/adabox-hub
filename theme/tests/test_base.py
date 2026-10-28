import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.template import Context, Template
from django.test import RequestFactory, override_settings


def _render(user):
    tpl = Template("{% extends 'theme/base.html' %}{% block content %}CORPO{% endblock %}"
                   "{% block public_content %}PUBBLICO{% endblock %}")
    rf = RequestFactory()
    request = rf.get("/")
    request.user = user
    request.resolver_match = None
    from theme.context_processors import theme
    ctx = Context({"request": request, "user": user, **theme(request)})
    return tpl.render(ctx)


@pytest.mark.django_db
def test_utente_loggato_vede_header_nav_e_footer():
    user = User.objects.create_user("mario", "m@example.com", "pass12345!", first_name="Mario", last_name="Rossi")
    with override_settings(THEME={"brand": "Acme", "mark": "AC", "company": "Ichnobyte",
                                  "nav": [{"label": "Home", "url_name": "core:home"}]}):
        html = _render(user)
    assert "CORPO" in html and "PUBBLICO" not in html
    assert 'class="ui-logo-mark">AC<' in html
    assert ">Home<" in html
    assert "Mario Rossi" in html
    assert "Ichnobyte" in html
    assert "theme/ui.css" in html and "theme/ui.js" in html
    assert "classList.add('js')" in html


def test_anonimo_vede_solo_public_content():
    html = _render(AnonymousUser())
    assert "PUBBLICO" in html and "CORPO" not in html
    assert "ui-header" not in html


@pytest.mark.django_db
def test_base_carica_htmx(client, django_user_model):
    u = django_user_model.objects.create_user("u", "u@example.com", "pass12345!")
    client.force_login(u)
    r = client.get("/accounts/password_change/")          # pagina del theme, indipendente da core
    assert "theme/vendor/htmx.min.js" in r.content.decode()
