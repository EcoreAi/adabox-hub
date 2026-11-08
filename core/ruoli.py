"""Ruoli: che cosa può fare una persona in ogni modulo, tradotto nei gruppi Django dei moduli.

Un ruolo ha un livello di partenza (nessuno, lettura, lavoro, responsabile) e può cambiarlo modulo per modulo; una
persona ha un ruolo e, se serve, le sue eccezioni. Un ruolo «tecnico» rende superutente (Global Admin), uno che
«amministra» dà dal front utenti, ruoli, applicazioni e impostazioni (Admin). Da questi si ricavano i gruppi: «lavoro» sono i gruppi di base del
modulo (Utente, Operatore, Venditore…), «responsabile» tutti i suoi gruppi, «lettura» un gruppo con i soli permessi di
vista che il kernel crea per lui. Chi non ha un ruolo resta com'era: i suoi gruppi non si toccano.
I dipartimenti restringono: in un'app fuori dai dipartimenti della persona il livello diventa «nessuno», salvo
un'eccezione per lei (vedi core.dipartimenti)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db.models import Q

from . import dipartimenti
from .models import Ruolo
from .registry import groups, modules

NESSUNO, LETTURA, LAVORO, RESPONSABILE = "nessuno", "lettura", "lavoro", "responsabile"
LIVELLI = Ruolo.LIVELLI
ETICHETTE = dict(LIVELLI)
ALTI = ("/ Responsabile", "/ Amministratore")
PIATTAFORMA = "Piattaforma / Amministratore"
PERMESSI_PIATTAFORMA = ["core.*", "auth.view_user", "auth.add_user", "auth.change_user", "auth.view_group"]


def _permessi(codici):
    if not codici:
        return Permission.objects.none()
    filtro = Q(*[Q(content_type__app_label=a, codename=c) for a, c in (p.split(".", 1) for p in codici)], _connector=Q.OR)
    return Permission.objects.filter(filtro)


def nome_lettura(manifest):
    proprio = [n for n in manifest.groups if n.endswith("/ Lettura")]
    return proprio[0] if proprio else f"{manifest.name} / Lettura"


def gruppi_del_kernel(manifest):
    """Il gruppo «Lettura» del modulo, se non lo dichiara lui: i permessi di vista dei suoi modelli e quelli di vista che
    i suoi gruppi danno su altre app. [nome del gruppo] o [] se non c'è niente da vedere."""
    if any(n.endswith("/ Lettura") for n in manifest.groups):
        return []
    codici = {f"{p.content_type.app_label}.{p.codename}"
              for p in Permission.objects.filter(content_type__app_label=manifest.slug, codename__startswith="view_").select_related("content_type")}
    for perms in manifest.groups.values():
        for perm in perms:
            codici |= {c for c in groups.espandi(perm) if c.split(".", 1)[1].startswith("view_")}
    if not codici:
        return []
    gruppo, _ = Group.objects.get_or_create(name=nome_lettura(manifest))
    gruppo.permissions.set(_permessi(codici))
    return [gruppo.name]


def gruppo_piattaforma():
    gruppo, _ = Group.objects.get_or_create(name=PIATTAFORMA)
    gruppo.permissions.set(_permessi({c for perm in PERMESSI_PIATTAFORMA for c in groups.espandi(perm)}))
    return gruppo


def gruppi_per_livello(manifest, livello):
    nomi = list(manifest.groups)
    if livello == RESPONSABILE:
        return set(nomi)
    if livello == LAVORO:
        return {n for n in nomi if not n.endswith(ALTI)} or set(nomi)
    if livello == LETTURA:
        nome = nome_lettura(manifest)
        if not Group.objects.filter(name=nome).exists() and not gruppi_del_kernel(manifest):
            return set()
        return {nome}
    return set()


def livello_di(profilo, slug):
    """Il livello effettivo in un modulo: l'eccezione della persona, poi quella del ruolo, poi la base del ruolo. None senza ruolo."""
    if slug in profilo.eccezioni:
        return profilo.eccezioni[slug]
    if profilo.ruolo_id is None:
        return None
    return profilo.ruolo.livelli.get(slug, profilo.ruolo.livello_base)


def livello_effettivo(profilo, slug, consentite=dipartimenti.NESSUN_LIMITE):
    """(livello, fuori): il livello con i dipartimenti, e vero se è «nessuno» solo perché l'app è fuori dai suoi
    dipartimenti. `consentite` le app dei suoi dipartimenti (dipartimenti.del_profilo). None senza ruolo."""
    livello = livello_di(profilo, slug)
    if livello is None or livello == NESSUNO or dipartimenti.dentro(slug, consentite, profilo.eccezioni):
        return livello, False
    return NESSUNO, True


def livello_dai_gruppi(nomi, manifest):
    """Per chi non ha un ruolo: il livello che i suoi gruppi fanno pensare (serve alla matrice)."""
    tutti = set(manifest.groups)
    alti = {n for n in tutti if n.endswith(ALTI)}
    if nomi & alti or (tutti and tutti <= nomi):
        return RESPONSABILE
    if nomi & ((tutti - alti) or tutti):
        return LAVORO
    if nome_lettura(manifest) in nomi:
        return LETTURA
    return NESSUNO


def moduli_gestibili(anche_spenti=False):
    """[(slug, manifest)] dei moduli installati che hanno dei gruppi: quelli su cui un ruolo decide."""
    spenti = set() if anche_spenti else modules.disattivati()
    return [(slug, m) for slug, m in modules.manifests_attivi().items() if m.groups and slug not in spenti]


def applica(utente):
    """Riallinea i gruppi dell'utente al suo ruolo e alle sue eccezioni; i gruppi che non c'entrano restano. Vero se ha cambiato qualcosa."""
    from .signals import crea_profilo
    profilo = crea_profilo(utente)
    if profilo.ruolo_id is None and not profilo.eccezioni:
        return False
    gestiti, voluti = set(), set()
    consentite = dipartimenti.del_profilo(profilo)
    for slug, m in moduli_gestibili(anche_spenti=True):
        livello, _ = livello_effettivo(profilo, slug, consentite)
        if livello is None:
            continue                                 # senza ruolo si toccano solo i moduli con un'eccezione
        gestiti |= set(m.groups) | {nome_lettura(m)}
        voluti |= gruppi_per_livello(m, livello)
    tecnico = bool(profilo.ruolo_id and profilo.ruolo.tecnico)
    amministra = tecnico or bool(profilo.ruolo_id and profilo.ruolo.amministra)
    if profilo.ruolo_id:
        gestiti.add(PIATTAFORMA)
    if amministra:
        gruppo_piattaforma()
        voluti.add(PIATTAFORMA)
    attuali = set(utente.groups.values_list("name", flat=True))
    nuovi = (attuali - gestiti) | voluti
    cambiato = nuovi != attuali
    if cambiato:
        utente.groups.set(Group.objects.filter(name__in=nuovi))
    if profilo.ruolo_id:                                 # con un ruolo, superutente e staff li decide il ruolo
        campi = []
        if utente.is_superuser != tecnico:
            utente.is_superuser, campi = tecnico, [*campi, "is_superuser"]
        if utente.is_staff != tecnico:                   # l'admin di Django è solo del ruolo tecnico: Admin lavora dal front
            utente.is_staff, campi = tecnico, [*campi, "is_staff"]
        if campi:
            utente.save(update_fields=campi)
            cambiato = True
    return cambiato


def applica_a_tutti():
    """Dopo l'installazione o l'aggiornamento di un modulo: i gruppi nuovi vanno a chi ha un ruolo. Quanti utenti sono cambiati."""
    return sum(applica(u) for u in get_user_model().objects.filter(is_active=True).select_related("profilo", "profilo__ruolo"))


def applica_al_ruolo(ruolo):
    return sum(applica(u) for u in get_user_model().objects.filter(profilo__ruolo=ruolo).select_related("profilo", "profilo__ruolo"))


def predefinito():
    return Ruolo.objects.filter(predefinito=True).first()
