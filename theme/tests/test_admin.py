import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.urls import reverse


@pytest.mark.django_db
def test_admin_index_ha_brand_e_css(client):
    User.objects.create_superuser("root", "root@example.com", "pass12345!")
    client.force_login(User.objects.get(username="root"))
    r = client.get(reverse("admin:index"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "theme/admin.css" in html
    assert f"{settings.THEME['brand']} · Admin" in html
    assert f'class="ui-admin-mark">{settings.THEME["mark"]}<' in html


@pytest.mark.django_db
def test_admin_login_usa_il_tema(client):
    r = client.get(reverse("admin:login"))
    assert r.status_code == 200
    assert "theme/admin.css" in r.content.decode()
