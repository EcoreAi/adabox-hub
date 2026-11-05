"""Il pacchetto per il commercialista: uno ZIP con i documenti e i registri del periodo. La contabilità resta allo
studio: qui si consegna solo ciò che serve a lui. SDI e Banca aggiungono le loro parti con `aggiungi`.

Ogni sezione riceve (request, anno, mese, avvisi) e restituisce (percorso, contenuto); legge dalle stesse viste delle
liste, quindi solo l'azienda corrente e solo ciò che l'utente può vedere."""
import csv
import io
import zipfile
from pathlib import PurePosixPath

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core.dashboard import queryset

from . import fatturapa, scadenzario
from .models import Fattura, Incasso
from .registro import MESI, periodo, registro

_sezioni = []


def aggiungi(sezione):
    if sezione not in _sezioni:
        _sezioni.append(sezione)


def foglio(intestazione, righe):
    """Un CSV che Excel apre bene in italiano: punto e virgola e BOM."""
    uscita = io.StringIO()
    scrittore = csv.writer(uscita, delimiter=";")
    scrittore.writerow(intestazione)
    scrittore.writerows(righe)
    return uscita.getvalue().encode("utf-8-sig")


def nel_periodo(qs, campo, anno, mese):
    qs = qs.filter(**{f"{campo}__year": anno})
    return qs.filter(**{f"{campo}__month": mese}) if mese else qs


def _vendite(request, anno, mese, avvisi):
    righe, _ = registro(request, anno, mese)
    if righe:
        yield "vendite/registro-iva-vendite.csv", foglio(
            ["Data", "Numero", "Tipo", "Cliente", "Partita IVA", "Codice fiscale", "Aliquota", "Imponibile", "Imposta"],
            [[r["fattura"].data.strftime("%d/%m/%Y"), r["fattura"].numero, r["fattura"].get_tipo_display(), r["fattura"].cliente.nome,
              r["fattura"].cliente.partita_iva, r["fattura"].cliente.codice_fiscale, r["aliquota"].codice,
              scadenzario.numero_csv(r["imponibile"]), scadenzario.numero_csv(r["imposta"])] for r in righe])
    for fattura in dict.fromkeys(r["fattura"] for r in righe):
        try:
            nome, contenuto = fatturapa.genera(fattura)
        except ValidationError as e:
            avvisi.append(f"Fattura {fattura.numero}: XML non generato ({' '.join(e.messages)})")
        else:
            yield f"vendite/fatture-xml/{nome}", contenuto
    incassi = nel_periodo(queryset(request, Incasso), "data", anno, mese).select_related("scadenza__fattura__cliente").order_by("data", "pk")
    if incassi:
        yield "vendite/incassi.csv", foglio(
            ["Data", "Fattura", "Cliente", "Tipo", "Metodo", "Riferimento", "Importo"],
            [[i.data.strftime("%d/%m/%Y"), i.scadenza.fattura.numero, i.scadenza.fattura.cliente.nome, i.get_tipo_display(),
              i.get_metodo_display(), i.riferimento, scadenzario.numero_csv(i.importo)] for i in incassi])
    aperte, _ = scadenzario.tabella(scadenzario.voci_clienti(request), timezone.localdate())
    if aperte:
        yield "vendite/crediti-aperti-oggi.csv", scadenzario.testo_csv(aperte, "Cliente").encode("utf-8-sig")


aggiungi(_vendite)


def componi(request, anno, mese):
    """(contenuto dello ZIP, numero di file, avvisi). I nomi dei file si puliscono: alcuni arrivano dai fornitori."""
    avvisi, memoria, usati = [], io.BytesIO(), set()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as archivio:
        for sezione in _sezioni:
            for percorso, contenuto in sezione(request, anno, mese, avvisi):
                cartella, nome = PurePosixPath(percorso).parent, PurePosixPath(percorso).name
                finale, n = str(cartella / nome), 1
                while finale in usati:
                    n += 1
                    finale = str(cartella / f"{n}-{nome}")
                usati.add(finale)
                archivio.writestr(finale, contenuto)
        titolo = f"{MESI[mese - 1]} {anno}" if mese else str(anno)
        testo = [f"Pacchetto per il commercialista: {request.azienda}", f"Periodo: {titolo}",
                 f"Preparato il {timezone.localtime():%d/%m/%Y %H:%M} da {request.user.get_full_name() or request.user.get_username()}",
                 f"File: {len(usati)}", ""]
        testo += ["Da controllare:", *[f"- {a}" for a in avvisi]] if avvisi else ["Nulla da controllare."]
        archivio.writestr("LEGGIMI.txt", "\r\n".join(testo).encode("utf-8-sig"))
    return memoria.getvalue(), len(usati), avvisi


@login_required
@permission_required("fatturazione.view_fattura", raise_exception=True)
def pacchetto(request):
    """GET: la scelta del periodo. POST: lo ZIP (genera gli XML, che assegnano il progressivo di invio se manca)."""
    anno, mese = periodo(request, request.POST if request.method == "POST" else None)
    if request.method == "POST":
        contenuto, _, _ = componi(request, anno, mese)
        esito = HttpResponse(contenuto, content_type="application/zip")
        esito["Content-Disposition"] = f'attachment; filename="commercialista-{anno}{f"-{mese:02d}" if mese else ""}.zip"'
        return esito
    oggi = timezone.localdate()
    return render(request, "fatturazione/commercialista.html", {
        "anno": anno, "mese": mese, "anni": range(oggi.year, oggi.year - 6, -1), "mesi": list(enumerate(MESI, start=1))})
