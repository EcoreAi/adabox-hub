import pytest
from django.contrib.auth.models import User
from django.urls import reverse

# django-axes 8 blocca al raggiungimento del limite (il 5° errore riceve già il
# lockout) e risponde 429 Too Many Requests.


@pytest.mark.django_db
def test_dopo_5_tentativi_falliti_arriva_il_lockout(client):
    User.objects.create_user("mario", "m@example.com", "giusta12345!")
    url = reverse("login")
    for _ in range(4):
        r = client.post(url, {"username": "mario", "password": "sbagliata"}, REMOTE_ADDR="10.0.0.9")
        assert r.status_code == 200
    r = client.post(url, {"username": "mario", "password": "sbagliata"}, REMOTE_ADDR="10.0.0.9")
    assert r.status_code == 429
    # bloccato anche con la password giusta
    r = client.post(url, {"username": "mario", "password": "giusta12345!"}, REMOTE_ADDR="10.0.0.9")
    assert r.status_code == 429
    assert "lockout.html" in [t.name for t in r.templates]
    assert "Troppi tentativi" in r.content.decode()


@pytest.mark.django_db
def test_altro_ip_non_e_bloccato(client):
    User.objects.create_user("mario", "m@example.com", "giusta12345!")
    url = reverse("login")
    for _ in range(5):
        client.post(url, {"username": "mario", "password": "sbagliata"}, REMOTE_ADDR="10.0.0.9")
    r = client.post(url, {"username": "mario", "password": "giusta12345!"}, REMOTE_ADDR="10.0.0.10")
    assert r.status_code == 302  # login riuscito
