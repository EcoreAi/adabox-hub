from core import chatter
from core.viste import register
from progetti.views import DelProgettoVisibile

from .models import Ambiente, CasoTest, Collaudo


@register
class AmbienteView(DelProgettoVisibile):
    model = Ambiente
    slug = "ambienti"
    list_display = ["nome", "progetto", "tipo", "url", "rilascio"]
    list_filter = ["progetto", "tipo"]
    search_fields = ["nome", "progetto__nome", "url"]
    form_layout = [("Ambiente", [("nome", "progetto"), ("tipo", "rilascio"), "url", "note"])]
    company_field = "azienda"


@register
class CasoTestView(DelProgettoVisibile):
    model = CasoTest
    slug = "casi"
    list_display = ["titolo", "area", "progetto", "priorita", "attivo"]
    list_filter = ["progetto", "area", "priorita", "attivo"]
    search_fields = ["titolo", "area", "passi", "atteso"]
    form_layout = [("Caso di test", [("titolo", "progetto"), ("area", "priorita"), "precondizioni", "passi", "atteso",
                                     "attivo"])]
    list_group_by = ["progetto", "area", "priorita"]
    company_field = "azienda"
    chatter = True
    import_key = "titolo"


@register
class CollaudoView(DelProgettoVisibile):
    model = Collaudo
    slug = "collaudi"
    list_display = ["nome", "progetto", "rilascio", "ambiente", "responsabile", "stato", "creato"]
    list_filter = ["progetto", "rilascio", "stato", "responsabile"]
    search_fields = ["nome", "progetto__nome"]
    form_layout = [("Collaudo", [("nome", "progetto"), ("rilascio", "ambiente"), "responsabile"])]
    readonly_fields = ["stato", "creato"]
    company_field = "azienda"
    kanban_group = "stato"
    kanban_fields = ["progetto", "rilascio", "responsabile"]
    chatter = True
    tracked_fields = ["stato"]
    buttons = ["aggiungi", "concludi"]

    def save_model(self, request, obj, form, change):
        if not change and obj.responsabile_id is None:
            obj.responsabile = request.user
        super().save_model(request, obj, form, change)

    def get_buttons(self, request, obj):
        return [] if obj.stato == Collaudo.CONCLUSO else super().get_buttons(request, obj)

    def aggiungi(self, request, obj):
        n = obj.aggiungi_casi()
        return f"Aggiunti {n} casi." if n else "Nessun caso nuovo da aggiungere."
    aggiungi.short_description = "Aggiungi i casi nuovi"

    def concludi(self, request, obj):
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = Collaudo.CONCLUSO
        obj.save(update_fields=["stato"])
        chatter.traccia(obj, vecchi, request.user)
        r = obj.riepilogo()
        chatter.scrivi(obj, request.user, f"Collaudo concluso: {r['superato']} superati, {r['fallito']} falliti, "
                                          f"{r['bloccato']} bloccati, {r['saltato']} saltati, {r['da_fare']} non "
                                          f"eseguiti su {r['totale']}.", tipo="nota")
        return f"Collaudo concluso: esito {obj.esito()}."
    concludi.short_description = "Concludi il collaudo"
