"""Approvazioni generiche (PLT-07): una catena blocca un bottone di un documento finché i suoi passi non approvano.

- Il bottone si avvolge alla registrazione della vista (registry._con_approvazioni): vale dalla pagina, dall'API e
  dall'assistente. Premuto la prima volta crea la richiesta e avvisa chi deve decidere; il documento resta com'è.
- Approvata l'ultima fase, chi aveva chiesto preme di nuovo il bottone e passa. Se intanto il valore della condizione
  è salito oltre quello approvato, serve una nuova approvazione.
- Chi decide: chi ha il ruolo del passo o la persona indicata, oppure chi ha una delega attiva da loro; mai chi ha
  chiesto. Ogni decisione resta nello storico; le scadenze dei passi mandano un promemoria."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Max, Q
from django.utils import timezone

from core import chatter
from core.generici import ct_di
from core.models import CatenaApprovazione, Delega, DecisioneApprovazione, RichiestaApprovazione


def _chiave(vista):
    return f"{vista.modulo}.{vista.slug}"


def valore_di(obj, campo):
    """Il valore della condizione: un campo del record, o il massimo su una relazione (righe__sconto)."""
    if not campo:
        return None
    if "__" in campo:
        relazione, _, nome = campo.partition("__")
        gestore = getattr(obj, relazione, None)
        if gestore is None or not hasattr(gestore, "aggregate"):
            return None
        return gestore.aggregate(m=Max(nome))["m"]
    return getattr(obj, campo, None)


def catena_per(vista, nome, obj):
    """La catena attiva più severa (soglia più alta) che vale per questo bottone e questo record, o None."""
    azienda = getattr(obj, "azienda", None)
    catene = CatenaApprovazione.objects.filter(vista=_chiave(vista), bottone=nome, attiva=True).filter(
        Q(azienda__isnull=True) | Q(azienda=azienda)).order_by("-soglia")
    for c in catene:
        if not c.campo:
            return c
        v = valore_di(obj, c.campo)
        if v is not None and Decimal(str(v)) >= c.soglia:
            return c
    return None


def richieste_di(obj):
    return RichiestaApprovazione.objects.filter(content_type=ct_di(obj), object_id=obj.pk)


def passi(catena):
    return list(catena.passi.select_related("ruolo", "utente").order_by("ordine", "pk"))


def chi_decide(passo):
    """Gli utenti del passo (la persona, o chi ha il ruolo) più chi ha una loro delega attiva oggi."""
    Utente = get_user_model()
    titolari = [passo.utente] if passo.utente_id else list(Utente.objects.filter(is_active=True, profilo__ruolo=passo.ruolo))
    oggi = timezone.localdate()
    delegati = Utente.objects.filter(deleghe_ricevute__da__in=titolari, deleghe_ricevute__dal__lte=oggi,
                                     deleghe_ricevute__al__gte=oggi, is_active=True).distinct()
    return titolari, list(delegati)


def puo_decidere(richiesta, utente):
    """(sì/no, per conto di chi) per il passo corrente."""
    if richiesta.stato != RichiestaApprovazione.IN_ATTESA or utente.pk == richiesta.richiesta_da_id:
        return False, None
    lista = passi(richiesta.catena)
    if not 0 < richiesta.passo <= len(lista):
        return False, None
    titolari, _ = chi_decide(lista[richiesta.passo - 1])
    if utente in titolari:
        return True, None
    oggi = timezone.localdate()
    delega = Delega.objects.filter(a=utente, da__in=titolari, dal__lte=oggi, al__gte=oggi).select_related("da").first()
    return (True, delega.da) if delega else (False, None)


def _avvisa(richiesta, testo):
    """Un messaggio nel chatter del record che menziona chi deve decidere: email, o posta di Discuss se c'è."""
    lista = passi(richiesta.catena)
    if not 0 < richiesta.passo <= len(lista) or richiesta.record is None:
        return
    titolari, delegati = chi_decide(lista[richiesta.passo - 1])
    nomi = " ".join(f"@{u.username}" for u in [*titolari, *delegati])
    for u in titolari:
        chatter.segui(richiesta.record, u)
    chatter.scrivi(richiesta.record, None, f"{testo} {nomi}".strip(), tipo="nota")


def _nuova(catena, obj, utente):
    lista = passi(catena)
    r = RichiestaApprovazione.objects.create(
        catena=catena, content_type=ct_di(obj), object_id=obj.pk, descrizione=str(obj)[:200], richiesta_da=utente,
        valore=valore_di(obj, catena.campo), scadenza=timezone.now() + timedelta(days=lista[0].giorni) if lista else None)
    if not lista:                                        # una catena senza passi non blocca nessuno
        r.stato, r.chiusa_il = RichiestaApprovazione.APPROVATA, timezone.now()
        r.save(update_fields=["stato", "chiusa_il"])
        return r
    _avvisa(r, f"Serve l'approvazione «{catena.nome}» per «{obj}»:")
    return r


def controlla(vista, nome, obj, request):
    """None se il bottone può procedere; altrimenti il messaggio da mostrare (richiesta creata o in attesa)."""
    catena = catena_per(vista, nome, obj)
    if catena is None:
        return None
    esistenti = richieste_di(obj).filter(catena=catena).exclude(stato=RichiestaApprovazione.ANNULLATA).order_by("-creata")
    ultima = esistenti.first()
    attuale = valore_di(obj, catena.campo)
    if ultima is not None and ultima.stato == RichiestaApprovazione.APPROVATA:
        if attuale is None or ultima.valore is None or Decimal(str(attuale)) <= ultima.valore:
            return None
        ultima = None                                    # il valore è salito: si richiede da capo
    if ultima is not None and ultima.stato == RichiestaApprovazione.IN_ATTESA:
        return f"«{obj}» aspetta ancora l'approvazione «{catena.nome}» (passo {ultima.passo} di {catena.passi.count()})."
    if ultima is not None and ultima.stato == RichiestaApprovazione.RIFIUTATA and ultima.valore is not None \
            and attuale is not None and Decimal(str(attuale)) >= ultima.valore:
        decisione = ultima.decisioni.filter(approvata=False).last()
        return f"L'approvazione «{catena.nome}» è stata rifiutata" + (f": {decisione.nota}" if decisione and decisione.nota else ".") + \
            " Cambia il documento (es. riduci l'importo o lo sconto) e riprova."
    _nuova(catena, obj, request.user)
    return f"Per questa operazione serve l'approvazione «{catena.nome}»: la richiesta è partita, riprova quando è approvata."


def decidi(richiesta, utente, approvata, nota=""):
    ammesso, per_conto_di = puo_decidere(richiesta, utente)
    if not ammesso:
        raise PermissionError("Non tocca a te decidere su questa richiesta.")
    DecisioneApprovazione.objects.create(richiesta=richiesta, passo=richiesta.passo, utente=utente, per_conto_di=per_conto_di,
                                         approvata=approvata, nota=nota[:250])
    lista = passi(richiesta.catena)
    obj = richiesta.record
    chi = utente.get_full_name() or utente.username
    if not approvata:
        richiesta.stato, richiesta.chiusa_il = RichiestaApprovazione.RIFIUTATA, timezone.now()
        richiesta.save(update_fields=["stato", "chiusa_il"])
        if obj is not None:
            chatter.scrivi(obj, utente, f"Approvazione «{richiesta.catena.nome}» rifiutata da {chi}" + (f": {nota}" if nota else ".")
                           + (f" @{richiesta.richiesta_da.username}" if richiesta.richiesta_da else ""), tipo="nota")
        return richiesta
    if richiesta.passo >= len(lista):
        richiesta.stato, richiesta.chiusa_il = RichiestaApprovazione.APPROVATA, timezone.now()
        richiesta.save(update_fields=["stato", "chiusa_il"])
        if obj is not None:
            chatter.scrivi(obj, utente, f"Approvazione «{richiesta.catena.nome}» concessa da {chi}: si può procedere."
                           + (f" @{richiesta.richiesta_da.username}" if richiesta.richiesta_da else ""), tipo="nota")
        return richiesta
    richiesta.passo += 1
    richiesta.scadenza = timezone.now() + timedelta(days=lista[richiesta.passo - 1].giorni)
    richiesta.save(update_fields=["passo", "scadenza"])
    _avvisa(richiesta, f"{chi} ha approvato il passo {richiesta.passo - 1}; ora tocca a")
    return richiesta


def da_decidere(utente):
    """Le richieste in attesa su cui l'utente può decidere ora (anche per delega)."""
    return [r for r in RichiestaApprovazione.objects.filter(stato=RichiestaApprovazione.IN_ATTESA).select_related("catena", "richiesta_da")
            if puo_decidere(r, utente)[0]]


def promemoria():
    """Lavoro pianificato: per i passi scaduti un nuovo avviso a chi deve decidere (una volta al giorno)."""
    n = 0
    for r in RichiestaApprovazione.objects.filter(stato=RichiestaApprovazione.IN_ATTESA, scadenza__lt=timezone.now()):
        _avvisa(r, f"Promemoria: l'approvazione «{r.catena.nome}» per «{r.descrizione}» è scaduta, manca la decisione di")
        n += 1
    return n


class _ConApprovazione:
    """Il bottone avvolto: prima le catene di approvazione, poi il metodo vero. Gli attributi (short_description,
    permission, rischio, ai…) si leggono sempre dal metodo della classe, anche se cambiano dopo."""

    def __init__(self, vista, nome):
        self._vista, self._nome = vista, nome

    def _metodo(self):
        return getattr(type(self._vista), self._nome)

    def __call__(self, request, obj):
        esito = controlla(self._vista, self._nome, obj, request)
        return esito if esito else self._metodo().__get__(self._vista)(request, obj)

    def __getattr__(self, attributo):
        return getattr(self._metodo(), attributo)


def avvolgi(vista):
    """I bottoni della vista passano dal controllo delle approvazioni (chiamato da registry)."""
    classe = type(vista)
    for nome in vista.buttons:
        if getattr(classe, nome, None) is not None:
            setattr(vista, nome, _ConApprovazione(vista, nome))
