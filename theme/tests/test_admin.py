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
    assert 'class="ui-admin-mark">' in html and 'class="ui-logo-cubo"' in html


@pytest.mark.django_db
def test_admin_entra_dal_login_unico_e_usa_il_tema(client, superuser):
    assert "theme/admin.css" in client.get(reverse("admin:index")).content.decode()
    client.logout()
    r = client.get(reverse("admin:login"))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
