import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404
from django.test import RequestFactory

from core.generici import ct_di, vista_e_oggetto
from core.models import Azienda, Modulo


def _richiesta(*codenames):
    u = User.objects.create_user("gen", "g@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    request = RequestFactory().get("/")
    request.user = User.objects.get(pk=u.pk)
    request.azienda = None
    return request


@pytest.mark.django_db
def test_vista_e_oggetto():
    a = Azienda.objects.create(nome="Acme")
    vista, obj = vista_e_oggetto(_richiesta("view_azienda"), ct_di(a).pk, a.pk)
    assert obj == a and vista.model is Azienda


@pytest.mark.django_db
def test_senza_permesso_403():
    a = Azienda.objects.create(nome="Acme")
    with pytest.raises(PermissionDenied):
        vista_e_oggetto(_richiesta(), ct_di(a).pk, a.pk)


@pytest.mark.django_db
def test_senza_change_403():
    a = Azienda.objects.create(nome="Acme")
    with pytest.raises(PermissionDenied):
        vista_e_oggetto(_richiesta("view_azienda"), ct_di(a).pk, a.pk, "change")


@pytest.mark.django_db
def test_404():
    request = _richiesta("view_azienda")
    with pytest.raises(Http404):
        vista_e_oggetto(request, ct_di(Azienda).pk, 99999)
    with pytest.raises(Http404):                                  # modello senza ModelView
        vista_e_oggetto(request, ContentType.objects.get_for_model(Modulo).pk, 1)
    with pytest.raises(Http404):
        vista_e_oggetto(request, 999999, 1)
    with pytest.raises(Http404):
        vista_e_oggetto(request, "x", 1)


@pytest.mark.postgres
@pytest.mark.django_db
def test_gira_su_postgres():
    assert connection.vendor == "postgresql"
