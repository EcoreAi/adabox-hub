"""Import CSV e XLSX in una ModelView: mappatura colonne → campi, prova a secco, tutto o niente."""
import csv
import datetime
import io
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction

from core.models import Azienda

VERI = {"sì", "si", "s", "yes", "y", "true", "vero", "1", "x"}


class ImportNonValido(ValueError):
    pass


def cartella():
    percorso = Path(settings.PRIVATE_MEDIA_ROOT) / "import"
    percorso.mkdir(parents=True, exist_ok=True)
    return percorso


def salva_caricato(file):
    estensione = Path(file.name).suffix.lower()
    if estensione not in (".csv", ".xlsx"):
        raise ImportNonValido("Formato non supportato: carica un file .csv o .xlsx")
    nome = f"{uuid.uuid4().hex}{estensione}"
    with open(cartella() / nome, "wb") as destinazione:
        for blocco in file.chunks():
            destinazione.write(blocco)
    return nome


def percorso(nome):
    p = (cartella() / nome).resolve()
    if p.parent != cartella().resolve():
        raise ImportNonValido("file non valido")
    return p


def leggi(nome):
    """(intestazioni, righe) dal file salvato; righe vuote saltate."""
    p = percorso(nome)
    if p.suffix == ".xlsx":
        from openpyxl import load_workbook
        foglio = load_workbook(p, read_only=True, data_only=True).active
        righe = [list(r) for r in foglio.iter_rows(values_only=True)]
    else:
        grezzo = p.read_bytes()
        try:
            testo = grezzo.decode("utf-8-sig")
        except UnicodeDecodeError:
            testo = grezzo.decode("latin-1")
        separatore = ";" if testo.split("\n", 1)[0].count(";") >= testo.split("\n", 1)[0].count(",") else ","
        righe = list(csv.reader(io.StringIO(testo), delimiter=separatore))
    righe = [r for r in righe if any(c not in (None, "") for c in r)]
    if not righe:
        raise ImportNonValido("Il file è vuoto")
    intestazioni = [str(c).strip() if c is not None else "" for c in righe[0]]
    return intestazioni, [r + [None] * (len(intestazioni) - len(r)) for r in righe[1:]]


RIGA = "riga."


def campi(vista):
    """[(nome, etichetta)] dei campi importabili: quelli del form più la chiave di aggiornamento e, per i documenti con
    righe, i campi della prima tabella di righe come «riga.<campo>»."""
    nomi = vista.campi_form()
    if vista.import_key and vista.import_key not in nomi:
        nomi = [vista.import_key] + nomi
    risultato = [(n, vista.etichetta(n)) for n in nomi]
    if vista.inlines:
        inline = vista.inlines[0]
        meta = inline.model._meta
        risultato += [(f"{RIGA}{c}", f"Riga · {str(meta.get_field(c).verbose_name)}") for c in inline.fields]
    return risultato


def _gruppi(righe, colonne_testata):
    """Le righe consecutive con gli stessi valori di testata formano un documento: [(numero della prima, [righe])]."""
    gruppi, chiave_prima = [], object()
    for n, riga in enumerate(righe, start=2):
        chiave = tuple(_testo(riga[i]) for i, _ in colonne_testata)
        if gruppi and chiave == chiave_prima:
            gruppi[-1][1].append((n, riga))
        else:
            gruppi.append((n, [(n, riga)]))
            chiave_prima = chiave
    return gruppi


def proponi(vista, intestazioni):
    """Per ogni colonna il campo con lo stesso nome o la stessa etichetta (senza maiuscole), o ''."""
    noti = {}
    for nome, etichetta in campi(vista):
        noti[nome.lower()] = nome
        noti[etichetta.lower()] = nome
    return [noti.get(i.strip().lower(), "") for i in intestazioni]


def _testo(v):
    return "" if v is None else str(v).strip()


class Convertitore:
    """Valori leggibili del foglio → dati per la ModelForm (con cache dei record correlati)."""

    def __init__(self, form_class):
        self.form_class = form_class
        self.cache = {}

    def _correlati(self, nome, campo):
        if nome not in self.cache:
            self.cache[nome] = {str(o).strip().lower(): o.pk for o in campo.queryset[:5000]}
        return self.cache[nome]

    def _pk(self, nome, campo, testo):
        if testo.isdigit() and campo.queryset.filter(pk=int(testo)).exists():
            return testo
        return str(self._correlati(nome, campo).get(testo.lower(), testo))

    def __call__(self, nome, valore):
        campo = self.form_class.base_fields.get(nome)
        testo = _testo(valore)
        if campo is None:
            return testo
        if isinstance(campo, forms.ModelMultipleChoiceField):
            return [self._pk(nome, campo, t.strip()) for t in testo.split(",") if t.strip()]
        if isinstance(campo, forms.ModelChoiceField):
            return self._pk(nome, campo, testo) if testo else ""
        if isinstance(campo, forms.BooleanField):
            return "on" if testo.lower() in VERI else ""
        if isinstance(campo, forms.ChoiceField):
            scelte = {str(k).lower(): k for k, _ in campo.choices}
            scelte.update({str(e).lower(): k for k, e in campo.choices})
            return scelte.get(testo.lower(), testo)
        if isinstance(campo, (forms.DateField, forms.DateTimeField)):
            if isinstance(valore, datetime.datetime):
                return valore.date().isoformat() if isinstance(campo, forms.DateField) else valore.isoformat()
            if isinstance(valore, datetime.date):
                return valore.isoformat()
            for formato in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y"):
                try:
                    return datetime.datetime.strptime(testo, formato).date().isoformat()
                except ValueError:
                    pass
            return testo
        if isinstance(campo, (forms.DecimalField, forms.FloatField, forms.IntegerField)) and isinstance(valore, str):
            if "," in testo:
                testo = testo.replace(".", "").replace(",", ".")
            try:
                Decimal(testo)
            except InvalidOperation:
                pass
            return testo
        return testo


def valida(vista, request, intestazioni, righe, mappa, aggiorna):
    """(operazioni, errori): operazioni = [(form, nuovo)], errori = [{riga, campo, messaggio}]. Con colonne «riga.»
    ogni form porta in `_righe` le form delle sue righe."""
    if vista.inlines and any(m.startswith(RIGA) for m in mappa if m):
        return _valida_con_righe(vista, request, righe, mappa, aggiorna)
    form_class = vista.get_form_class(request)
    converti = Convertitore(form_class)
    colonne = [(i, nome) for i, nome in enumerate(mappa) if nome]
    chiave = vista.import_key if aggiorna and vista.import_key in mappa else None
    esistenti = vista.get_queryset(request)
    puo_aggiungere, puo_modificare = vista.has_add_permission(request), vista.has_change_permission(request)
    operazioni, errori = [], []
    for n, riga in enumerate(righe, start=2):            # riga 1 = intestazioni, come in Excel
        istanza = None
        if chiave:
            valore = _testo(riga[mappa.index(chiave)])
            istanza = esistenti.filter(**{chiave: valore}).first() if valore else None
        if istanza is None and not puo_aggiungere:
            errori.append({"riga": n, "campo": "", "messaggio": "non hai il permesso di creare record"})
            continue
        if istanza is not None and not puo_modificare:
            errori.append({"riga": n, "campo": "", "messaggio": "non hai il permesso di modificare record"})
            continue
        dati = {}
        if istanza is not None:                          # aggiornamento: i campi non mappati restano com'erano
            from django.forms.models import model_to_dict
            dati.update(model_to_dict(istanza, fields=list(form_class.base_fields)))
        for i, nome in colonne:
            if nome in form_class.base_fields:
                dati[nome] = converti(nome, riga[i])
        form = form_class(data=dati, instance=istanza)
        if form.is_valid():
            operazioni.append((form, istanza is None))
        else:
            for campo, messaggi in form.errors.items():
                etichetta = vista.etichetta(campo) if campo != "__all__" else ""
                errori.extend({"riga": n, "campo": etichetta, "messaggio": str(m)} for m in messaggi)
    return operazioni, errori


def esegui(vista, request, intestazioni, righe, mappa, aggiorna):
    """Tutto o niente: se una riga non è valida non si salva nulla. Restituisce (nuovi, aggiornati, errori)."""
    operazioni, errori = valida(vista, request, intestazioni, righe, mappa, aggiorna)
    if errori:
        return 0, 0, errori
    nuovi = aggiornati = 0
    with transaction.atomic():
        for form, nuovo in operazioni:
            obj = form.save(commit=False)
            vista.save_model(request, obj, form, change=not nuovo)
            righe_form = getattr(form, "_righe", None)
            if righe_form is not None:
                inline = vista.inlines[0]
                if not nuovo:                              # aggiornando un documento, le righe del file sostituiscono le sue
                    inline.model._default_manager.filter(**{inline.fk: obj}).delete()
                for rf in righe_form:
                    riga = rf.save(commit=False)
                    setattr(riga, inline.fk, obj)
                    riga.save()
                vista.dopo_righe(request, obj)
            nuovi, aggiornati = nuovi + nuovo, aggiornati + (not nuovo)
    return nuovi, aggiornati, []


def _predefiniti(form_class):
    """I valori predefiniti del modello per i campi del form (sconto 0, data di oggi…): li usano i record nuovi per ciò
    che il file non dice."""
    from django.db.models.fields import NOT_PROVIDED
    modello = form_class._meta.model
    valori = {}
    for nome, campo in form_class.base_fields.items():
        try:
            f = modello._meta.get_field(nome)
        except Exception:                                   # noqa: BLE001 (campi solo del form)
            continue
        if getattr(f, "default", NOT_PROVIDED) is not NOT_PROVIDED:
            valore = f.default() if callable(f.default) else f.default
            if isinstance(campo, forms.BooleanField):
                valori[nome] = "on" if valore else ""
            elif hasattr(valore, "isoformat"):
                valori[nome] = valore.isoformat()
            elif valore is not None:
                valori[nome] = str(valore)
    return valori


def _valida_con_righe(vista, request, righe, mappa, aggiorna):
    form_class = vista.get_form_class(request)
    inline = vista.inlines[0]
    riga_class = inline.form_class(getattr(getattr(request, "azienda", None), "pk", None))
    converti, converti_riga = Convertitore(form_class), Convertitore(riga_class)
    predefiniti_riga = _predefiniti(riga_class)
    testata = [(i, nome) for i, nome in enumerate(mappa) if nome and not nome.startswith(RIGA)]
    di_riga = [(i, nome[len(RIGA):]) for i, nome in enumerate(mappa) if nome and nome.startswith(RIGA)]
    chiave = vista.import_key if aggiorna and vista.import_key in mappa else None
    esistenti = vista.get_queryset(request)
    puo_aggiungere, puo_modificare = vista.has_add_permission(request), vista.has_change_permission(request)
    operazioni, errori = [], []
    for n, gruppo in _gruppi(righe, testata):
        prima = gruppo[0][1]
        istanza = None
        if chiave:
            valore = _testo(prima[mappa.index(chiave)])
            istanza = esistenti.filter(**{chiave: valore}).first() if valore else None
        if (istanza is None and not puo_aggiungere) or (istanza is not None and not puo_modificare):
            errori.append({"riga": n, "campo": "", "messaggio": "non hai il permesso di creare o modificare questo documento"})
            continue
        dati = {} if istanza is not None else _predefiniti(form_class)
        if istanza is not None:
            from django.forms.models import model_to_dict
            dati.update(model_to_dict(istanza, fields=list(form_class.base_fields)))
        for i, nome in testata:
            if nome in form_class.base_fields:
                dati[nome] = converti(nome, prima[i])
        form = form_class(data=dati, instance=istanza)
        righe_form, ok = [], form.is_valid()
        if not ok:
            for campo, messaggi in form.errors.items():
                etichetta = vista.etichetta(campo) if campo != "__all__" else ""
                errori.extend({"riga": n, "campo": etichetta, "messaggio": str(m)} for m in messaggi)
        for nr, riga in gruppo:
            dati_riga = {nome: converti_riga(nome, riga[i]) for i, nome in di_riga if nome in riga_class.base_fields}
            if not any(v not in ("", None, []) for v in dati_riga.values()):
                continue
            rf = riga_class(data={**predefiniti_riga, **dati_riga})
            if rf.is_valid():
                righe_form.append(rf)
            else:
                for campo, messaggi in rf.errors.items():
                    errori.extend({"riga": nr, "campo": f"Riga · {campo}" if campo != "__all__" else "Riga", "messaggio": str(m)} for m in messaggi)
        if ok:
            form._righe = righe_form
            operazioni.append((form, istanza is None))
    return operazioni, errori


def in_background(modulo, slug, utente_id, azienda_id, file, mappa, aggiorna):
    """Lavoro: import grande; l'esito arriva per email. Il file si cancella comunque."""
    from core.viste import registry
    vista = next(v for v in registry.viste_di(modulo) if v.slug == slug)
    utente = get_user_model().objects.get(pk=utente_id)
    richiesta = SimpleNamespace(user=utente, azienda=Azienda.objects.filter(pk=azienda_id).first())
    try:
        intestazioni, righe = leggi(file)
        nuovi, aggiornati, errori = esegui(vista, richiesta, intestazioni, righe, mappa, aggiorna)
    finally:
        percorso(file).unlink(missing_ok=True)
    if errori:
        testo = "Import annullato, nessuna riga salvata. Errori:\n" + "\n".join(
            f"riga {e['riga']} {e['campo']}: {e['messaggio']}" for e in errori[:200])
    else:
        testo = f"Import completato: {nuovi} nuovi, {aggiornati} aggiornati."
    if utente.email:
        send_mail(f"[{settings.THEME.get('brand', '')}] Import {vista.verbose_name_plural}", testo, None, [utente.email])
    return testo
