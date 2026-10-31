"""L'elenco chiuso delle operazioni: quali strumenti dell'assistente AI arrivano agli agenti, su quali viste.

Un amministratore abilita coppie (strumento, vista facoltativa) in «Operazioni ammesse»; di default solo letture.
Da qui nascono:

- gli strumenti MCP di `tools/list`: uno per strumento ammesso, con lo schema dello strumento e, se le voci
  indicano delle viste, l'argomento `vista` ristretto a quelle (`enum`). Le annotazioni dicono ad Agate l'effetto:
  `readOnlyHint` per le letture, `destructiveHint` per le irreversibili (esplicito `false` per le scritture: per
  lo spec MCP un'annotazione assente vale distruttiva). Un bottone o un'azione con `rischio = "irreversibile"` in
  una vista ammessa rende irreversibile tutto `esegui_bottone` / `esegui_azione`;
- le operazioni dichiarate alla fabbrica al collegamento (§4 del contratto), nello stesso formato;
- i permessi del gruppo «AWF / Agenti», l'unica fonte dei permessi degli agenti: per ogni voce con una vista,
  quelli che servono allo strumento su quel modello (vedere; aggiungere, modificare, eliminare; i permessi dei
  bottoni e delle azioni). Le voci senza vista non danno permessi: valgono sulle viste già concesse da altre voci.
"""
import copy
import hashlib
import json
import re
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.models import Permission
from django.db.models import Q

from .models import OperazioneAmmessa

NOME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# strumenti che non hanno senso per un agente esterno: parlano con altri modelli o servizi (il plugin non chiama
# modelli), vivono in una conversazione della chat, o gestiscono l'assistente stesso
ESCLUSI = {"chiedi_esperto", "elenco_esperti", "classifica", "previsione", "crea_pianificata", "elenco_pianificate",
           "grafico", "tabella"}
# moduli le cui viste non arrivano mai agli agenti
MODULI_ESCLUSI = {"ai", "awf"}
PREDEFINITE = ["elenco_viste", "descrivi_vista", "cerca_record", "leggi_record", "aggrega_record", "data_e_ora"]
EFFETTO = {"lettura": "read", "scrittura": "write", "irreversibile": "irreversible"}
LIVELLO = {"read": "low", "write": "medium", "irreversible": "high"}
PERMESSO = {"crea_record": "add", "modifica_record": "change", "elimina_record": "delete",
            "pianifica_attivita": "change"}
METODI = {"esegui_bottone": "buttons", "esegui_azione": "actions"}
CODA_CHAT = " Non esegue nulla: prepara una proposta"


class _Tutti:
    """Un «utente» con tutti i permessi: per chiedere al registro dell'assistente tutti gli strumenti."""
    def has_perm(self, perm, obj=None):
        return True


def esponibili():
    """{nome: Strumento} degli strumenti che si possono ammettere (moduli attivi, servizi configurati)."""
    from ai.strumenti import disponibili
    return {s.nome: s for s in disponibili(_Tutti()) if s.nome not in ESCLUSI and NOME_RE.match(s.nome)}


def ha_vista(strumento):
    return "vista" in (strumento.schema.get("properties") or {})


def viste():
    """{id: ModelView} delle viste che un agente può avere (tutte, tranne quelle dell'assistente e di AWF)."""
    from core.registry.modules import disattivati
    from core.viste import registry
    moduli = ["core", *settings.ADDONS_ATTIVI]
    registry.autodiscover(moduli)
    spenti = disattivati()
    return {f"{v.modulo}.{v.slug}": v for m in moduli if m not in MODULI_ESCLUSI and m not in spenti
            for v in registry.viste_di(m)}


@dataclass
class Esposta:
    """Uno strumento ammesso, come lo vedono Agate e gli agenti."""
    nome: str
    strumento: object
    viste: list | None                                  # None = tutte le viste; lista = solo queste

    @property
    def effetto(self):
        base = EFFETTO.get(self.strumento.rischio, "irreversible")
        if base == "write" and self.nome in METODI and _metodi_irreversibili(self.nome, self.viste):
            return "irreversible"
        return base

    def ammette(self, vista):
        return self.viste is None or vista in self.viste

    def descrizione(self):
        testo = self.strumento.descrizione.split(CODA_CHAT)[0].strip()
        return {"read": testo, "write": f"{testo} Scrive nel gestionale.",
                "irreversible": f"{testo} Operazione irreversibile."}[self.effetto]

    def schema(self):
        schema = copy.deepcopy(self.strumento.schema) or {"type": "object", "properties": {}}
        if self.viste is not None and ha_vista(self.strumento):
            schema["properties"]["vista"] = {**schema["properties"]["vista"], "enum": list(self.viste)}
        return schema

    def strumento_mcp(self):
        """La voce di `tools/list`."""
        return {"name": self.nome, "title": self.nome, "description": self.descrizione(),
                "inputSchema": self.schema(),
                "annotations": {"readOnlyHint": self.effetto == "read",
                                "destructiveHint": self.effetto == "irreversible",
                                "idempotentHint": self.effetto == "read", "openWorldHint": False}}

    def dichiarazione(self):
        """La voce di `operations` per la fabbrica (§4 del contratto). I record letti possono contenere testi
        arrivati da fuori (email, ticket, documenti): le letture si dichiarano con contenuto esterno."""
        return {"name": self.nome, "description": self.descrizione(), "effect": self.effetto,
                "risk": LIVELLO[self.effetto], "external_content": self.effetto == "read",
                "params_schema": self.schema()}


def _metodi_irreversibili(nome, ammesse):
    attributo = METODI[nome]
    for vid, v in viste().items():
        if ammesse is not None and vid not in ammesse:
            continue
        for metodo in getattr(v, attributo, ()):
            if getattr(getattr(v, metodo, None), "rischio", "scrittura") == "irreversibile":
                return True
    return False


def esposte():
    """Gli strumenti ammessi ora, in ordine di nome. Le voci con una vista inesistente non contano; le voci con
    una vista per uno strumento che non ha l'argomento vista nemmeno."""
    strumenti = esponibili()
    tutte = viste()
    per_nome = {}
    for voce in OperazioneAmmessa.objects.filter(attiva=True):
        s = strumenti.get(voce.strumento)
        if s is None:
            continue
        if voce.vista:
            if not ha_vista(s) or voce.vista not in tutte:
                continue
            attuale = per_nome.setdefault(voce.strumento, set())
            if attuale is not None:
                attuale.add(voce.vista)
        else:
            per_nome[voce.strumento] = None
    return [Esposta(nome, strumenti[nome], None if v is None else sorted(v)) for nome, v in sorted(per_nome.items())]


def per_nome(nome):
    return next((e for e in esposte() if e.nome == nome), None)


def impronta():
    """Impronta di ciò che Agate approva (nomi, descrizioni, schemi, effetti): cambia se cambia l'elenco."""
    dati = json.dumps([e.strumento_mcp() for e in esposte()], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(dati.encode()).hexdigest()


def versione():
    """Versione dichiarata alla fabbrica: quella del modulo più l'impronta delle operazioni, così un elenco
    cambiato si vede al battito (in Agate uno schema cambiato va in quarantena finché qualcuno non lo rivede)."""
    from core.registry.modules import manifests_attivi
    manifest = manifests_attivi().get("awf")
    base = manifest.version if manifest else "1.0.0"
    return f"{base}+{impronta()[:8]}"[:30]


def semina_predefinite():
    """Al primo avvio: le sole letture predefinite, su tutte le viste (che gli agenti vedono solo se concesse)."""
    if OperazioneAmmessa.objects.exists():
        return 0
    presenti = esponibili()
    nuove = [OperazioneAmmessa(strumento=n) for n in PREDEFINITE if n in presenti]
    OperazioneAmmessa.objects.bulk_create(nuove)
    return len(nuove)


# ---------- permessi degli agenti ----------

def _codici(nome, strumento, v):
    """I permessi (app_label, codename) che servono allo strumento sulla vista."""
    opts = v.model._meta
    codici = {(opts.app_label, f"view_{opts.model_name}")}
    if nome in PERMESSO:
        codici.add((opts.app_label, f"{PERMESSO[nome]}_{opts.model_name}"))
    for metodo in getattr(v, METODI.get(nome, ""), ()) if nome in METODI else ():
        perm = getattr(getattr(v, metodo, None), "permission", "change")
        codici.add(tuple(perm.split(".", 1)) if "." in perm else (opts.app_label, f"{perm}_{opts.model_name}"))
    return codici


def permessi_derivati():
    """I permessi che l'elenco delle operazioni ammesse dà agli agenti."""
    codici = set()
    tutte = viste()
    for e in esposte():
        if e.strumento.permesso:
            codici.add(tuple(e.strumento.permesso.split(".", 1)))
        for vid in e.viste or ():
            codici |= _codici(e.nome, e.strumento, tutte[vid])
    if not codici:
        return Permission.objects.none()
    return Permission.objects.filter(Q(*[Q(content_type__app_label=a, codename=c) for a, c in codici],
                                       _connector=Q.OR))


def allinea_gruppo():
    """Ricalcola i permessi del gruppo «AWF / Agenti» dalle operazioni ammesse."""
    from . import agenti
    g = agenti.gruppo()
    g.permissions.set(list(permessi_derivati()))
    return g
