"""La parte degli acquisti nel pacchetto per il commercialista: registro, file originali e debiti aperti."""
from pathlib import PurePosixPath

from django.utils import timezone

from core.dashboard import queryset
from fatturazione import scadenzario
from fatturazione.commercialista import foglio, nel_periodo

from .models import FatturaPassiva
from .pagine import voci_fornitori


def acquisti(request, anno, mese, avvisi):
    registrate = (nel_periodo(queryset(request, FatturaPassiva).filter(stato=FatturaPassiva.REGISTRATA), "registrata_il", anno, mese)
                  .select_related("fornitore").prefetch_related("riepilogo").order_by("registrata_il", "pk"))
    righe = []
    for f in registrate:
        segno = -1 if f.nota_credito else 1
        for r in f.riepilogo.all():
            righe.append([f.registrata_il.strftime("%d/%m/%Y"), f.numero, f.data.strftime("%d/%m/%Y"), f.fornitore.nome,
                          f.fornitore.partita_iva, f"{r.aliquota:.0f}%" + (f" {r.natura}" if r.natura else ""),
                          scadenzario.numero_csv(r.imponibile * segno), scadenzario.numero_csv(r.imposta * segno)])
    if righe:
        yield "acquisti/registro-acquisti.csv", foglio(
            ["Registrata il", "Numero", "Data", "Fornitore", "Partita IVA", "Aliquota", "Imponibile", "Imposta"], righe)
    for f in registrate:
        try:
            with f.originale.open("rb") as file:
                yield f"acquisti/fatture-ricevute/{PurePosixPath(f.nome_file.replace(chr(92), '/')).name}", file.read()
        except (FileNotFoundError, ValueError):
            avvisi.append(f"Fattura ricevuta {f.numero} di {f.fornitore}: manca il file originale")
    sospese = nel_periodo(queryset(request, FatturaPassiva).exclude(stato=FatturaPassiva.REGISTRATA), "data", anno, mese).select_related("fornitore")
    for f in sospese:
        avvisi.append(f"Fattura ricevuta {f.numero} di {f.fornitore}: {f.get_stato_display().lower()}, non inclusa nel registro")
    aperti, _ = scadenzario.tabella(voci_fornitori(request), timezone.localdate())
    if aperti:
        yield "acquisti/debiti-aperti-oggi.csv", scadenzario.testo_csv(aperti, "Fornitore").encode("utf-8-sig")
