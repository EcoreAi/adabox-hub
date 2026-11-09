"""Vista Gantt: una barra per record, dal campo d'inizio a quello di fine (senza fine: fino al bordo del periodo),
su una finestra di mesi che si sposta. Resa dal server, come il calendario."""
import datetime
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from . import filtri
from .gruppi import MESI
from .lista import VistaBase, contesto_testata, query_filtri, urls_di

MESI_FINESTRA = 6
MASSIMO = 200


def _mese(testo, ripiego):
    try:
        return datetime.datetime.strptime(testo, "%Y-%m").date().replace(day=1)
    except (TypeError, ValueError):
        return ripiego


def _sposta(primo, delta):
    m = primo.month - 1 + delta
    return primo.replace(year=primo.year + m // 12, month=m % 12 + 1, day=1)


def _giorno(v):
    if isinstance(v, datetime.datetime):
        return timezone.localtime(v).date() if timezone.is_aware(v) else v.date()
    return v


class GanttView(VistaBase):
    def get(self, request):
        vista = self.vista
        if not vista.has_view_permission(request):
            raise PermissionDenied
        oggi = timezone.localdate()
        inizio = _mese(request.GET.get("da"), _sposta(oggi.replace(day=1), -1))
        fine = _sposta(inizio, MESI_FINESTRA) - datetime.timedelta(days=1)
        giorni = (fine - inizio).days + 1
        c_in, c_fi = vista.gantt_inizio, vista.gantt_fine
        qs = filtri.applica(vista, request, vista.get_queryset(request)).filter(**{f"{c_in}__isnull": False, f"{c_in}__lte": fine})
        qs = qs.filter(Q(**{f"{c_fi}__isnull": True}) | Q(**{f"{c_fi}__gte": inizio}))
        colori = {}
        if vista.gantt_colore:
            f = vista.opts.get_field(vista.gantt_colore)
            colori = {k: i % 6 for i, (k, _) in enumerate(f.flatchoices)} if f.flatchoices else {}
        barre = []
        for obj in qs.order_by(c_in, "pk")[:MASSIMO]:
            da, a = _giorno(getattr(obj, c_in)), _giorno(getattr(obj, c_fi)) or fine
            if a < da:
                a = da
            x0, x1 = max(da, inizio), min(a, fine)
            barre.append({"obj": obj, "da": da, "a": getattr(obj, c_fi), "sinistra": round((x0 - inizio).days * 100 / giorni, 3),
                          "larghezza": max(round(((x1 - x0).days + 1) * 100 / giorni, 3), 0.6), "tagliata_prima": da < inizio,
                          "tagliata_dopo": a > fine or getattr(obj, c_fi) is None,
                          "colore": colori.get(getattr(obj, vista.gantt_colore), 0) if vista.gantt_colore else (len(barre) % 6)})
        mesi = []
        m = inizio
        while m <= fine:
            successivo = _sposta(m, 1)
            mesi.append({"nome": f"{MESI[m.month - 1][:3]} {m.year % 100:02d}", "larghezza": round((successivo - m).days * 100 / giorni, 3)})
            m = successivo
        qf = query_filtri(request)

        def link(**param):
            return "?" + "&".join(x for x in (urlencode(param), qf) if x)
        return render(request, "core/vista/gantt.html", {
            "vista": vista, "urls": urls_di(vista), "barre": barre, "mesi": mesi, "troppi": qs.count() > MASSIMO,
            "oggi": round((oggi - inizio).days * 100 / giorni, 3) if inizio <= oggi <= fine else None,
            "titolo": f"{MESI[inizio.month - 1].capitalize()} {inizio.year} – {MESI[fine.month - 1]} {fine.year}",
            "precedente": link(da=_sposta(inizio, -3).strftime("%Y-%m")), "successivo": link(da=_sposta(inizio, 3).strftime("%Y-%m")),
            "oggi_link": link(), "puo_aggiungere": vista.has_add_permission(request), "filtri": filtri.specifiche(vista, request),
            "extra_get": [("da", request.GET["da"])] if request.GET.get("da") else [], **contesto_testata(request, vista, "gantt")})
