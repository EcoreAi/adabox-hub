from django import template

register = template.Library()


@register.simple_tag
def analitica_documento(documento):
    """Per la scheda di fattura, fattura ricevuta o nota spese: le righe con le loro imputazioni."""
    from analitica import fonti, operazioni
    fonte, righe = fonti.documento_e_righe(documento)
    if fonte is None or not righe:
        return None
    mappa = operazioni.imputazioni_di(fonte, righe)
    return {"fonte": fonte, "righe": [{"r": r, "descrizione": fonte.descrizione(r), "imputazioni": mappa.get(r.pk, [])} for r in righe]}


@register.simple_tag
def confronto_budget(budget):
    from analitica import operazioni
    return operazioni.confronto(budget)
