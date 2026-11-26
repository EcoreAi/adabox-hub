"""«Le mie previsioni» nella pagina Previsioni: le previsioni che l'utente ha fatto con Ada (chat) o in Analisi, in un
posto solo, con cerca, filtri, rinomina ed etichetta.

Il modulo non dipende da Assistente AI né da Analisi: `ai` e `grafici` si importano solo qui dentro, e ogni fonte c'è
solo se l'app è installata e accesa per l'azienda (`pronte.app_attiva`). Niente chiavi esterne verso di loro
(EtichettaPrevisione tiene origine e id), come PrevisioneArticolo (Ruling 18)."""
from django.apps import apps
from django.urls import reverse

from core.registry import modules

from . import pronte
from .models import EtichettaPrevisione

CHAT, ANALISI = EtichettaPrevisione.CHAT, EtichettaPrevisione.ANALISI
LIMITE = 200
LUNGHEZZA_TITOLO = 200
LUNGHEZZA_ETICHETTA = 60
ALTRO = "Altro"
PERIODI = {"mese": "per mese", "settimana": "per settimana", "giorno": "per giorno"}
NOMI_ORIGINE = {CHAT: "Chat", ANALISI: "Analisi"}
PERMESSO_ANALISI = "grafici.view_grafico"     # come le altre sezioni: senza il permesso niente righe di Analisi
APP_DI = {CHAT: "ai", ANALISI: "grafici"}


def _attiva(origine, request):
    slug = APP_DI[origine]
    return (apps.is_installed(slug) and getattr(request, "azienda", None) is not None
            and pronte.app_attiva(slug, request.azienda, request.user)
            and (origine != ANALISI or request.user.has_perm(PERMESSO_ANALISI)))


def fonti(request):
    return [o for o in (CHAT, ANALISI) if _attiva(o, request)]


def _queryset(origine, request):
    """Le previsioni dell'utente della richiesta. Quelle della chat sono dell'azienda corrente (l'Artifact la porta); i grafici
    di Analisi sono dell'utente e non hanno un'azienda (limite: si vedono in tutte le sue aziende)."""
    if origine == CHAT:
        from ai.models import Artifact
        return Artifact.objects.filter(utente=request.user, azienda=request.azienda, spec__grafico="previsione")
    from grafici.models import Grafico
    return Grafico.objects.filter(utente=request.user, tipo=Grafico.PREVISIONE)


def oggetto(origine, pk, request):
    """La previsione `pk` dell'utente, o None (non sua, non una previsione, fonte spenta, origine sconosciuta)."""
    if origine not in APP_DI or not _attiva(origine, request):
        return None
    return _queryset(origine, request).filter(pk=pk).first()


def argomento(spec):
    """L'app da cui viene la serie, con il nome del suo manifest: il prefisso di `misura_aziendale` o di `vista`."""
    origine = spec.get("misura_aziendale") or spec.get("vista") or ""
    slug = origine.split(".")[0] if "." in origine else ""
    manifest = modules.manifests_attivi().get(slug)
    return manifest.name if manifest else ALTRO


def tipo(spec):
    """(chiave per il filtro, testo): classifica per gruppo oppure andamento nel tempo, e il periodo."""
    periodo = PERIODI.get(spec.get("per"), PERIODI["mese"])
    if spec.get("raggruppa"):
        return "classifica", f"Classifica (primi {spec.get('primi') or 10})", periodo
    return "andamento", "Andamento", periodo


def voce(origine, obj, etichette):
    spec = obj.spec if isinstance(obj.spec, dict) else {}
    chiave_tipo, testo_tipo, periodo = tipo(spec)
    arg = argomento(spec)
    etichetta = etichette.get((origine, obj.pk), "")
    url = reverse("ai:artifact", args=[obj.pk]) if origine == CHAT else reverse("grafici:grafico", args=[obj.pk])
    return {"origine": origine, "origine_nome": NOMI_ORIGINE[origine], "pk": obj.pk, "titolo": obj.titolo, "url": url,
            "argomento": arg, "tipo": chiave_tipo, "tipo_nome": chiave_tipo.capitalize(), "tipo_testo": testo_tipo,
            "periodo": periodo, "creato": obj.creato, "etichetta": etichetta,
            "salvata": "si" if origine == ANALISI or getattr(obj, "salvato", False) else "no",
            "cerca": f"{obj.titolo} {etichetta} {arg}",
            "rinomina_url": reverse("previsioni:rinomina", args=[origine, obj.pk]),
            "etichetta_url": reverse("previsioni:etichetta", args=[origine, obj.pk])}


def _etichette(request):
    return {(e.origine, e.oggetto_pk): e.etichetta for e in EtichettaPrevisione.objects.filter(utente=request.user)}


def _pulisci_etichette(request, attive):
    """Cancella le etichette dell'utente il cui oggetto non esiste più (solo per le fonti attive: con una fonte spenta
    non si può sapere). L'oggetto di un'altra azienda esiste: la sua etichetta resta."""
    etichette = list(EtichettaPrevisione.objects.filter(utente=request.user, origine__in=attive))
    for origine in attive:
        pks = {e.oggetto_pk for e in etichette if e.origine == origine}
        if not pks:
            continue
        if origine == CHAT:
            from ai.models import Artifact as modello
        else:
            from grafici.models import Grafico as modello
        spariti = pks - set(modello.objects.filter(pk__in=pks).values_list("pk", flat=True))
        if spariti:
            EtichettaPrevisione.objects.filter(utente=request.user, origine=origine, oggetto_pk__in=spariti).delete()


def riga(origine, obj, request):
    """Il contesto della riga di un oggetto solo (dopo una rinomina o un'etichetta)."""
    return {"v": voce(origine, obj, _etichette(request))}


def sezione(request):
    """Il contesto della sezione, o None se nessuna fonte è disponibile (la sezione non c'è)."""
    attive = fonti(request)
    if not attive:
        return None
    _pulisci_etichette(request, attive)
    oggetti, totale = [], 0
    for origine in attive:
        qs = _queryset(origine, request).order_by("-creato", "-pk")
        totale += qs.count()
        oggetti += [(origine, o) for o in qs[:LIMITE]]
    oggetti.sort(key=lambda x: (x[1].creato, x[1].pk), reverse=True)
    etichette = _etichette(request)
    voci = [voce(o, obj, etichette) for o, obj in oggetti[:LIMITE]]

    def valori(campo):
        return sorted({v[campo] for v in voci if v[campo]}, key=str.lower)
    return {"voci": voci, "totale": totale, "troncata": totale > len(voci),
            "argomenti": valori("argomento"), "tipi": valori("tipo_nome"), "origini": valori("origine_nome"),
            "etichette": valori("etichetta")}
