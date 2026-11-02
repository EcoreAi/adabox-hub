"""Il contratto degli agenti deciso in adabox (§8.4 di `docs/plugin-api.md`), a nome della persona che ha confermato.

Alla conferma di «Assumi» la persona riscrive la password; adabox salva il suo **consenso**: chi, quando, squadra e
versione, settimane, tetti e prezzo come li ha visti. Quando la fabbrica propone il contratto (stato `proposed` con
`approval_id` e `proposal`, §8.3), adabox lo confronta con il consenso:

- **combacia** (stessa squadra e versione, stesse settimane, tetti non più alti, prezzo uguale): adabox approva da
  solo in Agate con la chiave `decide`, a nome di quella persona («Confermato in adabox il 01/11 alle 10:02»);
- **non combacia** (o manca il consenso, per esempio una richiesta fatta dalla chat): la pagina della richiesta dice
  cosa è cambiato e chiede di nuovo a lei, con la password;
- Agate può rispondere che serve la **doppia conferma** dei responsabili (202): si aspetta la loro email.

Senza il collegamento ad Agate con un codice (niente chiave `decide`) resta il percorso di prima: il contratto si
conferma nella pagina di Agate. Agate resta il garante: regole, tetti e scadenze sono suoi."""
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import RichiestaAgenti

log = logging.getLogger("awf.contratto")

R = RichiestaAgenti
TETTI = {"llm_eur_max": ("Spesa massima per l'AI", "€"), "spend_eur_max": ("Spesa massima degli agenti", "€"),
         "tasks_max": ("Compiti al massimo", "")}
PREZZO = {"pricing": "Tipo di prezzo", "period_eur": "Canone", "period_days": "Giorni del periodo",
          "task_eur": "Prezzo a compito", "llm_markup": "Ricarico sul credito dei modelli AI",
          "prepaid_credit_eur": "Credito iniziale dei modelli AI (€ al costo del provider)"}


def garante():
    """Il modulo `agate.applicazione` se adabox è collegato ad Agate con un codice (può decidere), altrimenti None."""
    from core.registry.modules import disattivati
    if "agate" not in settings.ADDONS_ATTIVI or "agate" in disattivati():
        return None
    try:
        from agate import applicazione
        return applicazione if applicazione.semplice() else None
    except Exception:                                   # modulo non migrato o rotto: si decide in Agate
        log.warning("collegamento ad Agate non leggibile", exc_info=True)
        return None


def sincronizza():
    """Dopo un cambio di «cosa può fare»: Agate rilegge gli strumenti di adabox (§8.1, chiave `sync`), appena le
    operazioni ammesse sono salvate. Non blocca mai: se non riesce si riprova da sola ogni minuto."""
    from core.registry.modules import disattivati
    if "agate" not in settings.ADDONS_ATTIVI or "agate" in disattivati():
        return
    try:
        from agate import applicazione
    except Exception:
        log.warning("modulo agate non leggibile: niente risincronizzazione", exc_info=True)
        return
    applicazione.sincronizza_dopo_il_commit()


# ---------- il consenso ----------

def _numero(valore):
    if valore in (None, "") or isinstance(valore, bool):
        return None
    try:
        d = Decimal(str(valore))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


def _semplice(valori):
    """Solo chiavi testuali e valori semplici (testo, numero, null): quello che si confronta."""
    if not isinstance(valori, dict):
        return {}
    return {k: v for k, v in valori.items() if isinstance(k, str)
            and (v is None or (isinstance(v, (str, int, float)) and not isinstance(v, bool)))}


def consenso(utente, team, versione, settimane, tetti, prezzo, giorni_prova=0, quando=None):
    """Quello che la persona ha confermato con la password: chi, quando, squadra, versione, settimane, tetti, prezzo."""
    quando = quando or timezone.now()
    return {"utente": utente.pk, "nome": " ".join((utente.get_full_name() or utente.get_username()).split()),
            "email": utente.email or "", "il": quando.isoformat(), "team": team, "versione": int(versione),
            "settimane": int(settimane), "tetti": _semplice(tetti), "prezzo": _semplice(prezzo),
            "giorni_prova": int(giorni_prova or 0)}


def dalla_proposta(utente, proposta, quando=None):
    """Il consenso dato a un contratto proposto (quando la persona lo conferma di nuovo, con la password)."""
    return consenso(utente, proposta.get("team", ""), _intero(proposta.get("team_version")) or 0,
                    _intero(proposta.get("weeks")) or 0, proposta.get("caps"), proposta.get("price"),
                    _intero(proposta.get("observe_days")) or 0, quando)


def _intero(valore):
    n = _numero(valore)
    return int(n) if n is not None and n == n.to_integral_value() else None


def quando(c):
    try:
        d = parse_datetime(c.get("il") or "") if isinstance(c, dict) else None
    except ValueError:
        d = None
    return d


# ---------- il confronto ----------

def _euro(d):
    return f"{d:.0f}" if d == d.to_integral_value() else f"{d:.2f}".replace(".", ",")


def _tetto(chiave, valore):
    nome, unita = TETTI.get(chiave, (chiave, ""))
    if valore is None:
        return "nessun limite"
    return f"{_euro(valore)} {unita}".strip()


def _prezzo_uguale(a, b):
    na, nb = _numero(a), _numero(b)
    if na is not None or nb is not None:
        return (na or Decimal(0)) == (nb or Decimal(0))
    return (a or "") == (b or "")


def differenze(c, proposta):
    """Cosa cambia tra quello che la persona ha confermato (`c`) e il contratto proposto: frasi per le persone.
    Vuota se combacia."""
    if not isinstance(proposta, dict) or not proposta:
        return ["Il contratto proposto non è leggibile."]
    if not c:
        return ["Non hai ancora confermato questo contratto con la tua password."]
    righe = []
    if proposta.get("team") != c.get("team"):
        righe.append("È un agente diverso da quello che hai scelto.")
    elif _intero(proposta.get("team_version")) != c.get("versione"):
        righe.append(f"L'agente è stato aggiornato da Agentlia (versione {c.get('versione')} → "
                     f"{proposta.get('team_version')}).")
    settimane = _intero(proposta.get("weeks"))
    if settimane != c.get("settimane"):
        righe.append(f"Durata: hai confermato {c.get('settimane')} settimane, il contratto ne propone {settimane}.")
    confermati, proposti = c.get("tetti") or {}, _semplice(proposta.get("caps"))
    for chiave in sorted(set(confermati) | set(proposti)):
        prima, dopo = _numero(confermati.get(chiave)), _numero(proposti.get(chiave))
        if prima is not None and (dopo is None or dopo > prima):
            righe.append(f"{TETTI.get(chiave, (chiave,))[0]}: da {_tetto(chiave, prima)} a {_tetto(chiave, dopo)}.")
    visti, proposto = c.get("prezzo") or {}, _semplice(proposta.get("price"))
    for chiave in sorted(set(visti) | set(proposto)):
        if not _prezzo_uguale(visti.get(chiave), proposto.get(chiave)):
            nome = PREZZO.get(chiave, chiave)
            righe.append(f"{nome}: da {visti.get(chiave) if visti.get(chiave) not in (None, '') else '—'} a "
                         f"{proposto.get(chiave) if proposto.get(chiave) not in (None, '') else '—'}.")
    return righe


def tetti_in_parole(tetti, prezzo=None):
    """{"llm_eur_max": 60} → ["Spesa massima per l'AI: 60 €"] (solo i tetti impostati). Con il listino (`prezzo`) il
    tetto dei modelli dice anche quanto vale per l'azienda: è al costo del provider (B9, `squadre.tetto_ai`)."""
    from . import squadre

    def parole(k, n):
        if k == "llm_eur_max" and prezzo is not None:
            return squadre.tetto_ai(prezzo, n)
        return _tetto(k, n)
    return [f"{TETTI.get(k, (k,))[0]}: {parole(k, _numero(v))}" for k, v in sorted((tetti or {}).items())
            if _numero(v) is not None]


# ---------- le decisioni ----------

def _salva(r, decisione, messaggio=""):
    r.decisione, r.decisione_il, r.decisione_msg = decisione, timezone.now(), messaggio[:300]
    r.save(update_fields=["decisione", "decisione_il", "decisione_msg", "aggiornata"])
    return r


def _decidi(r, g, utente, decisione, motivo):
    from agate import cliente
    try:
        esito = g.decidi(r.approval_id, decisione, utente, motivo)
    except cliente.ErroreAgate as e:
        if e.stato == 409:                              # già decisa (anche dalla console): lo dirà la fabbrica
            return _salva(r, R.APPROVATA if decisione == "approved" else R.RIFIUTATA_QUI, "già decisa")
        log.warning("contratto %s: decisione non arrivata ad Agate: %s", r.request_id, e)
        return _salva(r, R.ERRORE, str(e))
    except g.ErroreCollegamento as e:
        return _salva(r, R.ERRORE, str(e))
    if decisione != "approved":
        return _salva(r, R.RIFIUTATA_QUI, motivo)
    return _salva(r, R.IN_CONFERMA if esito == g.IN_CONFERMA else R.APPROVATA, motivo)


def automatico(r):
    """Dopo ogni lettura dello stato: se il contratto proposto combacia con il consenso, adabox lo approva a nome della
    persona che ha confermato; se no lo segna da confermare. Un errore si riprova alla lettura seguente."""
    if r.stato != R.DA_APPROVARE or not r.approval_id or r.decisione not in ("", R.ERRORE):
        return r
    g = garante()
    if g is None:
        return r                                         # si conferma in Agate, come prima
    if differenze(r.consenso, r.proposta):
        return _salva(r, R.DA_CONFERMARE)
    utente = get_user_model().objects.filter(pk=r.consenso.get("utente"), is_active=True).first()
    if utente is None:
        return _salva(r, R.DA_CONFERMARE, "chi aveva confermato non è più attivo")
    return _decidi(r, g, utente, "approved", g.motivo(quando(r.consenso)))


def conferma(r, utente):
    """La persona conferma di nuovo il contratto proposto (con la password, controllata da chi chiama): il consenso
    diventa quello del contratto proposto e adabox approva a suo nome."""
    g = garante()
    if g is None or r.stato != R.DA_APPROVARE or not r.approval_id:
        raise ValueError("questo contratto non si può confermare da qui")
    adesso = timezone.now()
    r.consenso = dalla_proposta(utente, r.proposta, adesso)
    r.save(update_fields=["consenso", "aggiornata"])
    return _decidi(r, g, utente, "approved", g.motivo(adesso))


def rifiuta(r, utente, motivo=""):
    g = garante()
    if g is None or r.stato != R.DA_APPROVARE or not r.approval_id:
        raise ValueError("questo contratto non si può rifiutare da qui")
    return _decidi(r, g, utente, "rejected", motivo.strip()[:1000] or g.motivo(azione="Rifiutato"))


def da_confermare():
    """Le richieste il cui contratto aspetta di nuovo la persona (per «Da approvare»)."""
    return R.objects.filter(stato=R.DA_APPROVARE, decisione=R.DA_CONFERMARE).exclude(approval_id="")
