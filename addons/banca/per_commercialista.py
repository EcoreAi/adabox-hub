"""La parte della banca nel pacchetto per il commercialista: i movimenti del periodo."""
from core.dashboard import queryset
from fatturazione.commercialista import foglio, nel_periodo
from fatturazione.scadenzario import numero_csv

from .models import MovimentoBanca


def movimenti(request, anno, mese, avvisi):
    voci = nel_periodo(queryset(request, MovimentoBanca), "data", anno, mese).select_related("conto").order_by("data", "pk")
    if voci:
        yield "banca/movimenti.csv", foglio(
            ["Data", "Valuta", "Conto", "Importo", "Descrizione", "Controparte", "Riferimento", "Stato", "Categoria", "Conto per lo studio"],
            [[m.data.strftime("%d/%m/%Y"), m.valuta.strftime("%d/%m/%Y") if m.valuta else "", m.conto, numero_csv(m.importo),
              m.descrizione, m.controparte, m.riferimento, m.get_stato_display(), m.categoria, m.codice_studio] for m in voci])
        per_categoria = {}
        for m in voci.filter(stato=MovimentoBanca.CLASSIFICATO):
            chiave = (m.categoria, m.codice_studio)
            per_categoria[chiave] = per_categoria.get(chiave, 0) + m.importo
        if per_categoria:
            yield "banca/movimenti-senza-fattura.csv", foglio(
                ["Categoria", "Conto per lo studio", "Totale"],
                [[c, codice, numero_csv(t)] for (c, codice), t in sorted(per_categoria.items())])
    da_abbinare = voci.filter(stato=MovimentoBanca.DA_ABBINARE).count()
    if da_abbinare:
        avvisi.append(f"Movimenti di banca ancora da abbinare: {da_abbinare}")
