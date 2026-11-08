"""Modelli di stampa (PLT-09): per azienda e documento, il colore, le righe sotto l'intestazione, i testi prima e dopo il
corpo, il piè di pagina e le colonne nascoste. I testi hanno segnaposto {{ campo }} sostituiti come nelle email
(core.modelli_email.riempi): un testo scritto da un utente non esegue nulla e finisce nel PDF con l'escape."""
import re

from django.utils import timezone
from django.utils.html import escape, linebreaks
from django.utils.safestring import mark_safe

from core.modelli_email import riempi

COLORE = re.compile(r"^#[0-9a-fA-F]{6}$")
SEGNAPOSTO = {"documento": "il documento (es. Preventivo PR/2026/0012)", "numero": "il numero", "data": "la data del documento",
              "cliente": "il cliente o il fornitore", "totale": "il totale", "azienda": "la tua azienda", "oggi": "la data di stampa"}


def chiave(vista, indice):
    return f"{vista.modulo}.{vista.slug}:{indice}"


def disponibili():
    """[(chiave, etichetta, colonne)] dei report di tutte le viste."""
    from core.viste import registry
    risultato = []
    for vv in registry._viste.values():
        for v in vv:
            for i, r in enumerate(v.reports):
                risultato.append((chiave(v, i), f"{str(v.verbose_name_plural).capitalize()} · {r['nome']}", list(r.get("colonne", []))))
    return sorted(risultato, key=lambda x: x[1])


def etichetta(valore):
    return next((e for k, e, _ in disponibili() if k == valore), valore)


def vista_e_indice(valore):
    from core.viste import registry
    vista_id, _, indice = (valore or "").partition(":")
    modulo, _, slug = vista_id.partition(".")
    vista = next((v for v in registry.viste_di(modulo) if v.slug == slug), None)
    return (vista, int(indice)) if vista is not None and indice.isdigit() and int(indice) < len(vista.reports) else (None, None)


def modello_per(vista, indice, azienda):
    """Il modello attivo dell'azienda per quel documento, altrimenti quello per tutte, altrimenti None (l'originale)."""
    from core.models import ModelloStampa
    candidati = ModelloStampa.objects.filter(report=chiave(vista, indice), attivo=True)
    if azienda is not None:
        proprio = candidati.filter(azienda=azienda).first()
        if proprio is not None:
            return proprio
    return candidati.filter(azienda__isnull=True).first()


def valori(obj, azienda):
    def data(d):
        return d.strftime("%d/%m/%Y") if d else ""
    controparte = getattr(obj, "cliente", None) or getattr(obj, "fornitore", None) or getattr(obj, "destinatario", None)
    totale = getattr(obj, "totale", None)
    return {"documento": str(obj), "numero": str(getattr(obj, "numero", "") or ""), "data": data(getattr(obj, "data", None)),
            "cliente": str(controparte or ""), "totale": f"{totale:.2f} €" if totale is not None else "",
            "azienda": str(azienda or ""), "oggi": data(timezone.localdate())}


def testo(modello, campo, obj=None, azienda=None):
    """Un testo del modello con i segnaposto riempiti, come HTML sicuro (paragrafi e a capo)."""
    grezzo = getattr(modello, campo, "") if modello is not None else ""
    if not grezzo:
        return ""
    return mark_safe(linebreaks(escape(riempi(grezzo, valori(obj, azienda) if obj is not None else {}))))


def css(modello):
    """Le regole che il modello aggiunge alla stampa: colore e colonne nascoste."""
    if modello is None:
        return ""
    regole = []
    if modello.colore and COLORE.match(modello.colore):
        regole.append(f"h1, .titolo-colore {{ color: {modello.colore}; }} .intestazione {{ border-bottom-color: {modello.colore}; }}")
    for colonna in modello.colonne_nascoste or []:
        if re.fullmatch(r"[a-z_]+", str(colonna)):
            regole.append(f".col-{colonna} {{ display: none; }}")
    return mark_safe("\n".join(regole))
