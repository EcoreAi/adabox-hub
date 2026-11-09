"""Che cosa si può automatizzare: tipi di record (Dominio) ed eventi (Evento), in parole di chi usa il gestionale.

L'elenco è chiuso e scritto qui, non generato dai modelli: una regola vede solo i campi pensati per le email e le
condizioni, e non può toccare uno stato o un documento fiscale. Compare solo ciò che appartiene a moduli installati."""
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

from django.apps import apps
from django.conf import settings
from django.utils import timezone

from core.generici import url_record
from core.viste.gruppi import numero


@dataclass
class Dominio:
    codice: str
    nome: str
    modulo: str
    campi: dict                                 # {nome: (etichetta, esempio)}
    valori: Callable                            # record -> {nome: testo}
    esterni: dict = field(default_factory=dict)     # {ruolo: (etichetta, record -> email)}
    interni: dict = field(default_factory=dict)     # {ruolo: (etichetta, record -> utente)}
    condizioni: dict = field(default_factory=dict)  # {nome: (etichetta, tipo, record -> valore[, scelte])}
    assegna: str = ""                               # campo dell'assegnatario, se la regola può assegnare
    modello: str = ""                               # app_label.Model dei record (per cambiare campi e premere bottoni)


@dataclass
class Evento:
    codice: str
    dominio: str
    nome: str
    modello: str = ""                           # eventi al salvataggio: il modello osservato
    osserva: tuple = ()                         # attname dei campi di cui serve il valore precedente
    scatta: Callable = None                     # (prima, obj, creato) -> bool
    cerca: Callable = None                      # eventi a tempo: (azienda, giorni) -> [(record, chiave, extra)]
    giorni: str = ""                            # eventi a tempo: la frase attorno ai giorni, con {n}
    giorni_default: int = 0
    urgente: bool = False                       # a tempo: controllato a ogni ora, anche di notte

    @property
    def a_tempo(self):
        return self.cerca is not None


def _euro(valore):
    return f"{numero(valore)} €"


def _data(valore):
    return f"{valore:%d/%m/%Y}" if valore else ""


def _link(obj):
    return f"{settings.SITO_URL}{url_record(obj) or ''}"


def _email(contatto):
    return contatto.email if contatto else ""


def _nome(utente):
    return (utente.get_full_name() or utente.username) if utente else ""


def _fatture():
    from fatturazione import operazioni
    from fatturazione.models import Fattura, Scadenza

    def valori(f):
        return {"documento": str(f), "numero": f.numero, "cliente": f.cliente.nome, "data": _data(f.data),
                "totale": _euro(f.totale), "residuo": _euro(f.residuo), "link_interno": _link(f),
                "paga_online": operazioni.frase_pagamento(f), "link_pagamento": operazioni.link_pagamento(f)}

    def scadute(azienda, giorni):
        limite = timezone.localdate() - timedelta(days=giorni)
        return _scadenze(Scadenza.objects.filter(fattura__azienda=azienda, data__lte=limite))

    def in_arrivo(azienda, giorni):
        oggi = timezone.localdate()
        return _scadenze(Scadenza.objects.filter(fattura__azienda=azienda, data__gt=oggi, data__lte=oggi + timedelta(days=giorni)))

    def _scadenze(qs):
        for s in qs.filter(pagata=False, fattura__stato=Fattura.EMESSA).select_related("fattura__cliente").order_by("data", "pk"):
            ritardo = (timezone.localdate() - s.data).days
            yield s.fattura, f"s{s.pk}", {"scadenza": _data(s.data), "importo_scadenza": _euro(s.residuo), "giorni_ritardo": max(ritardo, 0)}

    return Dominio(
        "fattura", "Fattura", "fatturazione",
        {"documento": ("Il documento", "Fattura 12/2026"), "numero": ("Numero", "12/2026"), "cliente": ("Nome del cliente", "Rossi Srl"),
         "data": ("Data", "02/10/2026"), "totale": ("Totale", "1.220,00 €"), "residuo": ("Ancora da incassare", "1.220,00 €"),
         "scadenza": ("Data della scadenza", "01/11/2026"), "importo_scadenza": ("Importo della scadenza", "610,00 €"),
         "giorni_ritardo": ("Giorni di ritardo", "7"),
         "paga_online": ("Frase con il link per pagare online (vuota se non si può)", "\nPuò pagarla online da questo link: https://hub.example.it/pagamenti/fattura/…/"),
         "link_pagamento": ("Solo il link per pagare online (vuoto se non si può)", "https://hub.example.it/pagamenti/fattura/…/"),
         "link_interno": ("Link interno alla fattura", "https://hub.example.it/fatturazione/fatture/1/")},
        valori,
        esterni={"cliente": ("Il cliente", lambda f: f.cliente.email)},
        condizioni={"totale": ("Totale", "numero", lambda f: f.totale),
                    "residuo": ("Ancora da incassare", "numero", lambda f: f.residuo),
                    "pa": ("Il cliente è una PA", "sino", lambda f: f.cliente.pubblica_amministrazione),
                    "cliente": ("Nome del cliente", "testo", lambda f: f.cliente.nome)}), [
        Evento("fattura.emessa", "fattura", "Una fattura viene emessa", "fatturazione.Fattura", ("stato",),
               lambda p, f, c: f.stato == Fattura.EMESSA and p.get("stato") != Fattura.EMESSA),
        Evento("fattura.incassata", "fattura", "Una fattura è incassata tutta", "fatturazione.Fattura", ("pagata",),
               lambda p, f, c: f.pagata and f.incassabile and f.stato == Fattura.EMESSA and p.get("pagata") is False and not c),
        Evento("fattura.scaduta", "fattura", "Una scadenza non è stata pagata", cerca=scadute,
               giorni="da {n} giorni", giorni_default=7),
        Evento("fattura.in_scadenza", "fattura", "Una scadenza si avvicina", cerca=in_arrivo,
               giorni="tra {n} giorni al massimo", giorni_default=3),
    ]


def _ticket():
    from helpdesk.models import Ticket

    def valori(t):
        return {"ticket": str(t), "numero": t.numero, "oggetto_ticket": t.oggetto, "cliente": t.contatto.nome if t.contatto else "",
                "priorita": t.get_priorita_display(), "assegnatario": _nome(t.assegnatario), "link_interno": _link(t)}

    def sla(azienda, giorni):
        qs = Ticket.objects.filter(azienda=azienda, fase__chiusa=False, scadenza_sla__lte=timezone.now()).select_related("contatto", "assegnatario")
        return [(t, f"sla{t.scadenza_sla:%Y%m%d%H%M}", {}) for t in qs]

    def senza_risposta(azienda, giorni):
        limite = timezone.now() - timedelta(days=giorni)
        qs = Ticket.objects.filter(azienda=azienda, fase__chiusa=False, creato__lte=limite).select_related("contatto", "assegnatario")
        return [(t, "aperto", {}) for t in qs]

    return Dominio(
        "ticket", "Ticket", "helpdesk",
        {"ticket": ("Il ticket", "HD/2026/0042 Non riesco a stampare"), "numero": ("Numero", "HD/2026/0042"),
         "oggetto_ticket": ("Oggetto", "Non riesco a stampare"), "cliente": ("Cliente", "Rossi Srl"), "priorita": ("Priorità", "Alta"),
         "assegnatario": ("Assegnatario", "Sara Bianchi"), "link_interno": ("Link interno al ticket", "https://hub.example.it/helpdesk/ticket/42/")},
        valori,
        esterni={"cliente": ("Il cliente", lambda t: t.email_cliente or _email(t.contatto))},
        interni={"assegnatario": ("Chi ha in carico il ticket", lambda t: t.assegnatario)},
        condizioni={"priorita": ("Priorità", "scelta", lambda t: t.priorita, Ticket.PRIORITA),
                    "senza_assegnatario": ("Senza assegnatario", "sino", lambda t: t.assegnatario_id is None),
                    "team": ("Team", "testo", lambda t: str(t.team or "")),
                    "oggetto": ("Oggetto", "testo", lambda t: t.oggetto)},
        assegna="assegnatario"), [
        Evento("ticket.creato", "ticket", "Si apre un ticket", "helpdesk.Ticket", (), lambda p, t, c: c),
        Evento("ticket.assegnato", "ticket", "Un ticket viene assegnato", "helpdesk.Ticket", ("assegnatario_id",),
               lambda p, t, c: bool(t.assegnatario_id) and not c and p.get("assegnatario_id") != t.assegnatario_id),
        Evento("ticket.chiuso", "ticket", "Un ticket viene chiuso", "helpdesk.Ticket", ("chiuso_il",),
               lambda p, t, c: bool(t.chiuso_il) and not c and p.get("chiuso_il") is None),
        Evento("ticket.sla", "ticket", "Un ticket supera il tempo di risposta", cerca=sla, urgente=True),
        Evento("ticket.aperto_da", "ticket", "Un ticket è ancora aperto", cerca=senza_risposta,
               giorni="dopo {n} giorni", giorni_default=5),
    ]


def _vendite():
    from vendite.models import OrdineVendita

    def valori(o):
        return {"documento": f"{o.titolo_documento} {o}", "numero": str(o), "cliente": o.cliente.nome, "data": _data(o.data),
                "valido_fino_al": _data(o.validita), "totale": _euro(o.totale), "commerciale": _nome(o.commerciale), "link_interno": _link(o)}

    def aperti(azienda):
        return OrdineVendita.objects.filter(azienda=azienda, stato=OrdineVendita.INVIATO).select_related("cliente", "commerciale")

    def in_scadenza(azienda, giorni):
        oggi = timezone.localdate()
        return [(o, f"v{o.validita:%Y%m%d}", {}) for o in aperti(azienda).filter(validita__gte=oggi, validita__lte=oggi + timedelta(days=giorni))]

    def senza_risposta(azienda, giorni):
        return [(o, "risposta", {}) for o in aperti(azienda).filter(data__lte=timezone.localdate() - timedelta(days=giorni))]

    return Dominio(
        "ordine", "Preventivo o ordine", "vendite",
        {"documento": ("Il documento", "Preventivo PV/2026/0007"), "numero": ("Numero", "PV/2026/0007"), "cliente": ("Nome del cliente", "Rossi Srl"),
         "data": ("Data", "02/10/2026"), "valido_fino_al": ("Valido fino al", "30/11/2026"), "totale": ("Totale", "1.220,00 €"),
         "commerciale": ("Commerciale", "Marco Neri"), "link_interno": ("Link interno", "https://hub.example.it/vendite/ordini/1/")},
        valori,
        esterni={"cliente": ("Il cliente", lambda o: o.cliente.email)},
        interni={"commerciale": ("Il commerciale", lambda o: o.commerciale)},
        condizioni={"totale": ("Totale", "numero", lambda o: o.totale), "cliente": ("Nome del cliente", "testo", lambda o: o.cliente.nome)},
        assegna="commerciale"), [
        Evento("ordine.confermato", "ordine", "Un ordine viene confermato", "vendite.OrdineVendita", ("stato",),
               lambda p, o, c: o.stato == OrdineVendita.CONFERMATO and p.get("stato") != OrdineVendita.CONFERMATO),
        Evento("ordine.in_scadenza", "ordine", "Un preventivo inviato sta per scadere", cerca=in_scadenza,
               giorni="tra {n} giorni al massimo", giorni_default=3),
        Evento("ordine.senza_risposta", "ordine", "Un preventivo inviato resta senza risposta", cerca=senza_risposta,
               giorni="da {n} giorni", giorni_default=7),
    ]


def _crm():
    from crm.models import Opportunita

    def valori(o):
        return {"opportunita": o.titolo, "contatto": str(o.contatto or o.nome_contatto), "valore": _euro(o.valore_atteso),
                "chiusura": _data(o.chiusura_prevista), "commerciale": _nome(o.commerciale), "link_interno": _link(o)}

    def scadute(azienda, giorni):
        limite = timezone.localdate() - timedelta(days=giorni)
        qs = Opportunita.objects.filter(azienda=azienda, stato=Opportunita.APERTA, chiusura_prevista__lte=limite).select_related("contatto", "commerciale")
        return [(o, f"c{o.chiusura_prevista:%Y%m%d}", {}) for o in qs]

    return Dominio(
        "opportunita", "Opportunità", "crm",
        {"opportunita": ("Titolo", "Nuovo sito web"), "contatto": ("Contatto", "Rossi Srl"), "valore": ("Valore atteso", "8.000,00 €"),
         "chiusura": ("Chiusura prevista", "30/11/2026"), "commerciale": ("Commerciale", "Marco Neri"),
         "link_interno": ("Link interno", "https://hub.example.it/crm/opportunita/1/")},
        valori,
        esterni={"contatto": ("Il contatto", lambda o: o.email or _email(o.contatto))},
        interni={"commerciale": ("Il commerciale", lambda o: o.commerciale)},
        condizioni={"valore": ("Valore atteso", "numero", lambda o: o.valore_atteso),
                    "probabilita": ("Probabilità %", "numero", lambda o: o.probabilita),
                    "senza_commerciale": ("Senza commerciale", "sino", lambda o: o.commerciale_id is None)},
        assegna="commerciale"), [
        Evento("opportunita.creata", "opportunita", "Arriva una nuova opportunità", "crm.Opportunita", (), lambda p, o, c: c),
        Evento("opportunita.vinta", "opportunita", "Un'opportunità è vinta", "crm.Opportunita", ("stato",),
               lambda p, o, c: o.stato == Opportunita.VINTA and p.get("stato") != Opportunita.VINTA),
        Evento("opportunita.persa", "opportunita", "Un'opportunità è persa", "crm.Opportunita", ("stato",),
               lambda p, o, c: o.stato == Opportunita.PERSA and p.get("stato") != Opportunita.PERSA),
        Evento("opportunita.oltre", "opportunita", "Un'opportunità ha passato la chiusura prevista", cerca=scadute,
               giorni="da {n} giorni", giorni_default=1),
    ]


def _attivita():
    from todo.models import Attivita

    def scadute(azienda, giorni):
        limite = timezone.localdate() - timedelta(days=giorni)
        qs = Attivita.objects.filter(azienda=azienda, stato__in=[Attivita.APERTA, Attivita.IN_CORSO], scadenza__lte=limite).select_related("assegnatario")
        return [(a, f"a{a.scadenza:%Y%m%d}", {}) for a in qs]

    return Dominio(
        "attivita", "Attività", "todo",
        {"attivita": ("Titolo", "Richiamare Rossi"), "scadenza": ("Scadenza", "01/11/2026"), "assegnatario": ("Assegnatario", "Sara Bianchi"),
         "link_interno": ("Link interno", "https://hub.example.it/todo/attivita/1/")},
        lambda a: {"attivita": a.titolo, "scadenza": _data(a.scadenza), "assegnatario": _nome(a.assegnatario), "link_interno": _link(a)},
        interni={"assegnatario": ("Chi ha l'attività", lambda a: a.assegnatario), "autore": ("Chi l'ha creata", lambda a: a.creato_da)},
        condizioni={"senza_assegnatario": ("Senza assegnatario", "sino", lambda a: a.assegnatario_id is None)},
        assegna="assegnatario"), [
        Evento("attivita.creata", "attivita", "Si crea un'attività", "todo.Attivita", (), lambda p, a, c: c),
        Evento("attivita.scaduta", "attivita", "Un'attività è in ritardo", cerca=scadute, giorni="da {n} giorni", giorni_default=1),
    ]


def _contratti():
    from assistenza.models import Contratto

    def in_scadenza(azienda, giorni):
        oggi = timezone.localdate()
        qs = Contratto.objects.filter(azienda=azienda, attivo=True, fine__gte=oggi, fine__lte=oggi + timedelta(days=giorni)).select_related("cliente")
        return [(c, f"f{c.fine:%Y%m%d}", {}) for c in qs]

    return Dominio(
        "contratto", "Contratto di assistenza", "assistenza",
        {"contratto": ("Il contratto", "Premium 2026"), "cliente": ("Nome del cliente", "Rossi Srl"), "fine": ("Scade il", "31/12/2026"),
         "link_interno": ("Link interno", "https://hub.example.it/assistenza/contratti/1/")},
        lambda c: {"contratto": c.nome, "cliente": c.cliente.nome, "fine": _data(c.fine), "link_interno": _link(c)},
        esterni={"cliente": ("Il cliente", lambda c: c.cliente.email)}), [
        Evento("contratto.in_scadenza", "contratto", "Un contratto sta per scadere", cerca=in_scadenza,
               giorni="tra {n} giorni al massimo", giorni_default=30),
    ]


def _compiti():
    from progetti.models import Compito

    def scaduti(azienda, giorni):
        limite = timezone.localdate() - timedelta(days=giorni)
        qs = Compito.objects.filter(azienda=azienda, fase__chiusa=False, scadenza__lte=limite).select_related("progetto__responsabile")
        return [(c, f"c{c.scadenza:%Y%m%d}", {}) for c in qs]

    return Dominio(
        "compito", "Compito di progetto", "progetti",
        {"compito": ("Titolo", "Rifare la home"), "progetto": ("Progetto", "Sito Rossi"), "scadenza": ("Scadenza", "01/11/2026"),
         "link_interno": ("Link interno", "https://hub.example.it/progetti/compiti/1/")},
        lambda c: {"compito": c.titolo, "progetto": str(c.progetto), "scadenza": _data(c.scadenza), "link_interno": _link(c)},
        interni={"responsabile": ("Il responsabile del progetto", lambda c: c.progetto.responsabile)},
        condizioni={"priorita": ("Priorità", "scelta", lambda c: c.priorita, [(Compito.NORMALE, "Normale"), (Compito.ALTA, "Alta")])}), [
        Evento("compito.completato", "compito", "Un compito è completato", "progetti.Compito", ("completato_il",),
               lambda p, c, n: bool(c.completato_il) and p.get("completato_il") is None),
        Evento("compito.scaduto", "compito", "Un compito è in ritardo", cerca=scaduti, giorni="da {n} giorni", giorni_default=1),
    ]


FONTI = {"fatturazione": _fatture, "helpdesk": _ticket, "vendite": _vendite, "crm": _crm, "todo": _attivita,
         "assistenza": _contratti, "progetti": _compiti}
_cache = None


def _generici(gia):
    """Un dominio per ogni ModelView con l'azienda che non ha già un dominio proprio: eventi «creato», «modificato» e,
    se c'è un campo stato con scelte, «stato cambiato». Le condizioni sono i campi con scelte e i sì/no."""
    from core.viste import registry
    risultato = []
    for vv in registry._viste.values():
        for v in vv:
            label = v.opts.label
            if not v.company_field or label.lower() in gia or v.opts.app_label in ("core", "automazioni"):
                continue
            gia.add(label.lower())
            codice = f"v_{v.opts.label_lower.replace('.', '_')}"
            nome = str(v.opts.verbose_name_plural).capitalize()
            condizioni = {}
            for f in v.opts.concrete_fields:
                if f.choices:
                    condizioni[f.name] = (str(f.verbose_name).capitalize(), "scelta", (lambda n: lambda o: getattr(o, n))(f.name),
                                          [(k, str(t)) for k, t in f.flatchoices])
                elif f.get_internal_type() == "BooleanField" and f.editable:
                    condizioni[f.name] = (str(f.verbose_name).capitalize(), "sino", (lambda n: lambda o: getattr(o, n))(f.name))
            utenti = [f.name for f in v.opts.concrete_fields if f.is_relation and f.related_model is not None
                      and f.related_model._meta.label == "auth.User" and f.editable]
            dominio = Dominio(codice, nome, v.modulo, {"record": ("Il record", "…"), "link_interno": ("Link interno", "https://…")},
                              lambda o: {"record": str(o), "link_interno": _link(o)},
                              interni={u: (str(v.opts.get_field(u).verbose_name).capitalize(), (lambda n: lambda o: getattr(o, n))(u)) for u in utenti},
                              condizioni=condizioni, assegna=utenti[0] if utenti else "", modello=label)
            voci = [Evento(f"{codice}.creato", codice, f"Nasce un record: {str(v.opts.verbose_name)}", label, (), lambda p, o, n: n),
                    Evento(f"{codice}.modificato", codice, f"Cambia un record: {str(v.opts.verbose_name)}", label, (), lambda p, o, n: not n)]
            stato = next((f for f in v.opts.concrete_fields if f.name == "stato" and f.choices), None)
            if stato is not None:
                voci.append(Evento(f"{codice}.stato", codice, f"Cambia lo stato: {str(v.opts.verbose_name)}", label, ("stato",),
                                   lambda p, o, n: not n and "stato" in p and p["stato"] != o.stato))
            risultato.append((dominio, voci))
    return risultato


def _carica():
    global _cache
    if _cache is None:
        domini, eventi = {}, {}
        for modulo, fonte in FONTI.items():
            if apps.is_installed(modulo):
                dominio, voci = fonte()
                if not dominio.modello:
                    dominio.modello = next((e.modello for e in voci if e.modello), "")
                domini[dominio.codice] = dominio
                eventi.update({e.codice: e for e in voci})
        try:
            gia = {d.modello.lower() for d in domini.values() if d.modello}
            for dominio, voci in _generici(gia):
                domini[dominio.codice] = dominio
                eventi.update({e.codice: e for e in voci})
        except Exception:                           # noqa: BLE001 (le viste non ancora pronte: solo i domini propri)
            pass
        _cache = domini, eventi
    return _cache


def modificabili(dominio):
    """[(campo, etichetta, tipo, scelte)] dei campi che l'azione «cambia un campo» può impostare."""
    if not dominio.modello:
        return []
    modello = apps.get_model(dominio.modello)
    risultato = []
    for f in modello._meta.concrete_fields:
        if not f.editable or f.primary_key or f.is_relation or f.name in ("azienda", "proprieta"):
            continue
        tipo = "scelta" if f.choices else {"BooleanField": "sino", "DateField": "data", "DecimalField": "numero",
                                           "IntegerField": "numero", "PositiveIntegerField": "numero",
                                           "PositiveSmallIntegerField": "numero", "CharField": "testo", "TextField": "testo"}.get(f.get_internal_type())
        if tipo:
            risultato.append((f.name, str(f.verbose_name).capitalize(), tipo, [(str(k), str(t)) for k, t in f.flatchoices] if f.choices else []))
    return risultato


def bottoni(dominio):
    """[(nome, etichetta)] dei bottoni della vista del record che una regola può premere (non quelli marcati ai=False)."""
    if not dominio.modello:
        return []
    from core.viste import registry
    vista = registry.per_modello(apps.get_model(dominio.modello))
    if vista is None:
        return []
    return [(n, vista.etichetta_metodo(n)) for n in vista.buttons if getattr(getattr(vista, n, None), "ai", True) is not False]


def domini():
    return _carica()[0]


def eventi():
    return _carica()[1]


def evento(codice):
    return eventi().get(codice)


def dominio_di(codice_evento):
    e = evento(codice_evento)
    return domini()[e.dominio] if e else None


def eventi_del_modello(modello):
    etichetta = modello._meta.label_lower
    return [e for e in eventi().values() if e.modello.lower() == etichetta]


def modelli_osservati():
    return {apps.get_model(e.modello) for e in eventi().values() if e.modello}
