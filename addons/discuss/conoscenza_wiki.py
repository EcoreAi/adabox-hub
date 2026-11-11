"""La wiki come fonte della conoscenza dell'assistente del sito: si scrive una volta sola.

Lo sportello sceglie gli spazi della wiki (prodotti, condizioni, policy) le cui pagine l'AI può riferire ai visitatori.
Le pagine si copiano nella conoscenza dello sportello, una voce per pagina, con il percorso nel titolo, e si
aggiornano a ogni salvataggio, spostamento o eliminazione. L'isolamento resta quello di sempre: l'AI del sito legge
solo le sue voci, mai la wiki interna; chi sceglie uno spazio rende pubbliche tutte le sue pagine, anche future.
Le voci copiate si modificano nella wiki."""
import re

from django.apps import apps
from django.db import transaction

from core import lavori

from .models import Sportello, VoceConoscenza

COLLEGAMENTO = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def attiva():
    return apps.is_installed("wiki")


def titolo_pubblico(pagina):
    return " › ".join([pagina.spazio.nome, *(p.titolo for p in pagina.percorso()), pagina.titolo])[:200]


def testo_pubblico(pagina):
    """Il markdown della pagina, con i collegamenti [[Titolo]] ridotti al loro testo (i link interni non servono fuori)."""
    return COLLEGAMENTO.sub(lambda m: (m.group(2) or m.group(1)).strip(), pagina.testo or "").strip()


def _scrivi(sportello, pagina):
    """Crea o aggiorna la voce della pagina; non la tocca se non è cambiata (ogni salvataggio la reindicizza)."""
    titolo, testo = titolo_pubblico(pagina), testo_pubblico(pagina)
    voce = VoceConoscenza.objects.filter(sportello=sportello, pagina_wiki=pagina.pk).first()
    if not testo:                                     # pagina vuota: non c'è niente da dire
        if voce is not None:
            voce.delete()
        return
    if voce is None:
        VoceConoscenza.objects.create(sportello=sportello, pagina_wiki=pagina.pk, tipo=VoceConoscenza.WIKI, titolo=titolo, testo=testo)
    elif (voce.titolo, voce.testo, voce.tipo) != (titolo, testo, VoceConoscenza.WIKI):
        voce.titolo, voce.testo, voce.tipo = titolo, testo, VoceConoscenza.WIKI
        voce.save()


def sincronizza_sportello(sportello_id):
    """Allinea la conoscenza dello sportello alle pagine degli spazi scelti: nuove, cambiate, tolte."""
    sportello = Sportello.objects.filter(pk=sportello_id).first()
    if sportello is None or not attiva():
        return None
    from wiki.models import PaginaWiki
    pagine = list(PaginaWiki.objects.filter(spazio_id__in=sportello.spazi_wiki or []).select_related("spazio", "padre"))
    with transaction.atomic():
        for pagina in pagine:
            _scrivi(sportello, pagina)
        tolte = VoceConoscenza.objects.filter(sportello=sportello, pagina_wiki__isnull=False).exclude(pagina_wiki__in=[p.pk for p in pagine])
        quante = tolte.count()
        tolte.delete()
    return f"pagine: {len(pagine)}, tolte: {quante}"


def pagina_cambiata(pagina_id):
    """Una pagina salvata, spostata (anche in un altro spazio) o eliminata: le voci degli sportelli seguono."""
    if not attiva():
        return None
    from wiki.models import PaginaWiki
    pagina = PaginaWiki.objects.select_related("spazio", "padre").filter(pk=pagina_id).first()
    toccati = 0
    for sportello in Sportello.objects.exclude(spazi_wiki=[]):
        if pagina is not None and pagina.spazio_id in (sportello.spazi_wiki or []):
            _scrivi(sportello, pagina)
            toccati += 1
        else:
            toccati += VoceConoscenza.objects.filter(sportello=sportello, pagina_wiki=pagina_id).delete()[0]
    # le pagine figlie hanno il percorso nel titolo: se cambia il titolo della madre si aggiornano anche loro
    if pagina is not None:
        for figlia in pagina.figlie.values_list("pk", flat=True):
            if VoceConoscenza.objects.filter(pagina_wiki=figlia).exists():
                lavori.accoda("discuss.conoscenza_wiki.pagina_cambiata", pagina_id=figlia, max_tentativi=2)
    return f"sportelli: {toccati}"


def sportelli_che_la_dicono(spazio_id):
    """Gli sportelli che riferiscono ai visitatori le pagine dello spazio (per l'avviso nella wiki)."""
    return [s for s in Sportello.objects.exclude(spazi_wiki=[]) if spazio_id in (s.spazi_wiki or [])]


def _pagina_salvata(sender, instance, raw=False, **_):
    if not raw:
        pk = instance.pk
        transaction.on_commit(lambda: lavori.accoda("discuss.conoscenza_wiki.pagina_cambiata", pagina_id=pk, max_tentativi=2))


def _sportello_salvato(sender, instance, raw=False, **_):
    if not raw and (instance.spazi_wiki or VoceConoscenza.objects.filter(sportello=instance, pagina_wiki__isnull=False).exists()):
        pk = instance.pk
        transaction.on_commit(lambda: lavori.accoda("discuss.conoscenza_wiki.sincronizza_sportello", sportello_id=pk, max_tentativi=2))


def collega():
    from django.db.models.signals import post_delete, post_save

    from wiki.models import PaginaWiki
    post_save.connect(_pagina_salvata, sender=PaginaWiki, dispatch_uid="discuss.wiki_pagina_salvata")
    post_delete.connect(_pagina_salvata, sender=PaginaWiki, dispatch_uid="discuss.wiki_pagina_eliminata")
    post_save.connect(_sportello_salvato, sender=Sportello, dispatch_uid="discuss.sportello_spazi_wiki")
