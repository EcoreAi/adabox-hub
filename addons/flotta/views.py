from core.viste import ModelView, register

from .models import ContrattoVeicolo, CostoVeicolo, Veicolo


@register
class VeicoloView(ModelView):
    model = Veicolo
    slug = "veicoli"
    company_field = "azienda"
    list_display = ["targa", "modello", "assegnato_a", "tipo_possesso", "km", "assicurazione_al", "revisione_al", "attivo"]
    list_filter = ["tipo_possesso", "attivo", "alimentazione"]
    search_fields = ["targa", "modello", "assegnato_a__cognome"]
    import_key = "targa"
    form_layout = [("Veicolo", [("targa", "modello"), ("tipo_possesso", "alimentazione"), ("assegnato_a", "uso_promiscuo"), ("km", "immatricolato_il"), "attivo"]),
                   ("Scadenze", [("assicurazione_al", "bollo_al"), ("revisione_al", "tagliando_al"), "tagliando_km"]), ("Note", ["note"])]
    chatter = True
    tracked_fields = ["assegnato_a", "km"]
    ai_descrizione = "I veicoli aziendali con assegnatario, chilometri e scadenze."


@register
class ContrattoVeicoloView(ModelView):
    model = ContrattoVeicolo
    slug = "contratti"
    company_field = "azienda"
    list_display = ["veicolo", "fornitore", "dal", "al", "canone", "km_compresi"]
    form_layout = [("Contratto", [("veicolo", "fornitore"), ("dal", "al"), ("canone", "km_compresi"), "riscatto"])]
    gantt_inizio, gantt_fine = "dal", "al"
    ai_descrizione = "I contratti di noleggio e leasing dei veicoli."


@register
class CostoVeicoloView(ModelView):
    model = CostoVeicolo
    slug = "costi"
    company_field = "azienda"
    list_display = ["data", "veicolo", "tipo", "importo", "km", "dipendente"]
    list_filter = ["tipo", "veicolo"]
    list_sum = ["importo"]
    list_group_by = ["tipo", "veicolo", "data:mese"]
    form_layout = [("Costo", [("veicolo", "data"), ("tipo", "importo"), ("km", "litri"), ("dipendente", "descrizione")])]
    ai_descrizione = "I costi dei veicoli: carburante, manutenzioni, multe, pedaggi."
