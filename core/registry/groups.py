"""Gruppi Django dichiarati nel manifest."""
from django.contrib.auth.models import Group, Permission
from django.db.models import Q


def espandi(perm):
    """'app.codename' -> ['app.codename']; 'app.*' -> tutti i permessi dei modelli dell'app."""
    app, codename = perm.split(".", 1)
    qs = Permission.objects.filter(content_type__app_label=app)
    if codename != "*":
        qs = qs.filter(codename=codename)
    trovati = sorted(f"{app}.{p.codename}" for p in qs)
    if not trovati:
        raise ValueError(f"permesso {perm!r} inesistente")
    return trovati


def crea_gruppi(manifest):
    """Crea o riallinea i gruppi del manifest. Restituisce i nomi (vanno in Modulo.gruppi_creati)."""
    nomi = []
    for nome, perms in manifest.groups.items():
        gruppo, _ = Group.objects.get_or_create(name=nome)
        codici = {p for perm in perms for p in espandi(perm)}
        if codici:
            filtro = Q(*[Q(content_type__app_label=a, codename=c) for a, c in (p.split(".", 1) for p in codici)],
                       _connector=Q.OR)
            gruppo.permissions.set(Permission.objects.filter(filtro))
        else:
            gruppo.permissions.clear()
        nomi.append(nome)
    return nomi
