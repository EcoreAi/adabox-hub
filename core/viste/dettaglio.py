from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from core import proprieta as proprieta_srv
from core.registry import hooks

from .chatter import contesto_chatter
from .lista import VistaBase, urls_di


class DettaglioView(VistaBase):
    def get(self, request, pk):
        vista = self.vista
        obj = vista.get_object(request, pk)
        if not vista.has_view_permission(request, obj):
            raise PermissionDenied
        def dato(c):
            return {"campo": c, "label": vista.etichetta(c), "valore": vista.col_valore(request, obj, c)}
        proprieta = [{"campo": proprieta_srv.nome_campo(d), "label": d.label, "valore": proprieta_srv.testo(d, obj)}
                     for d in vista.proprieta(request)]
        sezioni, collocate = [], False
        for titolo, righe in vista.layout_dettaglio():
            righe_dati = []
            for riga in righe:
                if riga == ["@proprieta"]:
                    righe_dati.extend([p] for p in proprieta)
                    collocate = True
                else:
                    righe_dati.append([dato(c) for c in riga])
            sezioni.append((titolo, [r for r in righe_dati if r]))
        if proprieta and not collocate:
            sezioni.append(("Altre informazioni", [[p] for p in proprieta]))
        return render(request, vista.template_dettaglio, {
            "vista": vista, "urls": urls_di(vista), "obj": obj, "sezioni": sezioni,
            "bottoni": [(nome, etichetta, vista.url("bottone", pk=obj.pk, nome=nome))
                        for nome, etichetta in vista.get_buttons(request, obj)],
            "puo_modificare": vista.has_change_permission(request, obj),
            "puo_eliminare": vista.has_delete_permission(request, obj),
            "url_modifica": vista.url("modifica", pk=obj.pk), "url_elimina": vista.url("elimina", pk=obj.pk),
            "sezioni_extra": hooks.sezioni_per(vista.model, request),
            "chatter": contesto_chatter(request, vista, obj) if vista.chatter else None,
            "stampe": [(r["nome"], vista.url("stampa", pk=obj.pk, indice=i)) for i, r in enumerate(vista.reports)],
        })
