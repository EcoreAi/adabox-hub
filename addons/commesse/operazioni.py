"""Il ciclo della commessa: dalle ore alla fattura, con i margini e il monte ore dei contratti."""
from collections import OrderedDict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from assistenza.models import Contratto, DatiTicket, Supporto
from core import modelli_email, parametri
from fatturazione.models import Fattura, RigaFattura
from fiscale import calcoli
from timesheet.models import RigaOre

from .models import Condizioni, CostoOrario, FatturaProgetto, OreFatturate, OreTicket, TariffaPersona

SOGLIE_MONTE = (80, 100)


def condizioni_di(progetto):
    return Condizioni.objects.get_or_create(progetto=progetto, defaults={"azienda": progetto.azienda})[0]


def _tariffe(condizioni):
    return {t.utente_id: t.tariffa for t in condizioni.tariffe.all()}


def _costi(azienda):
    """{utente: [(dal, costo)]}, dal più recente."""
    costi = {}
    for c in CostoOrario.objects.filter(azienda=azienda).order_by("-dal"):
        costi.setdefault(c.utente_id, []).append((c.dal, c.costo))
    return costi


def _costo(costi, utente_id, giorno):
    return next((costo for dal, costo in costi.get(utente_id, []) if dal <= giorno), Decimal(0))


# ---------- monte ore

def contratto_del_ticket(ticket):
    dati = DatiTicket.objects.filter(ticket=ticket).select_related("progetto").first()
    if dati and dati.progetto_id:
        supporto = Supporto.objects.filter(progetto=dati.progetto).first()
        if supporto:
            return supporto.contratto_valido()
    return Contratto.valido_per(ticket.contatto)


def ore_coperte(contratto):
    """{riga: ore comprese nel monte}, consumando il monte dalla riga più vecchia."""
    rimaste, coperte = contratto.ore_incluse, {}
    if rimaste <= 0:
        return coperte
    for voce in contratto.ore_ticket.select_related("riga").order_by("riga__data", "riga__pk"):
        quota = min(rimaste, voce.riga.ore)
        coperte[voce.riga_id] = quota
        rimaste -= quota
        if rimaste <= 0:
            break
    return coperte


def monte_ore(contratto):
    usate = contratto.ore_ticket.aggregate(t=Sum("riga__ore"))["t"] or Decimal(0)
    incluse = contratto.ore_incluse
    percentuale = int(usate * 100 / incluse) if incluse else 0
    return {"contratto": contratto, "incluse": incluse, "usate": usate, "residue": max(incluse - usate, Decimal(0)),
            "oltre": max(usate - incluse, Decimal(0)), "percentuale": percentuale,
            "percentuale_barra": min(percentuale, 100),
            "livello": "oltre" if percentuale >= 100 else ("allerta" if percentuale >= 80 else "ok")}


def _avvisa_monte(contratto):
    """All'80% e al 100%, una volta sola: a chi gestisce il progetto, così parla con il cliente per tempo."""
    if contratto is None or contratto.ore_incluse <= 0:
        return
    stato = monte_ore(contratto)
    soglia = max((s for s in SOGLIE_MONTE if stato["percentuale"] >= s), default=0)
    if soglia <= contratto.monte_avvisato:
        return
    Contratto.objects.filter(pk=contratto.pk).update(monte_avvisato=soglia)
    supporti = Supporto.objects.filter(contratto=contratto).select_related("responsabile", "progetto__responsabile")
    indirizzi = {u.email for s in supporti for u in (s.responsabile, s.progetto.responsabile) if u and u.email}
    if indirizzi:
        modelli_email.messaggio("commesse.monte_ore", contratto.azienda, {
            "contratto": str(contratto), "soglia": soglia, "usate": stato["usate"], "incluse": stato["incluse"]},
            sorted(indirizzi)).send(fail_silently=True)


# ---------- ore sui ticket

def _collega_al_ticket(riga, ticket):
    voce, _ = OreTicket.objects.update_or_create(riga=riga, defaults={"ticket": ticket, "contratto": contratto_del_ticket(ticket)})
    _avvisa_monte(voce.contratto)
    return voce


@transaction.atomic
def registra_su_ticket(ticket, utente, ore, descrizione="", data=None):
    dati = DatiTicket.objects.filter(ticket=ticket).select_related("progetto").first()
    progetto = dati.progetto if dati else None
    if progetto is None:
        raise ValidationError("Il ticket non è collegato a un progetto: indicalo prima di registrare le ore.")
    riga = RigaOre(azienda=ticket.azienda, utente=utente, progetto=progetto, ore=ore,
                   compito=dati.compito, descrizione=descrizione or f"Ticket {ticket.numero}")
    if data:
        riga.data = data
    riga.full_clean(exclude=["azienda"])
    riga.save()
    _collega_al_ticket(riga, ticket)
    return riga


def ore_da_cronometro(sender, riga, ticket_id=None, **kwargs):
    if ticket_id:
        from helpdesk.models import Ticket
        ticket = Ticket.objects.filter(pk=ticket_id, azienda=riga.azienda).first()
        if ticket:
            _collega_al_ticket(riga, ticket)


# ---------- dalle ore alla fattura

def _righe_aperte(progetto, al=None):
    righe = (RigaOre.objects.filter(progetto=progetto, fatturabile=True, bloccata=False)
             .select_related("utente", "compito", "su_ticket__contratto").order_by("data", "pk"))
    if al:
        righe = righe.filter(data__lte=al)
    if parametri.leggi("commesse.solo_approvate", progetto.azienda):
        righe = righe.filter(approvata=True)
    return righe


def da_fatturare(progetto, al=None):
    """[{riga, ore, tariffa, importo}]: le ore comprese nel monte del contratto non si fatturano."""
    condizioni = condizioni_di(progetto)
    if condizioni.tipo != Condizioni.ORE:
        return []
    tariffe = _tariffe(condizioni)
    coperture = {}
    voci = []
    for riga in _righe_aperte(progetto, al):
        ore = riga.ore
        contratto = riga.su_ticket.contratto if hasattr(riga, "su_ticket") else None
        if contratto:
            coperte = coperture.setdefault(contratto.pk, ore_coperte(contratto))
            ore -= coperte.get(riga.pk, Decimal(0))
        if ore <= 0:
            continue
        tariffa = tariffe.get(riga.utente_id, condizioni.tariffa)
        voci.append({"riga": riga, "ore": ore, "tariffa": tariffa, "importo": calcoli.arrotonda(ore * tariffa)})
    return voci


def _nome_gruppo(riga):
    persona = riga.utente.get_full_name() or riga.utente.username if riga.utente_id else ""
    return " · ".join(p for p in (riga.compito.titolo if riga.compito_id else "Attività", persona) if p)


@transaction.atomic
def fattura_ore(progetto, pk_righe=None, al=None):
    """Fattura in bozza con le ore scelte: una riga per compito e persona. Le ore restano bloccate finché vale."""
    if progetto.cliente_id is None:
        raise ValidationError(f"{progetto} non ha un cliente: indicalo prima di fatturare.")
    condizioni = condizioni_di(progetto)
    voci = da_fatturare(progetto, al)
    if pk_righe is not None:
        scelte = set(pk_righe)
        voci = [v for v in voci if v["riga"].pk in scelte]
    if not voci:
        raise ValidationError("Non ci sono ore da fatturare.")
    if any(not v["tariffa"] for v in voci):
        raise ValidationError("Manca la tariffa: indicala nelle condizioni del progetto.")
    fattura = Fattura.objects.create(azienda=progetto.azienda, cliente=progetto.cliente, termine_pagamento=condizioni.termine_pagamento,
                                     causale=f"Ore su {progetto.nome}"[:200])
    gruppi = OrderedDict()
    for v in voci:
        gruppi.setdefault((v["riga"].compito_id, v["riga"].utente_id, v["tariffa"]), []).append(v)
    for (_, _, tariffa), elenco in gruppi.items():
        RigaFattura.objects.create(fattura=fattura, descrizione=_nome_gruppo(elenco[0]["riga"])[:250], prezzo=tariffa,
                                   quantita=sum((v["ore"] for v in elenco), Decimal(0)), aliquota=condizioni.aliquota)
        for v in elenco:
            OreFatturate.objects.create(riga=v["riga"], fattura=fattura, ore=v["ore"])
    RigaOre.objects.filter(pk__in=[v["riga"].pk for v in voci]).update(bloccata=True)
    FatturaProgetto.objects.create(fattura=fattura, progetto=progetto)
    fattura.ricalcola()
    return fattura


def fatturato_corpo(progetto):
    """L'imponibile già fatturato al progetto (fatture non annullate, meno le note di credito emesse)."""
    totale = Decimal(0)
    for f in Fattura.objects.filter(su_progetto__progetto=progetto).exclude(stato=Fattura.ANNULLATA):
        totale += f.imponibile
        totale -= sum((n.imponibile for n in f.note_credito.filter(stato=Fattura.EMESSA)), Decimal(0))
    return totale


def residuo_corpo(progetto):
    return condizioni_di(progetto).importo_corpo - fatturato_corpo(progetto)


def _fattura_progetto(progetto, condizioni, descrizione, importo):
    if progetto.cliente_id is None:
        raise ValidationError(f"{progetto} non ha un cliente: indicalo prima di fatturare.")
    fattura = Fattura.objects.create(azienda=progetto.azienda, cliente=progetto.cliente, termine_pagamento=condizioni.termine_pagamento,
                                     causale=progetto.nome[:200])
    RigaFattura.objects.create(fattura=fattura, descrizione=descrizione[:250], prezzo=importo, aliquota=condizioni.aliquota)
    FatturaProgetto.objects.create(fattura=fattura, progetto=progetto)
    fattura.ricalcola()
    return fattura


@transaction.atomic
def fattura_corpo(progetto, importo=None, descrizione=""):
    """La fattura a corpo: senza importo, tutto il residuo; con un importo, un acconto. Mai oltre il valore."""
    condizioni = condizioni_di(progetto)
    if condizioni.tipo != Condizioni.CORPO or condizioni.importo_corpo <= 0:
        raise ValidationError("Indica l'importo a corpo nelle condizioni del progetto.")
    residuo = residuo_corpo(progetto)
    importo = residuo if importo is None else Decimal(importo).quantize(Decimal("0.01"))
    if importo <= 0 or residuo <= 0:
        raise ValidationError("Il progetto a corpo è già fatturato per intero.")
    if importo > residuo:
        raise ValidationError(f"Restano da fatturare {residuo:.2f} €: non puoi fatturarne {importo:.2f}.")
    acconto = importo < residuo
    testo = descrizione or (f"Acconto su {progetto.nome}" if acconto else progetto.nome if residuo == condizioni.importo_corpo
                            else f"Saldo di {progetto.nome}")
    return _fattura_progetto(progetto, condizioni, testo, importo)


def controlla_tappe(condizioni):
    """La somma delle tappe non supera il valore del progetto."""
    totale = sum((t.valore for t in condizioni.tappe.all()), Decimal(0))
    if condizioni.importo_corpo and totale > condizioni.importo_corpo:
        raise ValidationError(f"Le tappe valgono {totale:.2f} €, più del valore del progetto ({condizioni.importo_corpo:.2f} €).")
    return totale


@transaction.atomic
def completa_tappa(tappa, utente=None):
    """La tappa è raggiunta: si segna e nasce la sua fattura in bozza (una volta sola)."""
    condizioni = tappa.condizioni
    if condizioni.tipo != Condizioni.TAPPE:
        raise ValidationError("Il progetto non si fattura a tappe.")
    if tappa.fattura_id and tappa.fattura.stato != Fattura.ANNULLATA:
        raise ValidationError(f"La tappa ha già la {tappa.fattura}.")
    controlla_tappe(condizioni)
    progetto = condizioni.progetto
    fattura = _fattura_progetto(progetto, condizioni, f"{progetto.nome}: {tappa.nome}", tappa.valore)
    tappa.completata_il, tappa.fattura = timezone.localdate(), fattura
    tappa.save(update_fields=["completata_il", "fattura"])
    from core import chatter
    chatter.scrivi(progetto, utente, f"Tappa «{tappa.nome}» completata: {fattura} in bozza.", tipo="nota")
    return fattura


def _libera(fattura):
    righe = list(OreFatturate.objects.filter(fattura=fattura).values_list("riga", flat=True))
    if righe:
        RigaOre.objects.filter(pk__in=righe).update(bloccata=False)
        OreFatturate.objects.filter(fattura=fattura).delete()


def fattura_cambiata(sender, instance, **kwargs):
    """Fattura annullata, o stornata per intero da una nota appena emessa: le ore tornano da fatturare."""
    if instance.stato == Fattura.ANNULLATA:
        _libera(instance)
    elif instance.stato == Fattura.EMESSA and instance.tipo == Fattura.NOTA_CREDITO and instance.fattura_origine_id \
            and instance.fattura_origine.stornata:
        _libera(instance.fattura_origine)


def fattura_eliminata(sender, instance, **kwargs):
    _libera(instance)


# ---------- redditività

def redditivita(progetto):
    costi = _costi(progetto.azienda)
    ore_totali, costo_ore, per_persona = Decimal(0), Decimal(0), {}
    for riga in RigaOre.objects.filter(progetto=progetto).select_related("utente"):
        costo = riga.ore * _costo(costi, riga.utente_id, riga.data)
        ore_totali += riga.ore
        costo_ore += costo
        voce = per_persona.setdefault(riga.utente_id, {"utente": riga.utente, "ore": Decimal(0), "costo": Decimal(0)})
        voce["ore"] += riga.ore
        voce["costo"] += costo
    fatture = Fattura.objects.filter(su_progetto__progetto=progetto, stato=Fattura.EMESSA)
    fatturato = sum((f.imponibile for f in fatture), Decimal(0))
    fatturato -= sum((n.imponibile for f in fatture for n in f.note_credito.filter(stato=Fattura.EMESSA)), Decimal(0))
    aperte = da_fatturare(progetto)
    in_attesa = sum((v["importo"] for v in aperte), Decimal(0))
    ricavi = fatturato + in_attesa
    esterni = costi_analitica(progetto)
    budget = budget_progetto(progetto)
    margine = ricavi - costo_ore - esterni["acquisti"] - esterni["spese"]
    base = ricavi or Decimal(1)
    condizioni = condizioni_di(progetto)
    if condizioni.tipo == Condizioni.TAPPE:
        tappe = list(condizioni.tappe.select_related("fattura"))
        in_attesa = sum((t.valore for t in tappe if not t.fattura_id or t.fattura.stato == Fattura.ANNULLATA), Decimal(0))
        ricavi = fatturato + in_attesa
        margine = ricavi - costo_ore - esterni["acquisti"] - esterni["spese"]
        base = ricavi or Decimal(1)
    return {"ore": ore_totali, "costo": calcoli.arrotonda(costo_ore), "fatturato": fatturato, "in_attesa": in_attesa,
            "esterni": esterni["acquisti"], "spese": esterni["spese"], "budget": budget,
            "residuo_corpo": residuo_corpo(progetto) if condizioni.tipo == Condizioni.CORPO else None,
            "tappe": list(condizioni.tappe.select_related("fattura")) if condizioni.tipo == Condizioni.TAPPE else [],
            "ricavi": ricavi, "margine": calcoli.arrotonda(margine),
            "percentuale": int(margine * 100 / ricavi) if ricavi else 0,
            "quota_fatturato": int(fatturato * 100 / base), "quota_attesa": int(in_attesa * 100 / base),
            "ore_da_fatturare": sum((v["ore"] for v in aperte), Decimal(0)),
            "persone": sorted(per_persona.values(), key=lambda p: -p["ore"]),
            "condizioni": condizioni_di(progetto), "fatture": fatture.order_by("-data")[:10]}



def _voci_analitiche(progetto):
    from django.apps import apps
    if not apps.is_installed("analitica"):
        return []
    from analitica.models import Voce
    return list(Voce.objects.filter(azienda=progetto.azienda, progetto_id=progetto.pk))


def costi_analitica(progetto):
    """Fatture ricevute e note spese imputate alle voci analitiche collegate al progetto (positivi)."""
    voci = _voci_analitiche(progetto)
    valori = {"acquisti": Decimal(0), "spese": Decimal(0)}
    if not voci:
        return valori
    from analitica.operazioni import movimenti
    for m in movimenti(progetto.azienda, voci):
        if m["fonte"].categoria in valori:
            valori[m["fonte"].categoria] -= m["importo"]
    return valori


def budget_progetto(progetto):
    """Il confronto dei budget delle voci collegate (il più recente), o None."""
    voci = _voci_analitiche(progetto)
    if not voci:
        return None
    from analitica.models import Budget
    from analitica.operazioni import confronto
    b = Budget.objects.filter(voce__in=voci).order_by("-dal").first()
    return {"budget": b, **confronto(b)} if b else None


def portafoglio(azienda, progetti):
    """Per ogni progetto: ricavi, costi (ore, esterni, spese), margine e budget, per la vista d'insieme."""
    righe = []
    for p in progetti:
        r = redditivita(p)
        costi = r["costo"] + r["esterni"] + r["spese"]
        righe.append({"progetto": p, "ricavi": r["ricavi"], "fatturato": r["fatturato"], "costi": costi, "margine": r["margine"],
                      "percentuale": r["percentuale"], "budget": r["budget"], "tipo": r["condizioni"].get_tipo_display()})
    totale = {k: sum((x[k] for x in righe), Decimal(0)) for k in ("ricavi", "fatturato", "costi", "margine")}
    return righe, totale
