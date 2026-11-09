"""Permessi per spazio, versioni, testo reso e collegamenti [[Titolo]] tra pagine."""
import re

from django.apps import apps
from django.db.models import Max, Q
from django.urls import reverse
from django.utils.html import escape, linebreaks
from django.utils.safestring import mark_safe

from .models import MembroWiki, PaginaWiki, SpazioWiki, VersionePagina

COLLEGAMENTO = re.compile(r"\[\[([^\]\n|]{1,200})(?:\|([^\]\n]{1,200}))?\]\]")


def gestore(utente):
    return utente.is_superuser or utente.has_perm("wiki.delete_spaziowiki")


def spazi_leggibili(utente, azienda):
    qs = SpazioWiki.objects.filter(azienda=azienda)
    if gestore(utente):
        return qs
    return qs.filter(Q(aperto=True) | Q(iscritti__utente=utente)).distinct()


def puo_scrivere(utente, spazio):
    if gestore(utente):
        return True
    return MembroWiki.objects.filter(spazio=spazio, utente=utente, ruolo=MembroWiki.SCRIVE).exists()


def salva_versione(pagina, autore=None):
    """Una versione nuova se titolo o testo sono cambiati dall'ultima."""
    ultima = pagina.versioni.first()
    if ultima and ultima.titolo == pagina.titolo and ultima.testo == pagina.testo:
        return None
    numero = (pagina.versioni.aggregate(m=Max("numero"))["m"] or 0) + 1
    return VersionePagina.objects.create(pagina=pagina, numero=numero, titolo=pagina.titolo, testo=pagina.testo, autore=autore)


def ripristina(pagina, versione, autore=None):
    pagina.titolo, pagina.testo, pagina.aggiornata_da = versione.titolo, versione.testo, autore
    pagina.save()
    return salva_versione(pagina, autore)


def rendi(pagina):
    """Il testo in HTML sicuro: [[Titolo]] diventa il link alla pagina dello stesso spazio (o a crearla)."""
    titoli = {p.titolo.lower(): p.pk for p in PaginaWiki.objects.filter(spazio_id=pagina.spazio_id).only("pk", "titolo")}

    def link(m):
        titolo, etichetta = m.group(1).strip(), (m.group(2) or m.group(1)).strip()
        pk = titoli.get(titolo.lower())
        if pk:
            return f"[{etichetta}]({reverse('wiki:pagine_dettaglio', args=[pk])})"
        return f"[{etichetta} (da scrivere)]({reverse('wiki:pagine_nuovo')}?spazio={pagina.spazio_id}&titolo={titolo.replace(' ', '%20')})"
    testo = COLLEGAMENTO.sub(link, pagina.testo or "")
    if apps.is_installed("ai"):
        from ai import markdown
        return markdown.rendi(testo)
    return mark_safe(linebreaks(escape(testo)))


def citata_da(pagina):
    """Le pagine dello spazio che la citano con [[Titolo]]."""
    return [p for p in PaginaWiki.objects.filter(spazio_id=pagina.spazio_id).exclude(pk=pagina.pk)
            if pagina.titolo.lower() in {m.group(1).strip().lower() for m in COLLEGAMENTO.finditer(p.testo or "")}]
