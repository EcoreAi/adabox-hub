"""La parte dell'IVA nel pacchetto per il commercialista: le liquidazioni dei periodi richiesti."""

from . import calcolo
from .models import Liquidazione


def liquidazioni(request, anno, mese, avvisi):
    if not request.user.has_perm("iva.view_liquidazione"):
        return
    from .pagine import _foglio
    periodicita = calcolo.periodicita_di(request.azienda)
    periodi = calcolo.anno(request.azienda, anno, periodicita)
    if mese:
        voluto = mese if periodicita == Liquidazione.MENSILE else (mese - 1) // 3 + 1
        periodi = [r for r in periodi if r.periodo == voluto]
    periodi = [r for r in periodi if r.liquidazione or r.esigibile or r.detratta or r.a_credito or r.da_versare]
    if periodi:
        yield "iva/liquidazioni-iva.csv", _foglio(periodi)
        aperte = [r.nome for r in periodi if not r.da_chiusura]
        if aperte:
            avvisi.append(f"Liquidazioni IVA non ancora chiuse: {', '.join(aperte)}")
