"""Report PDF: template Django con il layout di stampa del kernel, convertiti con WeasyPrint."""
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone


class ReportNonDisponibile(RuntimeError):
    pass


def weasyprint():
    """Import pigro: WeasyPrint richiede Pango (libreria di sistema, presente nell'immagine Docker)."""
    try:
        import weasyprint as w
    except (ImportError, OSError) as e:
        raise ReportNonDisponibile("La generazione dei PDF non è disponibile su questo server (manca Pango).") from e
    return w


def disponibile():
    try:
        weasyprint()
        return True
    except ReportNonDisponibile:
        return False


def html(vista, request, oggetti, indice):
    """HTML del report `indice` della vista per gli oggetti dati (un record per pagina)."""
    report = vista.reports[indice]
    azienda = getattr(request, "azienda", None)
    logo = ""
    if azienda is not None and azienda.logo:
        logo = Path(settings.MEDIA_ROOT, azienda.logo.name).resolve().as_uri()
    return render_to_string(report["template"], {
        "vista": vista, "report": report, "oggetti": list(oggetti), "azienda": azienda, "logo": logo,
        "oggi": timezone.localdate(), "utente": request.user, "theme": settings.THEME,
    })


def pdf(contenuto_html):
    w = weasyprint()
    return w.HTML(string=contenuto_html, base_url=str(settings.BASE_DIR)).write_pdf()


def nome_file(vista, indice, oggetti):
    base = vista.reports[indice]["nome"].lower().replace(" ", "-")
    return f"{base}-{oggetti[0].pk}.pdf" if len(oggetti) == 1 else f"{base}-{timezone.localtime():%Y%m%d-%H%M}.pdf"


def in_background(modulo, slug, indice, pks, utente_id, azienda_id):
    """Lavoro: stampa di massa grande; il PDF diventa un allegato dell'utente e il link arriva per email."""
    from types import SimpleNamespace

    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.core.mail import send_mail
    from django.urls import reverse

    from core import allegati
    from core.models import Azienda
    from core.viste import registry
    vista = next(v for v in registry.viste_di(modulo) if v.slug == slug)
    utente = get_user_model().objects.get(pk=utente_id)
    richiesta = SimpleNamespace(user=utente, azienda=Azienda.objects.filter(pk=azienda_id).first())
    oggetti = list(vista.get_queryset(richiesta).filter(pk__in=pks))
    dati = pdf(html(vista, richiesta, oggetti, indice))
    allegato = allegati.salva(utente, ContentFile(dati, name=nome_file(vista, indice, oggetti)), utente)
    if utente.email:
        link = settings.SITO_URL + reverse("core:allegato_scarica", args=[allegato.pk])
        send_mail(f"[{settings.THEME.get('brand', '')}] Stampa pronta: {vista.reports[indice]['nome']}",
                  f"La stampa che hai chiesto è pronta:\n{link}\n", None, [utente.email])
    return allegato.pk
