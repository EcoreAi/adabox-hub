"""Dipartimenti: in quali app lavora una persona. Il ruolo dice quanto può fare, il dipartimento dove.

Regole:
- chi non è in nessun dipartimento (e il superutente) vede tutte le app che il ruolo consente;
- chi è in uno o più dipartimenti vede le loro app, le app comuni e quelle da cui queste dipendono (Vendite porta con sé
  Contatti e Prodotti, altrimenti non funzionerebbe);
- un dipartimento con «tutte le app» toglie ogni limite a chi ne fa parte;
- un'eccezione per persona su un'app la apre anche fuori dai suoi dipartimenti;
- i moduli di servizio (senza app propria) non si filtrano: servono alle app.

Il limite vale in due punti: ruoli.applica toglie i gruppi delle app fuori dai dipartimenti (così permessi, API e Ada
seguono), e il menu e il middleware nascondono e chiudono le app, anche quelle senza permessi propri.

Le suite: un pacchetto di app per dipartimento comprato dal portale. La licenza le elenca; ogni suite fa nascere un
dipartimento che la segue (allinea_alle_suite) e può avere un tetto di persone (posti_suite)."""
from django.conf import settings
from django.db import DatabaseError

NESSUN_LIMITE = None


def _manifests():
    from .registry import modules
    return modules.manifests_attivi()


def applicazioni():
    """{slug: manifest} delle app attive (application=True): quelle che un dipartimento può elencare."""
    return {s: m for s, m in _manifests().items() if m.application}


def con_dipendenze(slugs):
    """Gli slug con tutte le loro dipendenze, a cascata."""
    manifests = _manifests()
    visti, da_vedere = set(), list(slugs)
    while da_vedere:
        s = da_vedere.pop()
        if s in visti:
            continue
        visti.add(s)
        m = manifests.get(s)
        if m is not None:
            da_vedere.extend(d for d in m.depends if d not in visti)
    return visti


def comuni():
    from .models import Modulo
    try:
        return frozenset(Modulo.objects.filter(comune=True).values_list("slug", flat=True))
    except DatabaseError:
        return frozenset()


def comuni_predefinite():
    """Le app che nascono comuni quando arrivano: con una licenza a suite quelle del piano base, altrimenti l'impostazione."""
    from . import licenza
    stato = licenza.attuale()
    if stato.valida and stato.suite:
        return set(stato.comuni)
    return set(settings.DIPARTIMENTI_APP_COMUNI)


def calcola(dipartimenti, comuni_=None):
    """Le app consentite da un elenco di dipartimenti [(app, tutte)], o NESSUN_LIMITE."""
    dipartimenti = list(dipartimenti)
    if not dipartimenti or any(tutte for _, tutte in dipartimenti):
        return NESSUN_LIMITE
    elenco = set(comuni() if comuni_ is None else comuni_)
    for app, _ in dipartimenti:
        elenco |= set(app or [])
    return frozenset(con_dipendenze(elenco))


def del_profilo(profilo):
    """Le app consentite dai dipartimenti del profilo, o NESSUN_LIMITE."""
    if profilo is None or profilo.pk is None:
        return NESSUN_LIMITE
    return calcola(profilo.dipartimenti.values_list("app", "tutte"))


def consentite(utente):
    """Le app consentite all'utente dai suoi dipartimenti, o NESSUN_LIMITE. Ricordate sull'oggetto per la richiesta."""
    if not getattr(utente, "is_authenticated", False) or utente.is_superuser:
        return NESSUN_LIMITE
    if hasattr(utente, "_app_dipartimenti"):
        return utente._app_dipartimenti
    try:
        profilo = utente.profilo
    except Exception:                                     # senza profilo: nessun limite
        profilo = None
    try:
        valore = del_profilo(profilo)
    except DatabaseError:
        valore = NESSUN_LIMITE
    utente._app_dipartimenti = valore
    return valore


def dentro(slug, elenco, eccezioni=None):
    """Vero se l'app `slug` è ammessa da `elenco` (le consentite) o da un'eccezione; i moduli di servizio sempre."""
    if elenco is NESSUN_LIMITE or slug in elenco or slug in (eccezioni or {}):
        return True
    m = _manifests().get(slug)
    return m is None or not m.application


def ammessa(utente, slug):
    """L'utente può entrare nell'app `slug` secondo i suoi dipartimenti (le eccezioni per persona valgono)."""
    elenco = consentite(utente)
    if elenco is NESSUN_LIMITE:
        return True
    eccezioni = getattr(getattr(utente, "profilo", None), "eccezioni", None) or {}
    aperte = {s for s, livello in eccezioni.items() if livello != "nessuno"}
    return dentro(slug, elenco, aperte)


def dimentica(utente):
    if hasattr(utente, "_app_dipartimenti"):
        del utente._app_dipartimenti


def riapplica(utenti_ids):
    """I gruppi seguono i dipartimenti: ruoli.applica per ognuno degli utenti indicati."""
    from django.contrib.auth import get_user_model

    from . import ruoli
    return sum(ruoli.applica(u) for u in get_user_model().objects.filter(pk__in=set(utenti_ids)).select_related("profilo", "profilo__ruolo"))


def riapplica_tutti():
    """Dopo un cambio delle app comuni: tocca solo chi è in qualche dipartimento."""
    from django.contrib.auth import get_user_model
    return riapplica(get_user_model().objects.filter(profilo__dipartimenti__isnull=False).values_list("pk", flat=True))


# ---------- suite comprate dal portale

def allinea_alle_suite(stato):
    """Ogni suite della licenza ha il suo dipartimento: nasce con le app della suite (o si aggancia a uno con lo stesso
    nome) e poi le segue: un'app che entra nella suite entra nel dipartimento, una che esce ne esce. Le app aggiunte o
    tolte a mano dall'Admin restano come le ha lasciate. Restituisce i dipartimenti creati o cambiati."""
    from .models import Dipartimento
    if not stato.valida:
        return []
    cambiati = []
    for s in stato.suite:
        app = sorted(s["moduli"])
        d = Dipartimento.objects.filter(suite=s["slug"]).first() or Dipartimento.objects.filter(nome=s["nome"], suite="").first()
        if d is None:
            d = Dipartimento.objects.create(nome=_nome_libero(s["nome"]), suite=s["slug"], app=app, app_suite=app,
                                            descrizione=f"Dalla suite {s['nome']}")
            cambiati.append(d)
            continue
        prima = set(d.app_suite) if d.suite else set()
        nuove, tolte = set(app) - prima, prima - set(app)
        attuali = set(d.app)
        risultato = sorted((attuali | nuove) - tolte)
        if risultato != sorted(attuali) or d.suite != s["slug"] or d.app_suite != app:
            d.app, d.suite, d.app_suite = risultato, s["slug"], app
            d.save()
            cambiati.append(d)
    return cambiati


def _nome_libero(nome):
    from .models import Dipartimento
    candidato, i = nome[:80], 1
    while Dipartimento.objects.filter(nome=candidato).exists():
        i += 1
        candidato = f"{nome[:76]} {i}"
    return candidato


def _interni():
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(is_active=True, is_superuser=False).exclude(profilo__esterno=True)


def _mappa(dip_modificato=None, membri_modificati=None, utente_modificato=None):
    """({utente_id: [(app, tutte)]}, comuni) come sarebbero con le modifiche indicate, senza salvarle:
    dip_modificato = (pk o None, app, tutte), membri_modificati = set di utenti del dipartimento modificato,
    utente_modificato = (pk o None, [pk dei dipartimenti], attivo)."""
    from .models import Dipartimento
    dipartimenti = {d.pk: (d.app, d.tutte) for d in Dipartimento.objects.all()}
    NUOVO = "nuovo"
    if dip_modificato is not None:
        pk, app, tutte = dip_modificato
        dipartimenti[pk or NUOVO] = (app, tutte)
    per_utente = {u: [] for u in _interni().values_list("pk", flat=True)}
    for uid, did in Dipartimento.profili.through.objects.values_list("profiloutente__utente_id", "dipartimento_id"):
        if uid in per_utente:
            per_utente[uid].append(did)
    if dip_modificato is not None and membri_modificati is not None:
        chiave = dip_modificato[0] or NUOVO
        for uid in per_utente:
            per_utente[uid] = [d for d in per_utente[uid] if d != chiave] + ([chiave] if uid in membri_modificati else [])
    if utente_modificato is not None:
        pk, dip, attivo = utente_modificato
        chiave = pk or NUOVO
        if attivo:
            per_utente[chiave] = list(dip)
        else:
            per_utente.pop(chiave, None)
    return {uid: [dipartimenti[d] for d in dip if d in dipartimenti] for uid, dip in per_utente.items()}


def posti_suite(**modifiche):
    """[{slug, nome, utenti, occupati, persone}] delle suite della licenza con un tetto di persone. Occupa un posto chi
    vede almeno un'app propria della suite (non comune): anche chi non ha dipartimenti, perché vede tutto. Con le
    modifiche (vedi _mappa) conta come sarebbe dopo."""
    from . import licenza
    stato = licenza.attuale()
    con_tetto = [s for s in stato.suite if s.get("utenti")] if stato.valida else []
    if not con_tetto:
        return []
    c = comuni()
    mappa = _mappa(**modifiche)
    consentite_ = {uid: calcola(dip, c) for uid, dip in mappa.items()}
    righe = []
    for s in con_tetto:
        proprie = set(s["moduli"]) - c
        persone = {uid for uid, el in consentite_.items() if el is NESSUN_LIMITE or el & proprie} if proprie else set()
        righe.append({"slug": s["slug"], "nome": s["nome"], "utenti": s["utenti"], "occupati": len(persone), "persone": persone})
    return righe


def oltre_il_tetto(**modifiche):
    """Le frasi d'errore per le suite che con le modifiche supererebbero i posti, ma solo dove si peggiora."""
    prima = {r["slug"]: r for r in posti_suite()}
    errori = []
    for r in posti_suite(**modifiche):
        if r["occupati"] > r["utenti"] and r["occupati"] > prima.get(r["slug"], {}).get("occupati", 0):
            errori.append(f"La suite {r['nome']} copre {r['utenti']} person{'a' if r['utenti'] == 1 else 'e'} e sarebbero "
                          f"{r['occupati']}: chiedi altri posti, oppure togli a qualcuno i dipartimenti con le sue app.")
    return errori


def avviso_posti():
    """Il testo per gli amministratori se una suite ha più persone dei posti comprati (es. dopo una riduzione)."""
    oltre = [r for r in posti_suite() if r["occupati"] > r["utenti"]]
    return " ".join(f"La suite {r['nome']} ha {r['occupati']} persone su {r['utenti']} posti." for r in oltre)
