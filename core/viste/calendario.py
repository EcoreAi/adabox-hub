"""Vista calendario: mese o settimana, eventi dal campo data della ModelView, resa dal server."""
import datetime
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.db import models
from django.shortcuts import render
from django.utils import timezone

from . import filtri
from .gruppi import MESI
from .lista import VistaBase, contesto_testata, query_filtri, urls_di

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
MAX_PER_GIORNO = 4


def _data(testo, formato):
    try:
        return datetime.datetime.strptime(testo, formato).date()
    except (TypeError, ValueError):
        return None


def periodo(request):
    """(modo, inizio, fine, riferimento): settimana da lunedì o mese intero allargato a settimane complete."""
    oggi = timezone.localdate()
    if (giorno := _data(request.GET.get("settimana"), "%Y-%m-%d")) is not None:
        inizio = giorno - datetime.timedelta(days=giorno.weekday())
        return "settimana", inizio, inizio + datetime.timedelta(days=6), inizio
    primo = _data(request.GET.get("mese"), "%Y-%m") or oggi.replace(day=1)
    primo = primo.replace(day=1)
    ultimo = (primo.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    return ("mese", primo - datetime.timedelta(days=primo.weekday()),
            ultimo + datetime.timedelta(days=6 - ultimo.weekday()), primo)


def _mese_spostato(primo, delta):
    m = primo.month - 1 + delta
    return primo.replace(year=primo.year + m // 12, month=m % 12 + 1, day=1)


class CalendarioView(VistaBase):
    def get(self, request):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        campo = vista.opts.get_field(vista.calendar_date)
        con_ora = isinstance(campo, models.DateTimeField)
        modo, inizio, fine, riferimento = periodo(request)
        lookup = f"{campo.name}__date__range" if con_ora else f"{campo.name}__range"
        qs = filtri.applica(vista, request, vista.get_queryset(request)).filter(**{lookup: (inizio, fine)})
        colori = {}
        if vista.calendar_color:
            f_colore = vista.opts.get_field(vista.calendar_color)
            colori = {k: i % 6 for i, (k, _) in enumerate(f_colore.flatchoices)}
        eventi = {}
        for obj in qs.order_by(campo.name, "pk"):
            valore = getattr(obj, campo.name)
            giorno = timezone.localtime(valore).date() if con_ora else valore
            eventi.setdefault(giorno, []).append({
                "obj": obj, "ora": timezone.localtime(valore).strftime("%H:%M") if con_ora else "",
                "colore": colori.get(getattr(obj, vista.calendar_color), 0) if vista.calendar_color else 0})
        oggi = timezone.localdate()
        giorni = []
        d = inizio
        while d <= fine:
            del_giorno = eventi.get(d, [])
            limite = len(del_giorno) if modo == "settimana" else MAX_PER_GIORNO
            giorni.append({"data": d, "oggi": d == oggi, "fuori": modo == "mese" and d.month != riferimento.month,
                           "eventi": del_giorno[:limite], "altri": max(0, len(del_giorno) - limite)})
            d += datetime.timedelta(days=1)
        qf = query_filtri(request)

        def link(**param):
            return "?" + "&".join(x for x in (urlencode(param), qf) if x)
        if modo == "mese":
            titolo = f"{MESI[riferimento.month - 1].capitalize()} {riferimento.year}"
            precedente = link(mese=_mese_spostato(riferimento, -1).strftime("%Y-%m"))
            successivo = link(mese=_mese_spostato(riferimento, 1).strftime("%Y-%m"))
            altro_modo = link(settimana=(oggi if inizio <= oggi <= fine else riferimento).isoformat())
        else:
            titolo = f"{inizio.day} {MESI[inizio.month - 1]} – {fine.day} {MESI[fine.month - 1]} {fine.year}"
            precedente = link(settimana=(inizio - datetime.timedelta(days=7)).isoformat())
            successivo = link(settimana=(inizio + datetime.timedelta(days=7)).isoformat())
            altro_modo = link(mese=riferimento.strftime("%Y-%m"))
        return render(request, vista.template_calendario, {
            "vista": vista, "urls": urls_di(vista), "modo": modo, "titolo": titolo, "intestazioni": GIORNI,
            "settimane": [giorni[i:i + 7] for i in range(0, len(giorni), 7)],
            "precedente": precedente, "successivo": successivo,
            "oggi_link": link(settimana=oggi.isoformat()) if modo == "settimana" else link(),
            "altro_modo": altro_modo, "campo": campo.name, "puo_aggiungere": vista.has_add_permission(request),
            "filtri": filtri.specifiche(vista, request),
            "extra_get": [(k, request.GET[k]) for k in ("mese", "settimana") if request.GET.get(k)],
            **contesto_testata(request, vista, "calendario")})
