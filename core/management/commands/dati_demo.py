"""Dati dimostrativi verosimili per provare dashboard, Analisi e previsioni: `dati_demo genera` riempie l'azienda
principale con contatti, prodotti, opportunità, preventivi e ordini, fatture con incassi, acquisti, magazzino, ticket,
progetti con compiti e ore, attività, eventi, note spese, assenze e canoni sugli ultimi mesi (stagionalità e crescita
comprese); `dati_demo azzera` toglie tutto ciò che ha creato, e solo quello (registro in ADDONS_DIR/dati_demo.json).

I documenti passano dalle operazioni vere dei moduli (conferma, emissione, incasso, spedizione), così numeri,
scadenze e giacenze sono coerenti. Ogni modulo è facoltativo: si genera ciò che è installato. Lo stesso seme dà
sempre gli stessi dati."""
import datetime
import json
import random
from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max, ProtectedError
from django.utils import timezone

REGISTRO = "dati_demo.json"
# modelli di cui si registrano le righe nuove (anche quelle create dai segnali); l'ordine è quello di cancellazione
MODELLI = [
    "fatturazione.Incasso", "fatturazione.Scadenza", "fatturazione.RigaFattura", "ricorrenti.FatturaCanone", "fatturazione.Fattura",
    "ricorrenti.Adeguamento", "ricorrenti.RigaCanone", "ricorrenti.Canone",
    "magazzino.Movimento", "magazzino.RigaConsegna", "magazzino.Consegna", "magazzino.RigaRicevimento", "magazzino.Ricevimento",
    "vendite.RigaVendita", "vendite.OrdineVendita", "acquisti.RigaAcquisto", "acquisti.OrdineAcquisto",
    "helpdesk.Valutazione", "helpdesk.Ticket", "timesheet.RigaOre", "progetti.Compito", "progetti.Milestone",
    "progetti.Sprint", "progetti.Rilascio", "progetti.Progetto", "todo.Attivita", "calendario.Evento",
    "spese.RigaSpesa", "spese.NotaSpese", "personale.Assenza", "crm.Opportunita",
    "prodotti.PrezzoListino", "prodotti.Prodotto", "prodotti.Categoria", "contatti.Contatto",
    "core.Messaggio", "core.AttivitaPianificata", "auth.User",
]

COGNOMI = ["Rossi", "Bianchi", "Ferrari", "Esposito", "Romano", "Colombo", "Ricci", "Marino", "Greco", "Bruno", "Gallo",
           "Conti", "De Luca", "Costa", "Giordano", "Mancini", "Rizzo", "Lombardi", "Moretti", "Barbieri", "Fontana",
           "Santoro", "Mariani", "Rinaldi", "Caruso", "Ferrara", "Galli", "Martini", "Leone", "Longo"]
NOMI = ["Giulia", "Marco", "Francesca", "Luca", "Chiara", "Andrea", "Sara", "Matteo", "Elena", "Davide", "Valentina",
        "Alessandro", "Martina", "Simone", "Federica", "Paolo", "Laura", "Stefano", "Silvia", "Roberto"]
SETTORI = [("Costruzioni", "Srl"), ("Impianti", "Snc"), ("Forniture", "Spa"), ("Logistica", "Srl"), ("Arredamenti", "Srl"),
           ("Meccanica", "Spa"), ("Serramenti", "Sas"), ("Informatica", "Srl"), ("Alimentari", "Spa"), ("Elettronica", "Srl"),
           ("Tessile", "Srl"), ("Trasporti", "Snc"), ("Edilizia", "Srl"), ("Packaging", "Spa"), ("Agricola", "Soc. Coop."),
           ("Automazioni", "Srl"), ("Stampa", "Snc"), ("Nautica", "Srl"), ("Energia", "Spa"), ("Farmaceutica", "Srl")]
STUDI = ["Studio Legale", "Studio Commercialista", "Studio Tecnico", "Farmacia", "Ristorante", "Hotel", "Officina", "Palestra"]
CITTA = [("Milano", "MI", "20100"), ("Roma", "RM", "00100"), ("Torino", "TO", "10100"), ("Bologna", "BO", "40100"),
         ("Firenze", "FI", "50100"), ("Napoli", "NA", "80100"), ("Genova", "GE", "16100"), ("Verona", "VR", "37100"),
         ("Padova", "PD", "35100"), ("Brescia", "BS", "25100"), ("Bergamo", "BG", "24100"), ("Modena", "MO", "41100"),
         ("Parma", "PR", "43100"), ("Cagliari", "CA", "09100"), ("Sassari", "SS", "07100"), ("Bari", "BA", "70100"),
         ("Palermo", "PA", "90100"), ("Catania", "CT", "95100"), ("Trento", "TN", "38100"), ("Udine", "UD", "33100"),
         ("Vicenza", "VI", "36100"), ("Treviso", "TV", "31100"), ("Perugia", "PG", "06100"), ("Ancona", "AN", "60100"),
         ("Pescara", "PE", "65100")]
RUOLI = ["Amministratore", "Responsabile acquisti", "Direttore tecnico", "Ufficio amministrazione", "Titolare",
         "Responsabile IT", "Responsabile commerciale", "Project manager"]
STAGIONE = {1: .9, 2: 1.0, 3: 1.15, 4: 1.05, 5: 1.1, 6: 1.0, 7: .9, 8: .45, 9: 1.1, 10: 1.2, 11: 1.15, 12: .8}

PRODOTTI = [  # (nome, tipo, categoria, unità, prezzo, costo)
    ("Server rack 2U", "bene", "Hardware", "pz", 2450, 1700), ("Notebook 14'' business", "bene", "Hardware", "pz", 1150, 820),
    ("Monitor 27'' 4K", "bene", "Hardware", "pz", 390, 265), ("Switch 24 porte PoE", "bene", "Hardware", "pz", 680, 470),
    ("Access point Wi-Fi 6", "bene", "Hardware", "pz", 210, 140), ("Stampante multifunzione A3", "bene", "Hardware", "pz", 1890, 1300),
    ("Firewall UTM", "bene", "Hardware", "pz", 1250, 860), ("UPS 1500 VA", "bene", "Hardware", "pz", 320, 215),
    ("Docking station USB-C", "bene", "Accessori", "pz", 145, 95), ("Tastiera e mouse wireless", "bene", "Accessori", "pz", 59, 34),
    ("Webcam Full HD", "bene", "Accessori", "pz", 79, 48), ("Cuffie con microfono", "bene", "Accessori", "pz", 95, 58),
    ("Toner nero", "bene", "Consumabili", "pz", 89, 52), ("Cavo di rete cat. 6 (100 m)", "bene", "Consumabili", "m", 1.2, .6),
    ("Disco SSD 1 TB", "bene", "Consumabili", "pz", 118, 80), ("Memoria RAM 16 GB", "bene", "Consumabili", "pz", 72, 50),
    ("Consulenza senior", "servizio", "Servizi", "h", 95, 0), ("Sviluppo software", "servizio", "Servizi", "h", 78, 0),
    ("Assistenza sistemistica", "servizio", "Servizi", "h", 70, 0), ("Formazione in aula", "servizio", "Servizi", "gg", 850, 0),
    ("Canone assistenza mensile", "servizio", "Servizi", "pz", 240, 0), ("Installazione e collaudo", "servizio", "Servizi", "gg", 620, 0),
    ("Licenza gestionale (anno)", "servizio", "Servizi", "pz", 1200, 0), ("Backup in cloud (mese)", "servizio", "Servizi", "pz", 45, 0),
]
TITOLI_CRM = ["Fornitura {p} per {c}", "Rinnovo assistenza {c}", "Progetto rete uffici {c}", "Migrazione gestionale {c}",
              "Postazioni di lavoro {c}", "Formazione team {c}", "Sostituzione server {c}", "Contratto manutenzione {c}",
              "Sicurezza perimetrale {c}", "Backup e continuità {c}", "Nuova sede {c}", "Licenze software {c}"]
TICKET = ["Non riesco ad accedere al gestionale", "Stampante non in rete", "Errore in fase di fatturazione", "Richiesta nuovo utente",
          "PC lento all'avvio", "Email non arrivano", "Backup fallito stanotte", "Licenza in scadenza", "Collegamento VPN instabile",
          "Monitor non si accende", "Richiesta formazione", "Aggiornamento software", "Password dimenticata", "Wi-Fi assente in sala riunioni",
          "Errore nell'export Excel", "Server non raggiungibile", "Telefono VoIP muto", "Richiesta preventivo accessori",
          "Documento non si apre", "Problema con la firma digitale"]
COMPITI = ["Analisi dei requisiti", "Disegno dell'architettura", "Configurazione ambienti", "Migrazione dei dati", "Sviluppo modulo ordini",
           "Sviluppo modulo fatture", "Integrazione email", "Test di accettazione", "Formazione utenti", "Documentazione",
           "Collaudo in sede", "Correzione anomalie", "Ottimizzazione prestazioni", "Importazione anagrafiche", "Stampe personalizzate",
           "Backup e ripristino", "Permessi e ruoli", "Dashboard direzionale", "Rilascio in produzione", "Revisione finale"]
TODO = ["Richiamare {c}", "Inviare preventivo a {c}", "Preparare offerta per {c}", "Verificare pagamento {c}", "Rinnovo contratto {c}",
        "Appuntamento in sede {c}", "Controllare consegna {c}", "Aggiornare listino", "Riunione settimanale", "Chiudere il mese",
        "Prenotare trasferta", "Rinnovare dominio", "Compilare report trimestrale", "Ordinare toner", "Verifica scadenze SLA"]
EVENTI = ["Riunione commerciale", "Demo con {c}", "Kick-off progetto {c}", "Collaudo presso {c}", "Formazione interna",
          "Stand-up tecnico", "Revisione trimestrale", "Call con {c}", "Pianificazione sprint", "Visita fornitore"]
SPESE = [("Vitto", "Pranzo con il cliente", 18, 65), ("Alloggio", "Hotel una notte", 75, 160), ("Treno, aereo, bus", "Treno A/R", 29, 140),
         ("Taxi e parcheggi", "Taxi dalla stazione", 12, 48), ("Altro", "Materiale di consumo", 8, 60)]


class Comando:
    """Lo stato di una generazione: azienda, utenti, caso, oggi, contatori."""

    def __init__(self, azienda, seme, mesi, scala, stdout):
        self.azienda, self.rnd, self.mesi, self.scala, self.stdout = azienda, random.Random(seme), mesi, scala, stdout
        self.oggi = timezone.localdate()
        self.inizio = _mesi_prima(self.oggi.replace(day=1), mesi)
        self.inizio_documenti = max(self.inizio, datetime.date(self.oggi.year, 1, 1))   # i numeri seguono l'anno
        self.utenti, self.commerciali, self.tecnici = [], [], []

    # ---------- caso ----------
    def n(self, base):
        return max(1, round(base * self.scala))

    def scegli(self, voci):
        """Una voce da [(peso, valore), ...]."""
        totale = sum(p for p, _ in voci)
        x = self.rnd.random() * totale
        for p, v in voci:
            x -= p
            if x <= 0:
                return v
        return voci[-1][1]

    def data(self, da=None, a=None, stagionale=True):
        """Una data nel periodo, più probabile nei mesi pieni e verso la fine (crescita)."""
        da, a = da or self.inizio, a or self.oggi
        giorni = max((a - da).days, 0)
        while True:
            d = da + datetime.timedelta(days=self.rnd.randint(0, giorni))
            if not stagionale:
                return d
            crescita = 1 + 0.04 * ((d.year - self.inizio.year) * 12 + d.month - self.inizio.month)
            if self.rnd.random() < STAGIONE[d.month] * crescita / 2.2:
                return d

    def ora(self, giorno, da=8, a=18):
        return timezone.make_aware(datetime.datetime.combine(giorno, datetime.time(self.rnd.randint(da, a - 1), self.rnd.choice([0, 15, 30, 45]))))

    def importo(self, minimo, massimo, passo=1):
        """Log-uniforme: tanti piccoli, pochi grandi."""
        import math
        v = math.exp(self.rnd.uniform(math.log(minimo), math.log(massimo)))
        return Decimal(int(round(v / passo)) * passo)

    def lavorativo(self, d):
        while d.weekday() >= 5:
            d += datetime.timedelta(days=1)
        return d

    def scrivi(self, testo):
        self.stdout.write(testo)


def _mesi_prima(data, mesi):
    m = data.month - 1 - mesi
    return data.replace(year=data.year + m // 12, month=m % 12 + 1, day=1)


def _modello(label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None


def _installata(app):
    return apps.is_installed(app)


def _assicura_fixture(slug):
    """Le tabelle di appoggio di un modulo (fasi, tipi…) dai suoi file `data`, se mancano."""
    from core.management.commands.modulo_applica import carica_fixture
    from core.registry import modules
    m = modules.manifests_attivi().get(slug)
    if m is not None and m.data:
        carica_fixture(m)


# ---------- generatori ----------

def utenti(c):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    nuovi = []
    for username, nome, cognome in [("giulia.verdi", "Giulia", "Verdi"), ("luca.bianchi", "Luca", "Bianchi"),
                                    ("sara.neri", "Sara", "Neri")]:
        u, creato = User.objects.get_or_create(username=username, defaults={
            "first_name": nome, "last_name": cognome, "email": f"{username}@example.com", "is_active": True})
        if creato:
            u.set_unusable_password()
            u.save(update_fields=["password"])
            nuovi.append(u)
    c.utenti = list(User.objects.filter(is_active=True, is_superuser=False).order_by("pk")) or list(User.objects.filter(is_active=True).order_by("pk"))
    superutente = User.objects.filter(is_active=True, is_superuser=True).order_by("pk").first()
    if superutente and superutente not in c.utenti:
        c.utenti.append(superutente)
    c.commerciali = c.utenti[:4]
    c.tecnici = c.utenti[-3:] if len(c.utenti) >= 3 else c.utenti
    c.scrivi(f"utenti: {len(nuovi)} nuovi, {len(c.utenti)} in uso")


def contatti(c):
    Contatto = _modello("contatti.Contatto")
    if Contatto is None:
        return [], []
    from core import sequenze
    Categoria = _modello("contatti.Categoria")
    categorie = list(Categoria.objects.all()) if Categoria else []
    usati, clienti, fornitori = set(), [], []

    def nome_azienda():
        while True:
            if c.rnd.random() < .8:
                settore, forma = c.rnd.choice(SETTORI)
                nome = f"{c.rnd.choice(COGNOMI)} {settore} {forma}"
            else:
                nome = f"{c.rnd.choice(STUDI)} {c.rnd.choice(COGNOMI)}"
            if nome not in usati:
                usati.add(nome)
                return nome

    def crea(nome, **extra):
        citta, provincia, cap = c.rnd.choice(CITTA)
        base = nome.lower().replace(" ", "").replace(".", "").replace("'", "")[:18]
        piva = "".join(str(c.rnd.randint(0, 9)) for _ in range(11))
        k = Contatto.objects.create(
            azienda=c.azienda, tipo="azienda", nome=nome, email=f"info@{base}.it", telefono=f"0{c.rnd.randint(2, 9)}{c.rnd.randint(10, 99)} {c.rnd.randint(100000, 999999)}",
            indirizzo=f"Via {c.rnd.choice(COGNOMI)} {c.rnd.randint(1, 120)}", cap=cap, citta=citta, provincia=provincia,
            partita_iva=piva, codice_sdi="0000000", responsabile=c.rnd.choice(c.commerciali) if c.commerciali else None,
            codice=sequenze.prossimo("contatti.contatto", c.azienda), **extra)
        if categorie and c.rnd.random() < .3:
            k.categorie.add(c.rnd.choice(categorie))
        return k
    for _ in range(c.n(40)):
        clienti.append(crea(nome_azienda(), cliente=True))
    for _ in range(c.n(14)):
        fornitori.append(crea(nome_azienda(), fornitore=True, cliente=c.rnd.random() < .15))
    for k in c.rnd.sample(clienti, min(len(clienti), c.n(22))):            # i referenti delle aziende clienti
        nome, cognome = c.rnd.choice(NOMI), c.rnd.choice(COGNOMI)
        Contatto.objects.create(azienda=c.azienda, tipo="persona", nome=f"{nome} {cognome}", societa=k, ruolo=c.rnd.choice(RUOLI),
                                email=f"{nome.lower()}.{cognome.lower().replace(' ', '')}@{k.email.split('@')[1]}",
                                cellulare=f"3{c.rnd.randint(20, 99)} {c.rnd.randint(1000000, 9999999)}", citta=k.citta, provincia=k.provincia,
                                codice=sequenze.prossimo("contatti.contatto", c.azienda))
    c.scrivi(f"contatti: {len(clienti)} clienti, {len(fornitori)} fornitori, referenti")
    return clienti, fornitori


def prodotti(c):
    Prodotto = _modello("prodotti.Prodotto")
    if Prodotto is None:
        return []
    from core import sequenze
    Categoria, Unita, Aliquota = _modello("prodotti.Categoria"), _modello("prodotti.UnitaMisura"), _modello("fiscale.AliquotaIva")
    if not Unita.objects.exists():
        _assicura_fixture("prodotti")
    if not Aliquota.objects.exists():
        _assicura_fixture("fiscale")
    iva = Aliquota.objects.filter(codice="22").first() or Aliquota.objects.filter(attiva=True).order_by("-percentuale").first()
    unita = {u.simbolo: u for u in Unita.objects.all()}
    creati = []
    for nome, tipo, categoria, simbolo, prezzo, costo in PRODOTTI:
        if Prodotto.objects.filter(azienda=c.azienda, nome=nome).exists():
            creati.append(Prodotto.objects.get(azienda=c.azienda, nome=nome))
            continue
        cat, _ = Categoria.objects.get_or_create(nome=categoria)
        creati.append(Prodotto.objects.create(
            azienda=c.azienda, nome=nome, tipo=tipo, categoria=cat, unita=unita.get(simbolo) or next(iter(unita.values())),
            prezzo_vendita=Decimal(str(prezzo)), costo=Decimal(str(costo)), aliquota_iva=iva, scorta_minima=Decimal(5 if tipo == "bene" else 0),
            codice=sequenze.prossimo("prodotti.prodotto", c.azienda), descrizione_vendita=nome))
    Listino, Prezzo = _modello("prodotti.Listino"), _modello("prodotti.PrezzoListino")
    listino = Listino.objects.filter(azienda=c.azienda, attivo=True).first() if Listino else None
    if listino and Prezzo:
        for p in creati:
            if p.tipo == "bene" and not Prezzo.objects.filter(listino=listino, prodotto=p).exists():
                Prezzo.objects.create(listino=listino, prodotto=p, prezzo=(p.prezzo_vendita * Decimal("0.85")).quantize(Decimal("0.01")))
    c.scrivi(f"prodotti: {len(creati)}")
    return creati


def magazzino_iniziale(c, beni):
    Movimento, Magazzino = _modello("magazzino.Movimento"), _modello("magazzino.Magazzino")
    if Movimento is None or not beni:
        return
    mag = Magazzino.objects.filter(azienda=c.azienda).order_by("-predefinito", "pk").first()
    if mag is None:
        mag = Magazzino.objects.create(azienda=c.azienda, nome="Magazzino principale", predefinito=True)
    for p in beni:
        Movimento.objects.create(azienda=c.azienda, prodotto=p, magazzino=mag, quantita=Decimal(c.rnd.randint(40, 250)),
                                 tipo="rettifica", causale="Giacenza iniziale", data=c.ora(c.inizio))
    c.scrivi("magazzino: giacenze iniziali")


def crm(c, clienti, prodotti_):
    Opportunita, Fase = _modello("crm.Opportunita"), _modello("crm.FaseCrm")
    if Opportunita is None:
        return []
    if not Fase.objects.exists():
        _assicura_fixture("crm")
    fasi = list(Fase.objects.filter(vinta=False).order_by("ordine"))
    vinta = Fase.objects.filter(vinta=True).first()
    Motivo, Etichetta = _modello("crm.MotivoPerdita"), _modello("crm.EtichettaCrm")
    motivi, etichette = list(Motivo.objects.all()), list(Etichetta.objects.all())
    vinte = []
    for _ in range(c.n(140)):
        aperta_il = c.data()
        eta = (c.oggi - aperta_il).days
        cliente = c.rnd.choice(clienti) if clienti and c.rnd.random() < .8 else None
        nome_c = cliente.nome if cliente else f"{c.rnd.choice(COGNOMI)} {c.rnd.choice(SETTORI)[0]} {c.rnd.choice(['Srl', 'Spa'])}"
        prodotto = c.rnd.choice(prodotti_).nome.split(" (")[0].lower() if prodotti_ else "materiale"
        titolo = c.rnd.choice(TITOLI_CRM).format(c=nome_c.split(" Srl")[0].split(" Spa")[0], p=prodotto)
        valore = c.importo(1500, 85000, 100)
        durata = c.rnd.randint(15, 110)
        if eta > 60:
            esito = c.scegli([(55, "vinta"), (32, "persa"), (13, "aperta")])
        elif eta > 20:
            esito = c.scegli([(25, "vinta"), (15, "persa"), (60, "aperta")])
        else:
            esito = c.scegli([(5, "vinta"), (5, "persa"), (90, "aperta")])
        chiusa_il = min(aperta_il + datetime.timedelta(days=durata), c.oggi) if esito != "aperta" else None
        if esito == "vinta" and vinta is not None:
            fase, stato, prob = vinta, "vinta", 100
        elif esito == "persa":
            fase, stato, prob = c.rnd.choice(fasi[1:] or fasi), "persa", 0
        else:
            fase = fasi[min(len(fasi) - 1, int(min(eta, 120) / 120 * len(fasi) * c.rnd.uniform(.4, 1.2)))]
            stato, prob = "aperta", fase.probabilita
        o = Opportunita.objects.create(
            azienda=c.azienda, titolo=titolo[:200], contatto=cliente, nome_contatto="" if cliente else nome_c,
            email="" if cliente else f"info@{nome_c.split()[0].lower()}.it", fase=fase, stato=stato, valore_atteso=valore, probabilita=prob,
            chiusura_prevista=aperta_il + datetime.timedelta(days=durata), chiusa_il=chiusa_il,
            commerciale=c.rnd.choice(c.commerciali) if c.commerciali else None, priorita=c.scegli([(50, 0), (30, 1), (15, 2), (5, 3)]),
            motivo_perdita=c.rnd.choice(motivi) if esito == "persa" and motivi else None)
        if etichette and c.rnd.random() < .35:
            o.etichette.add(c.rnd.choice(etichette))
        if esito == "vinta":
            vinte.append(o)
    c.scrivi(f"crm: {Opportunita.objects.filter(azienda=c.azienda).count()} opportunità ({len(vinte)} vinte)")
    return vinte


def _righe(c, Riga, campo_doc, documento, prodotti_, massimo=4):
    for p in c.rnd.sample(prodotti_, c.rnd.randint(1, min(massimo, len(prodotti_)))):
        q = Decimal(c.rnd.randint(1, 12)) if p.tipo == "bene" else Decimal(c.rnd.choice([2, 4, 8, 16, 24, 40]))
        Riga.objects.create(**{campo_doc: documento}, prodotto=p, quantita=q, sconto=Decimal(c.scegli([(60, 0), (25, 5), (15, 10)])))


def vendite(c, clienti, prodotti_, vinte):
    Ordine, Riga = _modello("vendite.OrdineVendita"), _modello("vendite.RigaVendita")
    if Ordine is None or not clienti or not prodotti_:
        return []
    from core import sequenze
    from vendite.segnali import ordine_confermato
    Termine = _modello("fiscale.TerminePagamento")
    termini = list(Termine.objects.filter(attivo=True)) if Termine else []
    confermati = []

    def crea(cliente, data, stato, commerciale):
        o = Ordine.objects.create(azienda=c.azienda, cliente=cliente, data=data, validita=data + datetime.timedelta(days=30), stato=stato,
                                  commerciale=commerciale, termine_pagamento=c.rnd.choice(termini) if termini else None,
                                  numero=sequenze.prossimo("vendite.preventivo", c.azienda))
        _righe(c, Riga, "ordine", o, prodotti_)
        o.ricalcola()
        if stato == "confermato":
            o.numero_ordine, o.confermato_il = sequenze.prossimo("vendite.ordine", c.azienda), data
            o.save(update_fields=["numero_ordine", "confermato_il"])
            ordine_confermato.send(sender=Ordine, ordine=o, utente=None)
            confermati.append(o)
        return o
    da_opportunita = [v for v in vinte if v.contatto_id and v.chiusa_il and v.chiusa_il >= c.inizio_documenti]
    for v in da_opportunita:
        crea(v.contatto, v.chiusa_il, "confermato", v.commerciale)
    for _ in range(c.n(60)):
        data = c.data(c.inizio_documenti)
        eta = (c.oggi - data).days
        stato = c.scegli([(55, "bozza"), (35, "inviato"), (10, "confermato")]) if eta < 12 else c.scegli([(72, "confermato"), (12, "annullato"), (16, "inviato")])
        crea(c.rnd.choice(clienti), data, stato, c.rnd.choice(c.commerciali) if c.commerciali else None)
    c.scrivi(f"vendite: {Ordine.objects.filter(azienda=c.azienda).count()} documenti ({len(confermati)} ordini confermati)")
    return confermati


def fatture(c, confermati):
    Fattura = _modello("fatturazione.Fattura")
    if Fattura is None or not confermati:
        return
    from core import sequenze
    from fatturazione import operazioni
    Scadenza = _modello("fatturazione.Scadenza")
    bozze = []
    for o in confermati:
        if (c.oggi - o.data).days < 3 or c.rnd.random() > .88:
            continue                                                    # qualcosa resta da fatturare
        try:
            f = operazioni.da_ordine(o)
        except ValidationError:
            continue
        f.data = min(o.data + datetime.timedelta(days=c.rnd.randint(0, 6)), c.oggi)
        f.save(update_fields=["data"])
        bozze.append(f)
    bozze.sort(key=lambda f: (f.data, f.pk))
    emesse = 0
    for f in bozze:                                                     # come emetti(), senza il vincolo sulle fatture già in archivio
        if not f.righe.exists() or f.totale <= 0:
            continue
        f.numero, f.stato, f.emessa_il = sequenze.prossimo("fatturazione.fattura", c.azienda), "emessa", c.ora(f.data)
        f.save(update_fields=["numero", "stato", "emessa_il"])
        modalita = f.termine_pagamento.modalita if f.termine_pagamento else "MP05"
        for data, importo in operazioni.calcoli.scadenze(f.termine_pagamento, f.data, f.da_incassare):
            Scadenza.objects.create(fattura=f, data=data, importo=importo, modalita=modalita)
        emesse += 1
        for s in f.scadenze.all():
            if (c.oggi - s.data).days > 2 and c.rnd.random() < .86:
                quando = min(s.data + datetime.timedelta(days=c.rnd.randint(-4, 14)), c.oggi)
                metodo = c.scegli([(70, "bonifico"), (12, "riba"), (10, "sdd"), (5, "carta"), (3, "contanti")])
                try:
                    operazioni.registra_incasso(s, data=quando, metodo=metodo, riferimento=f"Demo {f.numero}")
                except ValidationError:
                    pass
    c.scrivi(f"fatture: {emesse} emesse, {Fattura.objects.filter(azienda=c.azienda, pagata=True, stato='emessa').count()} pagate")


def acquisti(c, fornitori, beni):
    Ordine, Riga = _modello("acquisti.OrdineAcquisto"), _modello("acquisti.RigaAcquisto")
    if Ordine is None or not fornitori or not beni:
        return
    from acquisti.segnali import ordine_acquisto_confermato
    from core import sequenze
    Termine = _modello("fiscale.TerminePagamento")
    termini = list(Termine.objects.filter(attivo=True)) if Termine else []
    for _ in range(c.n(45)):
        data = c.data(c.inizio_documenti)
        eta = (c.oggi - data).days
        stato = c.scegli([(50, "bozza"), (30, "inviato"), (20, "confermato")]) if eta < 10 else c.scegli([(80, "confermato"), (8, "annullato"), (12, "inviato")])
        o = Ordine.objects.create(azienda=c.azienda, fornitore=c.rnd.choice(fornitori), data=data, stato=stato,
                                  consegna_prevista=data + datetime.timedelta(days=c.rnd.randint(5, 25)),
                                  termine_pagamento=c.rnd.choice(termini) if termini else None, buyer=c.rnd.choice(c.utenti),
                                  confermato_il=data if stato == "confermato" else None, numero=sequenze.prossimo("acquisti.ordine", c.azienda))
        for p in c.rnd.sample(beni, c.rnd.randint(1, 3)):
            Riga.objects.create(ordine=o, prodotto=p, quantita=Decimal(c.rnd.randint(5, 40)), prezzo=p.costo)
        o.ricalcola()
        if stato == "confermato":
            ordine_acquisto_confermato.send(sender=Ordine, ordine=o, utente=None)
    c.scrivi(f"acquisti: {Ordine.objects.filter(azienda=c.azienda).count()} ordini")


def magazzino_movimenti(c):
    """Ricevimenti e consegne creati dagli ordini: i più vecchi si fanno davvero, così ci sono carichi e scarichi."""
    Ricevimento, Consegna, Movimento = _modello("magazzino.Ricevimento"), _modello("magazzino.Consegna"), _modello("magazzino.Movimento")
    if Movimento is None:
        return
    from django.contrib.contenttypes.models import ContentType

    from magazzino import operazioni
    OrdineAcquisto, OrdineVendita = _modello("acquisti.OrdineAcquisto"), _modello("vendite.OrdineVendita")

    def data_documento(doc, Ordine, da, a):
        """I documenti nascono con la data di oggi: li si riporta a qualche giorno dopo l'ordine."""
        o = Ordine.objects.filter(pk=doc.origine_id).first() if Ordine and doc.origine_id else None
        doc.data = min((o.data if o else doc.data) + datetime.timedelta(days=c.rnd.randint(da, a)), c.oggi)
        doc.save(update_fields=["data"])
        return doc.data
    fatti = {"ricevuti": 0, "spediti": 0}
    for r in Ricevimento.objects.filter(azienda=c.azienda, stato="bozza").order_by("pk"):
        data = data_documento(r, OrdineAcquisto, 3, 15)
        if (c.oggi - data).days > 2 and c.rnd.random() < .85:
            operazioni.ricevi(r)
            ct = ContentType.objects.get_for_model(Ricevimento)
            Movimento.objects.filter(content_type=ct, object_id=r.pk).update(data=c.ora(data))
            fatti["ricevuti"] += 1
    for k in Consegna.objects.filter(azienda=c.azienda, stato="bozza").order_by("pk"):
        data = data_documento(k, OrdineVendita, 1, 6)
        if (c.oggi - data).days > 2 and c.rnd.random() < .85:
            try:
                operazioni.spedisci(k)
            except ValidationError:
                continue                                                # merce insufficiente: resta da spedire
            ct = ContentType.objects.get_for_model(Consegna)
            Movimento.objects.filter(content_type=ct, object_id=k.pk).update(data=c.ora(data))
            fatti["spediti"] += 1
    c.scrivi(f"magazzino: {fatti['ricevuti']} ricevimenti e {fatti['spediti']} consegne fatti")


def helpdesk(c, clienti):
    Ticket, Fase, Team = _modello("helpdesk.Ticket"), _modello("helpdesk.FaseTicket"), _modello("helpdesk.Team")
    if Ticket is None:
        return
    if not Fase.objects.exists():
        _assicura_fixture("helpdesk")
    aperte = list(Fase.objects.filter(chiusa=False).order_by("ordine"))
    chiusa = Fase.objects.filter(chiusa=True).first()
    team = Team.objects.first() or Team.objects.create(nome="Assistenza")
    team.membri.add(*c.tecnici)
    Valutazione = _modello("helpdesk.Valutazione")
    chiusi = 0
    for _ in range(c.n(170)):
        giorno = c.data()
        creato = c.ora(giorno)
        eta_ore = (timezone.now() - creato).total_seconds() / 3600
        priorita = c.scegli([(25, "bassa"), (45, "media"), (22, "alta"), (8, "urgente")])
        chiude = chiusa is not None and (eta_ore > 72 and c.rnd.random() < .9 or 8 < eta_ore <= 72 and c.rnd.random() < .5)
        t = Ticket.objects.create(azienda=c.azienda, oggetto=c.rnd.choice(TICKET), descrizione="Segnalazione dimostrativa.",
                                  contatto=c.rnd.choice(clienti) if clienti and c.rnd.random() < .85 else None, team=team,
                                  assegnatario=c.rnd.choice(c.tecnici) if c.tecnici and (chiude or c.rnd.random() < .7) else None,
                                  fase=chiusa if chiude else c.rnd.choice(aperte), priorita=priorita)
        ore_sla = t.ore_sla()
        campi = {"creato": creato, "scadenza_sla": creato + datetime.timedelta(hours=ore_sla)}
        if chiude:
            durata = ore_sla * c.rnd.uniform(.15, .95) if c.rnd.random() < .8 else ore_sla * c.rnd.uniform(1.05, 2.5)
            campi["chiuso_il"] = min(creato + datetime.timedelta(hours=durata), timezone.now())
            chiusi += 1
            if Valutazione and c.rnd.random() < .4:
                v = Valutazione.objects.create(ticket=t, voto=c.scegli([(3, 1), (5, 2), (12, 3), (40, 4), (40, 5)]), commento="")
                Valutazione.objects.filter(pk=v.pk).update(creata=campi["chiuso_il"] + datetime.timedelta(hours=c.rnd.randint(1, 48)))
        Ticket.objects.filter(pk=t.pk).update(**campi)
    c.scrivi(f"helpdesk: {Ticket.objects.filter(azienda=c.azienda).count()} ticket ({chiusi} chiusi)")


def progetti(c, clienti):
    Progetto, Compito, Fase = _modello("progetti.Progetto"), _modello("progetti.Compito"), _modello("progetti.FaseCompito")
    if Progetto is None:
        return []
    if not Fase.objects.exists():
        _assicura_fixture("progetti")
    from core import sequenze
    fasi = list(Fase.objects.filter(chiusa=False).order_by("ordine"))
    fatta = Fase.objects.filter(chiusa=True).first()
    Tipo, Milestone = _modello("progetti.TipoCompito"), _modello("progetti.Milestone")
    tipi = list(Tipo.objects.all()) if Tipo else []
    creati = []
    schema = [("attivo", 0.55), ("attivo", 0.3), ("attivo", 0.1), ("chiuso", 1.0), ("chiuso", 1.0), ("sospeso", 0.4)]
    for i, (stato, avanzamento) in enumerate(schema[:c.n(6)]):
        cliente = c.rnd.choice(clienti) if clienti else None
        inizio = c.data(a=c.oggi - datetime.timedelta(days=30), stagionale=False)
        fine = inizio + datetime.timedelta(days=c.rnd.randint(60, 240))
        p = Progetto.objects.create(azienda=c.azienda, nome=f"{c.rnd.choice(['Gestionale', 'Rete', 'Migrazione', 'Portale', 'Sicurezza', 'Formazione'])} {cliente.nome.split()[0] if cliente else 'interno'} {inizio.year}",
                                    cliente=cliente, responsabile=c.rnd.choice(c.utenti), inizio=inizio, fine=fine, stato=stato,
                                    budget_ore=Decimal(c.rnd.randint(120, 600)), descrizione="Progetto dimostrativo.",
                                    codice=sequenze.prossimo("progetti.progetto", c.azienda))
        p.membri.set(c.rnd.sample(c.utenti, min(len(c.utenti), 3)))
        tappe = [Milestone.objects.create(azienda=c.azienda, progetto=p, nome=n, scadenza=inizio + datetime.timedelta(days=int((fine - inizio).days * q)))
                 for n, q in [("Analisi", .25), ("Rilascio", .7), ("Collaudo", 1.0)]] if Milestone else []
        for titolo in c.rnd.sample(COMPITI, min(len(COMPITI), c.rnd.randint(10, 16))):
            scadenza = inizio + datetime.timedelta(days=c.rnd.randint(5, max(6, (fine - inizio).days)))
            completato = c.rnd.random() < avanzamento or (stato == "chiuso")
            k = Compito.objects.create(azienda=c.azienda, progetto=p, titolo=titolo, fase=fatta if completato and fatta else c.rnd.choice(fasi),
                                       scadenza=scadenza, priorita=c.scegli([(75, "normale"), (25, "alta")]), ore_previste=Decimal(c.rnd.choice([4, 8, 16, 24, 40])),
                                       tipo=c.rnd.choice(tipi) if tipi else None, milestone=c.rnd.choice(tappe) if tappe and c.rnd.random() < .7 else None)
            k.assegnatari.set(c.rnd.sample(c.utenti, c.rnd.randint(1, 2)))
            campi = {"creato": c.ora(max(inizio, c.inizio))}
            if completato:
                campi["completato_il"] = c.ora(min(scadenza - datetime.timedelta(days=c.rnd.randint(-3, 5)), c.oggi))
            Compito.objects.filter(pk=k.pk).update(**campi)
        creati.append(p)
    c.scrivi(f"progetti: {len(creati)} progetti, {Compito.objects.filter(azienda=c.azienda).count()} compiti")
    return creati


def timesheet(c, progetti_):
    RigaOre = _modello("timesheet.RigaOre")
    if RigaOre is None or not progetti_:
        return
    Compito = _modello("progetti.Compito")
    attivi = [p for p in progetti_ if p.stato == "attivo"] or progetti_
    approvatore = next((u for u in c.utenti if u.is_superuser), c.utenti[0])
    n = 0
    giorno = c.oggi - datetime.timedelta(days=120)
    while giorno <= c.oggi:
        if giorno.weekday() < 5:
            for u in c.utenti[:4]:
                if c.rnd.random() < .85:
                    ore_totali = c.rnd.choice([4, 6, 7, 8, 8, 8])
                    pezzi = c.rnd.randint(1, 3)
                    quote = sorted(c.rnd.sample(range(1, ore_totali), pezzi - 1)) if pezzi > 1 else []
                    for a, b in zip([0, *quote], [*quote, ore_totali]):
                        p = c.rnd.choice(attivi)
                        compiti = list(Compito.objects.filter(progetto=p)) if Compito else []
                        vecchia = (c.oggi - giorno).days > 14
                        RigaOre.objects.create(azienda=c.azienda, data=giorno, utente=u, progetto=p,
                                               compito=c.rnd.choice(compiti) if compiti and c.rnd.random() < .7 else None,
                                               descrizione=c.rnd.choice(COMPITI), ore=Decimal(b - a), fatturabile=c.rnd.random() < .8,
                                               approvata=vecchia, approvata_da=approvatore if vecchia else None,
                                               approvata_il=c.ora(giorno + datetime.timedelta(days=c.rnd.randint(1, 7))) if vecchia else None)
                        n += 1
        giorno += datetime.timedelta(days=1)
    c.scrivi(f"timesheet: {n} righe di ore")


def todo(c, clienti):
    Attivita, Tag = _modello("todo.Attivita"), _modello("todo.Tag")
    if Attivita is None:
        return
    from core import sequenze
    tag = list(Tag.objects.all()) if Tag else []
    for _ in range(c.n(70)):
        futura = c.rnd.random() < .3
        scadenza = c.oggi + datetime.timedelta(days=c.rnd.randint(0, 30)) if futura else c.data(c.oggi - datetime.timedelta(days=90), stagionale=False)
        stato = c.scegli([(70, "aperta"), (30, "in_corso")]) if futura else c.scegli([(68, "fatta"), (6, "annullata"), (18, "aperta"), (8, "in_corso")])
        cliente = c.rnd.choice(clienti).nome if clienti else "il cliente"
        creatore = c.rnd.choice(c.utenti)
        a = Attivita.objects.create(azienda=c.azienda, titolo=c.rnd.choice(TODO).format(c=cliente)[:200], scadenza=scadenza,
                                    assegnatario=c.rnd.choice(c.utenti), stato=stato, numero=sequenze.prossimo("todo.attivita", c.azienda))
        if tag and c.rnd.random() < .5:
            a.tag.add(c.rnd.choice(tag))
        Attivita.objects.filter(pk=a.pk).update(creato=c.ora(max(scadenza - datetime.timedelta(days=c.rnd.randint(1, 20)), c.inizio)), creato_da=creatore)
    c.scrivi(f"todo: {Attivita.objects.filter(azienda=c.azienda).count()} attività")


def calendario(c, clienti):
    Evento = _modello("calendario.Evento")
    if Evento is None:
        return
    for _ in range(c.n(60)):
        futuro = c.rnd.random() < .35
        giorno = c.lavorativo(c.oggi + datetime.timedelta(days=c.rnd.randint(0, 30)) if futuro else c.oggi - datetime.timedelta(days=c.rnd.randint(1, 75)))
        inizio = c.ora(giorno, 9, 17)
        cliente = c.rnd.choice(clienti) if clienti else None
        e = Evento.objects.create(azienda=c.azienda, titolo=c.rnd.choice(EVENTI).format(c=cliente.nome.split()[0] if cliente else "cliente"),
                                  inizio=inizio, fine=inizio + datetime.timedelta(minutes=c.rnd.choice([30, 60, 90, 120])),
                                  luogo=c.rnd.choice(["Sede", "Da remoto", cliente.citta if cliente else "Sede", "Sala riunioni"]),
                                  organizzatore=c.rnd.choice(c.utenti), promemoria=15)
        e.partecipanti.set(c.rnd.sample(c.utenti, c.rnd.randint(1, min(3, len(c.utenti)))))
        if cliente and c.rnd.random() < .5:
            e.contatti.add(cliente)
    c.scrivi(f"calendario: {Evento.objects.filter(azienda=c.azienda).count()} eventi")


def spese(c):
    NotaSpese, RigaSpesa, Categoria = _modello("spese.NotaSpese"), _modello("spese.RigaSpesa"), _modello("spese.CategoriaSpesa")
    Dipendente = _modello("personale.Dipendente")
    if NotaSpese is None or Dipendente is None:
        return
    if not Categoria.objects.exists():
        _assicura_fixture("spese")
    from django.core.files.base import ContentFile

    from core import sequenze
    dipendenti = list(Dipendente.objects.filter(azienda=c.azienda, attivo=True, responsabile__isnull=False)) or list(Dipendente.objects.filter(azienda=c.azienda, attivo=True))
    if not dipendenti:
        return
    categorie = {k.nome: k for k in Categoria.objects.all()}
    approvatore = next((u for u in c.utenti if u.is_superuser), c.utenti[0])
    for _ in range(c.n(26)):
        giorno = c.data(c.inizio_documenti, stagionale=False)
        eta = (c.oggi - giorno).days
        stato = c.scegli([(50, "bozza"), (50, "inviata")]) if eta < 10 else c.scegli([(12, "inviata"), (18, "approvata"), (62, "rimborsata"), (8, "rifiutata")])
        nota = NotaSpese.objects.create(azienda=c.azienda, dipendente=c.rnd.choice(dipendenti),
                                        titolo=f"Trasferta {c.rnd.choice(CITTA)[0]} {giorno:%d/%m}", numero=sequenze.prossimo("spese.nota", c.azienda))
        for nome_cat, descrizione, minimo, massimo in c.rnd.sample(SPESE, c.rnd.randint(2, 4)):
            cat = categorie.get(nome_cat) or next(iter(categorie.values()))
            RigaSpesa.objects.create(nota=nota, data=giorno, categoria=cat, descrizione=descrizione, importo=c.importo(minimo, massimo, 0.5) if not cat.chilometrica else None,
                                     km=Decimal(c.rnd.randint(20, 180)) if cat.chilometrica else None,
                                     ricevuta=ContentFile(b"%PDF-1.4 ricevuta dimostrativa", name="ricevuta.pdf") if cat.ricevuta_obbligatoria else None)
        if categorie.get("Rimborso chilometrico") and c.rnd.random() < .5:
            RigaSpesa.objects.create(nota=nota, data=giorno, categoria=categorie["Rimborso chilometrico"], descrizione="Sede - cliente", km=Decimal(c.rnd.randint(20, 220)))
        nota.ricalcola()
        campi = {"stato": stato}
        if stato != "bozza":
            campi["inviata_il"] = c.ora(giorno + datetime.timedelta(days=1))
        if stato in ("approvata", "rimborsata", "rifiutata"):
            campi.update(decisa_da=approvatore, nota_decisione="Ok" if stato != "rifiutata" else "Manca la ricevuta")
        if stato == "rimborsata":
            campi["rimborsata_il"] = min(giorno + datetime.timedelta(days=c.rnd.randint(7, 30)), c.oggi)
        NotaSpese.objects.filter(pk=nota.pk).update(**campi)
    c.scrivi(f"spese: {NotaSpese.objects.filter(azienda=c.azienda).count()} note spese")


def personale(c):
    Assenza, Tipo, Dipendente = _modello("personale.Assenza"), _modello("personale.TipoAssenza"), _modello("personale.Dipendente")
    if Assenza is None:
        return
    if not Tipo.objects.exists():
        _assicura_fixture("personale")
    dipendenti = list(Dipendente.objects.filter(azienda=c.azienda, attivo=True))
    tipi = {t.saldo or t.nome: t for t in Tipo.objects.filter(attivo=True)}
    if not dipendenti or not tipi:
        return
    approvatore = next((u for u in c.utenti if u.is_superuser), c.utenti[0])
    for _ in range(c.n(36)):
        tipo = c.scegli([(50, tipi.get("ferie")), (30, tipi.get("permessi")), (20, tipi.get("Malattia"))]) or next(iter(tipi.values()))
        futura = c.rnd.random() < .15
        if futura:
            dal = c.lavorativo(c.oggi + datetime.timedelta(days=c.rnd.randint(3, 40)))
        else:
            dal = c.lavorativo(c.data(stagionale=False) if tipo.saldo != "ferie" else c.scegli([(55, c.data(stagionale=False)), (45, datetime.date(c.oggi.year, 8, c.rnd.randint(1, 25)))]))
            dal = min(dal, c.oggi)
        giorni = 0 if tipo.unita == "ore" else (c.rnd.randint(2, 10) if tipo.saldo == "ferie" else c.rnd.randint(0, 3))
        al = dal + datetime.timedelta(days=giorni)
        stato = "richiesta" if futura and c.rnd.random() < .6 else c.scegli([(90, "approvata"), (6, "rifiutata"), (4, "annullata")])
        Assenza.objects.create(azienda=c.azienda, dipendente=c.rnd.choice(dipendenti), tipo=tipo, dal=dal, al=al,
                               ore=Decimal(c.rnd.choice([2, 4, 8])) if tipo.unita == "ore" else None, motivo="" if tipo.saldo == "ferie" else "Esigenze personali",
                               stato=stato, decisa_da=approvatore if stato in ("approvata", "rifiutata") else None,
                               decisa_il=c.ora(dal - datetime.timedelta(days=c.rnd.randint(1, 10))) if stato in ("approvata", "rifiutata") else None)
    c.scrivi(f"personale: {Assenza.objects.filter(azienda=c.azienda).count()} assenze")


def ricorrenti(c, clienti, servizi):
    Canone, Riga = _modello("ricorrenti.Canone"), _modello("ricorrenti.RigaCanone")
    if Canone is None or not clienti or not servizi:
        return
    from core import sequenze
    from ricorrenti import operazioni
    Termine = _modello("fiscale.TerminePagamento")
    termini = list(Termine.objects.filter(attivo=True)) if Termine else []
    canoni = [s for s in servizi if "Canone" in s.nome or "Licenza" in s.nome or "Backup" in s.nome] or servizi
    n = 0
    for cliente in c.rnd.sample(clienti, min(len(clienti), c.n(9))):
        inizio = c.data(c.inizio, c.oggi - datetime.timedelta(days=20), stagionale=False).replace(day=1)
        k = Canone.objects.create(azienda=c.azienda, nome=f"Assistenza e licenze {cliente.nome.split()[0]}", cliente=cliente,
                                  responsabile=c.rnd.choice(c.commerciali) if c.commerciali else None, inizio=inizio,
                                  periodicita=c.scegli([(55, 1), (30, 3), (15, 12)]), durata_mesi=12, termine_pagamento=c.rnd.choice(termini) if termini else None,
                                  numero=sequenze.prossimo("ricorrenti.contratto", c.azienda))
        for s in c.rnd.sample(canoni, min(len(canoni), c.rnd.randint(1, 2))):
            Riga.objects.create(canone=k, prodotto=s, quantita=Decimal(c.rnd.randint(1, 5)))
        if hasattr(k, "ricalcola"):
            k.ricalcola()
        try:
            operazioni.attiva(k)
            n += 1
        except ValidationError:
            pass
    c.scrivi(f"ricorrenti: {n} canoni attivi")


# ---------- registro ----------

def _percorso():
    return settings.ADDONS_DIR / REGISTRO


def _massimi():
    return {label: (M.objects.aggregate(m=Max("pk"))["m"] or 0) for label in MODELLI if (M := _modello(label)) is not None}


def _nuovi(prima):
    nuovi = {}
    for label, massimo in prima.items():
        pks = list(_modello(label).objects.filter(pk__gt=massimo).values_list("pk", flat=True))
        if pks:
            nuovi[label] = pks
    return nuovi


def _elimina(oggetti, stdout):
    rimasti = {label: set(pks) for label, pks in oggetti.items()}
    while rimasti:
        progresso = False
        for label in [l for l in MODELLI if l in rimasti] + [l for l in rimasti if l not in MODELLI]:
            M = _modello(label)
            if M is None:
                rimasti.pop(label)
                continue
            try:
                with transaction.atomic():
                    n, _ = M.objects.filter(pk__in=list(rimasti[label])).delete()
                stdout.write(f"  {label}: {n} eliminati" if n else f"  {label}: niente")
                rimasti.pop(label)
                progresso = True
            except ProtectedError:
                continue                                              # ci riprova dopo aver tolto chi lo protegge
        if not progresso:
            raise CommandError("Non riesco a eliminare: " + ", ".join(rimasti))


class Command(BaseCommand):
    help = "Dati dimostrativi: «genera» li crea sull'azienda principale, «azzera» toglie solo quelli."

    def add_arguments(self, parser):
        parser.add_argument("operazione", choices=["genera", "azzera"])
        parser.add_argument("--mesi", type=int, default=13, help="mesi di storia (default 13)")
        parser.add_argument("--seme", type=int, default=7, help="seme del caso: stesso seme, stessi dati")
        parser.add_argument("--scala", type=float, default=1.0, help="moltiplicatore dei volumi (0.2 = un quinto)")
        parser.add_argument("--forza", action="store_true", help="genera anche se c'è già un registro di dati demo")

    def handle(self, operazione, mesi, seme, scala, forza, **_):
        percorso = _percorso()
        if operazione == "azzera":
            if not percorso.exists():
                raise CommandError("Nessun dato demo registrato.")
            registro = json.loads(percorso.read_text())
            self.stdout.write(f"Tolgo i dati demo generati il {registro.get('generato', '?')[:16]}…")
            _elimina(registro["oggetti"], self.stdout)
            percorso.unlink()
            self.stdout.write(self.style.SUCCESS("Fatto."))
            return
        if percorso.exists() and not forza:
            raise CommandError("Ci sono già dati demo (ADDONS_DIR/dati_demo.json): prima «dati_demo azzera», o --forza.")
        from core.models import Azienda
        azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
        if azienda is None:
            raise CommandError("Nessuna azienda attiva.")
        c = Comando(azienda, seme, mesi, scala, self.stdout)
        prima = _massimi()
        self.stdout.write(f"Genero dati demo per «{azienda}» dal {c.inizio:%d/%m/%Y} (seme {seme}, scala {scala})…")
        with transaction.atomic():
            utenti(c)
            clienti, fornitori = contatti(c)
            prodotti_ = prodotti(c)
            beni = [p for p in prodotti_ if p.tipo == "bene"]
            servizi = [p for p in prodotti_ if p.tipo == "servizio"]
            magazzino_iniziale(c, beni)
            vinte = crm(c, clienti, prodotti_)
            confermati = vendite(c, clienti, prodotti_, vinte)
            acquisti(c, fornitori, beni)
            magazzino_movimenti(c)
            fatture(c, confermati)
            helpdesk(c, clienti)
            progetti_ = progetti(c, clienti)
            timesheet(c, progetti_)
            todo(c, clienti)
            calendario(c, clienti)
            spese(c)
            personale(c)
            ricorrenti(c, clienti, servizi)
            nuovi = _nuovi(prima)
        registro = {"generato": timezone.now().isoformat(), "azienda": azienda.pk, "seme": seme, "mesi": mesi, "scala": scala,
                    "oggetti": nuovi}
        percorso.write_text(json.dumps(registro))
        totale = sum(len(v) for v in nuovi.values())
        self.stdout.write(self.style.SUCCESS(f"Fatto: {totale} record in {len(nuovi)} tabelle; «dati_demo azzera» li toglie."))
