"""Il giro di allineamento di un collegamento: si legge l'albero della cartella su SharePoint, si copia in adabox ciò che
è cambiato di là (se il verso lo prevede), poi si scrive su SharePoint ciò che è cambiato in adabox (idem).

Chi è cambiato si capisce da FileSharePoint: il cTag di SharePoint e la versione del documento all'ultimo
allineamento. Se cambiano entrambi, vince SharePoint e il file di adabox resta tra le versioni precedenti del
documento: non si perde nulla. Un file tolto da SharePoint finisce nel cestino dei Documenti; su SharePoint non si
cancella mai nulla."""
import datetime
import logging

from django.core.files.base import ContentFile
from django.db.models import Q
from django.utils import timezone

from core import allegati, cifratura, lavori
from documenti import quote, servizi
from documenti.models import Cartella, Documento

from . import graph, prova
from .models import CollegamentoSharePoint, FileSharePoint

log = logging.getLogger("sharepoint")
MAX_FILE_PER_GIRO = 200                 # copie per verso in un giro; il resto al giro dopo
BLOCCO_SCADE = datetime.timedelta(minutes=30)
PROFONDITA = 20


class DepositoCollegamento(graph.Deposito):
    """Il token di accesso cifrato sul collegamento, finché non scade: lo condividono tutti i giri."""

    def __init__(self, collegamento):
        self.collegamento = collegamento

    def leggi(self):
        c = self.collegamento
        if c.accesso_cifrato and c.accesso_scade and c.accesso_scade > timezone.now():
            try:
                return cifratura.decifra(c.accesso_cifrato)
            except Exception:                   # chiave cambiata: se ne chiede uno nuovo
                return None
        return None

    def salva(self, token, scade):
        c = self.collegamento
        c.accesso_cifrato, c.accesso_scade = cifratura.cifra(token), scade
        CollegamentoSharePoint.objects.filter(pk=c.pk).update(accesso_cifrato=c.accesso_cifrato, accesso_scade=scade)


def client(collegamento):
    """Il client Graph del collegamento: in prova parla con la SharePoint finta, se no con quella vera."""
    deposito = DepositoCollegamento(collegamento)
    if collegamento.modalita == CollegamentoSharePoint.PROVA:
        return graph.Graph(prova.TENANT, "prova", "prova", deposito=deposito, transport=prova.trasporto(collegamento))
    if not (collegamento.tenant and collegamento.client_id and collegamento.segreto_cifrato):
        raise graph.ErroreSharePoint("Mancano tenant, client id o client secret: inseriscili nel collegamento.")
    return graph.Graph(collegamento.tenant, collegamento.client_id, collegamento.segreto(), deposito=deposito)


def sito_di(collegamento):
    return prova.SITO if collegamento.modalita == CollegamentoSharePoint.PROVA else collegamento.sito


def libreria_di(collegamento):
    return "" if collegamento.modalita == CollegamentoSharePoint.PROVA else collegamento.libreria


def verifica(collegamento, g=None):
    """Prova l'accesso e trova sito, raccolta e cartella. Restituisce il nome del sito."""
    g = g or client(collegamento)
    sito = g.sito(sito_di(collegamento))
    drive_id = g.libreria(sito["id"], libreria_di(collegamento))
    if collegamento.modalita == CollegamentoSharePoint.PROVA:
        prova.prepara(collegamento)
    cartella_id = g.cartella(drive_id, collegamento.percorso, crea=collegamento.scrive)
    collegamento.drive_id, collegamento.cartella_id_esterna = drive_id, cartella_id
    CollegamentoSharePoint.objects.filter(pk=collegamento.pk).update(drive_id=drive_id, cartella_id_esterna=cartella_id)
    return sito["nome"]


# --- il giro ----------------------------------------------------------------------------------------------------------

def _prendi(collegamento_id):
    """Un giro alla volta per collegamento: il blocco scade da solo se un giro muore a metà."""
    adesso = timezone.now()
    return bool(CollegamentoSharePoint.objects.filter(pk=collegamento_id).filter(
        Q(in_corso_dal__isnull=True) | Q(in_corso_dal__lt=adesso - BLOCCO_SCADE)).update(in_corso_dal=adesso))


def giro(collegamento_id):
    """Lavoro: allinea un collegamento. Gli errori temporanei risalgono, così il lavoro riprova."""
    c = CollegamentoSharePoint.objects.select_related("azienda", "cartella").filter(pk=collegamento_id, attivo=True).first()
    if c is None:
        return "collegamento spento o tolto"
    if not _prendi(c.pk):
        return "c'è già un giro in corso"
    esito, in_errore = "", False
    try:
        esito = Giro(c).esegui()
        return esito
    except graph.ErroreTemporaneo as e:
        esito, in_errore = f"{e} Si riprova.", True
        raise
    except graph.ErroreSharePoint as e:
        esito, in_errore = str(e), True
        return esito
    finally:
        CollegamentoSharePoint.objects.filter(pk=c.pk).update(in_corso_dal=None, ultimo_giro=timezone.now(),
                                                              ultimo_esito=esito[:1000], in_errore=in_errore)


giro.senza_transazione = True                # la rete non deve tenere aperta una transazione


def giro_di_tutti():
    """Dal cron: un lavoro per collegamento, così uno lento o in errore non ferma gli altri."""
    for pk in CollegamentoSharePoint.objects.filter(attivo=True).values_list("pk", flat=True):
        lavori.accoda("sharepoint.sincronia.giro", collegamento_id=pk, max_tentativi=3)


class Giro:
    def __init__(self, collegamento, g=None):
        self.c = collegamento
        self.g = g or client(collegamento)
        self.copiati_qui = self.copiati_li = self.cestinati = 0
        self.problemi = []
        self.max_byte = quote.max_file_mb(collegamento.azienda) * 1024 * 1024

    def esegui(self):
        try:
            verifica(self.c, self.g)
            voci, completo = self.g.albero(self.c.drive_id, self.c.cartella_id_esterna)
            if self.c.legge:
                self.leggi(voci, completo)
            if self.c.scrive:
                self.scrivi(voci)
        finally:
            self.g.chiudi()
        return self.esito(completo)

    def esito(self, completo):
        parti = []
        if self.c.legge:
            parti.append(f"{self.copiati_qui} file copiati da SharePoint")
        if self.c.scrive:
            parti.append(f"{self.copiati_li} file copiati su SharePoint")
        if self.cestinati:
            parti.append(f"{self.cestinati} documenti nel cestino perché tolti da SharePoint")
        testo = ", ".join(parti)
        testo = testo[:1].upper() + testo[1:] + "."
        if not completo:
            testo += f" La cartella su SharePoint ha più di {graph.MAX_VOCI} voci: lette solo le prime, nessun documento cestinato."
        if self.problemi:
            testo += " Da guardare: " + "; ".join(self.problemi[:5]) + ("; …" if len(self.problemi) > 5 else "") + "."
        return testo

    # --- le cartelle dei Documenti sotto quella collegata --------------------------------------------------------------

    def cartella_per(self, percorso):
        """La cartella dei Documenti per il percorso relativo («A/B»), creata se manca, sotto quella collegata."""
        cartella = self.c.cartella
        for nome in [p for p in percorso.split("/") if p][:PROFONDITA]:
            nome = servizi.nome_visibile(nome)[:120] or "senza nome"
            figlia = Cartella.objects.filter(padre=cartella, nome=nome).order_by("pk").first()
            cartella = figlia or Cartella.objects.create(azienda=cartella.azienda, padre=cartella, nome=nome)
        return cartella

    def sottocartelle(self):
        """{cartella_id: percorso relativo} della cartella collegata e di tutte le sue sottocartelle."""
        percorsi, livello = {self.c.cartella_id: ""}, [self.c.cartella_id]
        for _ in range(PROFONDITA):
            figlie = list(Cartella.objects.filter(padre_id__in=livello).exclude(pk__in=percorsi).values_list("pk", "padre_id", "nome"))
            if not figlie:
                break
            for pk, padre, nome in figlie:
                percorsi[pk] = f"{percorsi[padre]}/{nome}" if percorsi[padre] else nome
            livello = [pk for pk, _, _ in figlie]
        return percorsi

    # --- da SharePoint ad adabox ---------------------------------------------------------------------------------------

    def leggi(self, voci, completo):
        mappa = {f.id_esterno: f for f in FileSharePoint.objects.filter(collegamento=self.c).select_related("documento__cartella")}
        visti, copiati = set(), 0
        for voce in voci:
            if voce["cartella"]:
                self.cartella_per(voce["percorso"])
                continue
            item, percorso = voce["item"], voce["percorso"]
            visti.add(item["id"])
            legame = mappa.get(item["id"])
            if legame is not None:
                self._segui_spostamento(legame, percorso)
                if legame.ctag == item.get("cTag"):
                    continue
            if copiati >= MAX_FILE_PER_GIRO:
                continue
            try:
                if self._copia_qui(item, percorso, legame):
                    copiati += 1
            except (allegati.AllegatoNonValido, quote.QuotaSuperata) as e:
                self.problemi.append(str(e))
            except graph.ErroreTemporaneo:
                raise
            except graph.ErroreSharePoint as e:
                self.problemi.append(f"«{percorso}»: {e}")
        self.copiati_qui = copiati
        if completo:
            for id_esterno, legame in mappa.items():
                if id_esterno not in visti:
                    self.cestinati += servizi.cestina([legame.documento])
                    legame.delete()

    def _segui_spostamento(self, legame, percorso):
        """Un file rinominato o spostato su SharePoint: il documento lo segue."""
        if legame.percorso == percorso:
            return
        doc, cartella_rel, _, nome = legame.documento, *percorso.rpartition("/")
        cartella = self.cartella_per(cartella_rel)
        Documento.objects.filter(pk=doc.pk).update(nome=servizi.nome_visibile(nome) or doc.nome, cartella=cartella)
        FileSharePoint.objects.filter(pk=legame.pk).update(percorso=percorso)
        legame.percorso = percorso

    def _copia_qui(self, item, percorso, legame):
        nome = servizi.nome_visibile(item["name"]) or "senza nome"
        if (item.get("size") or 0) > self.max_byte:
            self.problemi.append(f"«{percorso}» supera {self.max_byte // (1024 * 1024)} MB, il massimo dei Documenti")
            return False
        doc = legame.documento if legame is not None else None
        if doc is not None and doc.bloccato_da_id:
            self.problemi.append(f"«{percorso}» è bloccato in adabox da {doc.bloccato_da}: si aggiorna dopo lo sblocco")
            return False
        contenuto = ContentFile(self.g.scarica(self.c.drive_id, item["id"], self.max_byte), name=nome)
        if doc is None:
            doc = servizi.carica(self.cartella_per(percorso.rpartition("/")[0]), contenuto, None)
        else:
            if self.c.scrive and doc.versione != legame.versione:
                self.problemi.append(f"«{percorso}» cambiato da entrambe le parti: tenuto quello di SharePoint, "
                                     "quello di adabox è tra le versioni precedenti")
            contenuto.name = allegati.valida(contenuto, max_mb=quote.max_file_mb(doc.azienda))
            quote.controlla(doc.cartella, contenuto.size)
            doc = servizi.nuova_versione(doc, contenuto, None)
        FileSharePoint.objects.filter(collegamento=self.c, documento=doc).exclude(id_esterno=item["id"]).delete()
        FileSharePoint.objects.update_or_create(collegamento=self.c, id_esterno=item["id"], defaults={
            "azienda": self.c.azienda, "documento": doc, "percorso": percorso, "ctag": item.get("cTag") or "", "versione": doc.versione})
        return True

    # --- da adabox a SharePoint ----------------------------------------------------------------------------------------

    def scrivi(self, voci):
        presenti = {v["item"]["id"]: v for v in voci}
        cartelle_sp = {"": self.c.cartella_id_esterna}
        cartelle_sp.update({v["percorso"]: v["item"]["id"] for v in voci if v["cartella"]})
        percorsi = self.sottocartelle()
        legami = {f.documento_id: f for f in FileSharePoint.objects.filter(collegamento=self.c)}
        documenti = (Documento.objects.filter(cartella_id__in=percorsi, cestinato_il__isnull=True, allegato__isnull=True)
                     .exclude(file="").order_by("pk"))
        copiati = 0
        for doc in documenti.iterator():
            base = "/".join(graph.nome_per_sharepoint(p) for p in percorsi[doc.cartella_id].split("/") if p)
            percorso = f"{base}/{graph.nome_per_sharepoint(doc.nome)}" if base else graph.nome_per_sharepoint(doc.nome)
            legame = legami.get(doc.pk)
            if legame is not None and legame.versione == doc.versione and legame.percorso == percorso and legame.id_esterno in presenti:
                continue
            if copiati >= MAX_FILE_PER_GIRO:
                break
            try:
                self._copia_li(doc, base, percorso, legame, presenti, cartelle_sp)
                copiati += 1
            except graph.ErroreTemporaneo:
                raise
            except graph.ErroreSharePoint as e:
                self.problemi.append(f"«{doc.nome}»: {e}")
        self.copiati_li = copiati

    def _cartella_sp(self, base, cartelle_sp):
        if base in cartelle_sp:
            return cartelle_sp[base]
        madre, _, nome = base.rpartition("/")
        cartelle_sp[base] = self.g.sottocartella(self.c.drive_id, self._cartella_sp(madre, cartelle_sp), nome)
        return cartelle_sp[base]

    def _copia_li(self, doc, base, percorso, legame, presenti, cartelle_sp):
        padre = self._cartella_sp(base, cartelle_sp)
        nome = percorso.rpartition("/")[2]
        if legame is not None and legame.id_esterno in presenti and legame.percorso != percorso:
            self.g.sposta(self.c.drive_id, legame.id_esterno, padre, nome)       # rinominato in adabox: niente doppioni
        with doc.file.open("rb") as f:
            contenuto = f.read()
        item = self.g.carica(self.c.drive_id, padre, nome, contenuto)
        FileSharePoint.objects.filter(collegamento=self.c, id_esterno=item["id"]).exclude(documento=doc).delete()
        FileSharePoint.objects.update_or_create(collegamento=self.c, documento=doc, defaults={
            "azienda": self.c.azienda, "id_esterno": item["id"], "percorso": percorso, "ctag": item.get("cTag") or "",
            "versione": doc.versione})
