"""Legge gli estratti conto: CAMT.053 (XML ISO 20022), MT940, CBI a tracciato fisso, CSV ed Excel dell'home banking.
Nessuna scrittura, solo righe. Per MT940 e CBI il saldo iniziale più i movimenti deve dare il saldo finale: se non torna,
il file è stato letto male e non si importa niente."""
import csv
import datetime
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from lxml import etree

from .models import iban_valido, normalizza_iban

MASSIMO_BYTE = 10 * 1024 * 1024


class EstrattoNonValido(Exception):
    pass


@dataclass
class Riga:
    data: datetime.date
    importo: Decimal
    descrizione: str = ""
    valuta: datetime.date | None = None
    controparte: str = ""
    iban_controparte: str = ""
    riferimento: str = ""


@dataclass
class Estratto:
    formato: str
    righe: list
    scartate: int = 0
    iban: str = ""
    saldo: Decimal | None = None
    saldo_al: datetime.date | None = None
    coordinate: tuple | None = None          # (ABI, CAB, conto) dichiarati dal file, quando non c'è l'IBAN


def leggi(contenuto, nome=""):
    if len(contenuto) > MASSIMO_BYTE:
        raise EstrattoNonValido("Il file è troppo grande: il massimo è 10 MB.")
    if not contenuto.strip():
        raise EstrattoNonValido("Il file è vuoto.")
    inizio = contenuto.lstrip(b"\xef\xbb\xbf \r\n\t")
    if inizio.startswith(b"<"):
        return _camt(contenuto)
    if contenuto[:4] == b"PK\x03\x04":
        return _tabella(_righe_excel(contenuto), "Excel")
    testo = _decodifica(contenuto)
    if MT940_RE.search(testo):
        return _mt940(testo)
    prima = next((r for r in testo.splitlines() if r.strip()), "")
    if CBI_RE.match(prima) and ";" not in prima:
        return _cbi(testo)
    return _tabella(_righe_csv(testo), "CSV")


def _decodifica(contenuto):
    for codifica in ("utf-8-sig", "cp1252"):
        try:
            return contenuto.decode(codifica)
        except UnicodeDecodeError:
            continue
    return contenuto.decode("latin-1")


def _euro(valore):
    return f"{valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _quadra(apertura, somma, chiusura):
    """Saldo iniziale più movimenti deve dare il saldo finale: se non torna, il file è letto male e non si importa."""
    if apertura + somma != chiusura:
        raise EstrattoNonValido(
            f"Il file non torna: saldo iniziale {_euro(apertura)} € più movimenti {_euro(somma)} € fa {_euro(apertura + somma)} €, "
            f"ma il saldo finale dichiarato è {_euro(chiusura)} €. Non ho importato nulla: controlla il file, o mandacelo per verificare il formato.")


def _iban_in(testo):
    for m in re.finditer(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", testo.replace(" ", "").upper()):
        if iban_valido(m[0]):
            return m[0]
    return ""


def impronte(righe):
    """Stessa riga, stessa impronta: reimportare non crea doppioni. Due movimenti identici nello stesso file restano due."""
    visti, risultato = {}, []
    for r in righe:
        base = "|".join((r.data.isoformat(), f"{r.importo:.2f}", " ".join(r.descrizione.upper().split()), r.riferimento))
        visti[base] = visti.get(base, 0) + 1
        risultato.append(hashlib.sha256(f"{base}|{visti[base]}".encode()).hexdigest())
    return risultato


# ---------- CAMT

def _x(nodo, percorso):
    """Il testo del primo nodo su `percorso`, ignorando gli spazi dei nomi: ogni banca usa una versione diversa."""
    trovati = nodo.xpath("./" + "/".join(f"*[local-name()='{p}']" for p in percorso.split("/")))
    return (trovati[0].text or "").strip() if trovati and trovati[0].text else ""


def _figli(nodo, percorso):
    return nodo.xpath(".//" + "/".join(f"*[local-name()='{p}']" for p in percorso.split("/")))


def _data_iso(testo):
    return datetime.date.fromisoformat(testo[:10]) if testo else None


def _camt(contenuto):
    parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False, huge_tree=False)
    try:
        radice = etree.fromstring(contenuto, parser)
    except etree.XMLSyntaxError as e:
        raise EstrattoNonValido("Il file XML non è leggibile.") from e
    estratti = _figli(radice, "Stmt") or _figli(radice, "Rpt")
    if not estratti:
        raise EstrattoNonValido("Questo XML non è un estratto conto CAMT.")
    uscita, scartate, iban, saldo, saldo_al = [], 0, "", None, None
    for stmt in estratti:
        iban = iban or normalizza_iban(_x(stmt, "Acct/Id/IBAN"))
        for bal in stmt.xpath("./*[local-name()='Bal']"):
            if _x(bal, "Tp/CdOrPrtry/Cd") in ("CLBD", "CLAV"):
                try:
                    saldo = Decimal(_x(bal, "Amt")) * (-1 if _x(bal, "CdtDbtInd") == "DBIT" else 1)
                    saldo_al = _data_iso(_x(bal, "Dt/Dt") or _x(bal, "Dt/DtTm"))
                except (InvalidOperation, ValueError):
                    saldo, saldo_al = None, None
                break
        for ntry in stmt.xpath("./*[local-name()='Ntry']"):
            if (_x(ntry, "Sts") or _x(ntry, "Sts/Cd") or "BOOK") not in ("BOOK", "Booked"):
                continue                     # ancora in sospeso: arriverà contabilizzato nel prossimo estratto
            try:
                uscita += _voci(ntry)
            except (InvalidOperation, ValueError, TypeError):
                scartate += 1
    return Estratto("CAMT", uscita, scartate, iban, saldo, saldo_al)


def _voci(ntry):
    data = _data_iso(_x(ntry, "BookgDt/Dt") or _x(ntry, "BookgDt/DtTm") or _x(ntry, "ValDt/Dt"))
    valuta = _data_iso(_x(ntry, "ValDt/Dt") or _x(ntry, "ValDt/DtTm"))
    segno = -1 if _x(ntry, "CdtDbtInd") == "DBIT" else 1
    totale = Decimal(_x(ntry, "Amt"))
    dettagli = _figli(ntry, "NtryDtls/TxDtls")
    voci = []
    for tx in dettagli or [ntry]:
        parte = _x(tx, "Amt") or _x(tx, "AmtDtls/TxAmt/Amt")
        importo = Decimal(parte) if parte and len(dettagli) > 1 else totale
        chi = "Dbtr" if segno > 0 else "Cdtr"
        testo = " ".join(n.text.strip() for n in _figli(tx, "RmtInf/Ustrd") if n.text) or _x(ntry, "AddtlNtryInf") or _x(tx, "AddtlTxInf")
        voci.append(Riga(data, importo * segno, testo, valuta,
                         _x(tx, f"RltdPties/{chi}/Nm") or _x(tx, f"RltdPties/{chi}/Pty/Nm"),
                         normalizza_iban(_x(tx, f"RltdPties/{chi}Acct/Id/IBAN")),
                         (_x(tx, "Refs/AcctSvcrRef") or _x(tx, "Refs/EndToEndId") or _x(ntry, "AcctSvcrRef") or _x(ntry, "NtryRef"))[:120]))
    return voci


# ---------- CSV ed Excel

NOMI = {
    "data": ("data contabile", "data operazione", "data registrazione", "data", "date", "booking date"),
    "valuta": ("data valuta", "valuta", "value date"),
    "importo": ("importo", "importo eur", "importo (eur)", "importo euro", "amount", "movimento"),
    "dare": ("dare", "addebiti", "addebito", "uscite", "uscita"),
    "avere": ("avere", "accrediti", "accredito", "entrate", "entrata"),
    "descrizione": ("descrizione", "descrizione operazione", "causale", "dettagli", "dettaglio", "description", "causale descrizione"),
    "controparte": ("controparte", "ordinante", "beneficiario", "ordinante/beneficiario", "nominativo"),
    "riferimento": ("riferimento", "cro", "trn", "id operazione", "numero operazione"),
}


def _righe_csv(testo):
    prima = next((r for r in testo.splitlines() if r.strip() and re.search(r"[;,\t]", r)), None)
    if prima is None:
        raise EstrattoNonValido("Il file non sembra una tabella di movimenti.")
    conta = {s: "\n".join(testo.splitlines()[:40]).count(s) for s in ";\t,"}
    separatore = ";" if conta[";"] else ("\t" if conta["\t"] else ",")
    return list(csv.reader(io.StringIO(testo), delimiter=separatore))


def _righe_excel(contenuto):
    from openpyxl import load_workbook
    try:
        foglio = load_workbook(io.BytesIO(contenuto), read_only=True, data_only=True).active
        return [["" if c is None else c for c in riga] for riga in foglio.iter_rows(values_only=True)]
    except Exception as e:
        raise EstrattoNonValido("Il file Excel non è leggibile.") from e


def _intestazione(riga):
    """{campo: colonna} se la riga è l'intestazione: le banche mettono spesso qualche riga di testo prima."""
    nomi = [" ".join(str(c).strip().lower().split()) for c in riga]
    colonne = {}
    for campo, sinonimi in NOMI.items():
        for sinonimo in sinonimi:
            if sinonimo in nomi:
                colonne[campo] = nomi.index(sinonimo)
                break
    return colonne if "data" in colonne and ("importo" in colonne or "dare" in colonne or "avere" in colonne) else None


def _data(valore):
    if isinstance(valore, datetime.datetime):
        return valore.date()
    if isinstance(valore, datetime.date):
        return valore
    testo = str(valore).strip()
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.datetime.strptime(testo, formato).date()
        except ValueError:
            continue
    raise ValueError(testo)


def _importo(valore):
    """1.234,56 · -1.234,56 · 1,234.56 · 1234.56 · 1234,5 · (12,00) · +12 €. Il separatore più a destra è quello dei decimali."""
    if isinstance(valore, (int, float, Decimal)):
        return Decimal(str(valore)).quantize(Decimal("0.01"))
    testo = re.sub(r"[€\sA-Za-z]", "", str(valore))
    negativo = testo.startswith("-") or (testo.startswith("(") and testo.endswith(")")) or testo.endswith("-")
    testo = testo.strip("+-()")
    if not testo:
        raise ValueError(valore)
    virgola, punto = testo.rfind(","), testo.rfind(".")
    if virgola > punto:
        testo = testo.replace(".", "").replace(",", ".")
    elif punto > virgola and virgola >= 0:
        testo = testo.replace(",", "")
    elif punto >= 0 and re.fullmatch(r"\d{1,3}(\.\d{3})+", testo):
        testo = testo.replace(".", "")                  # 1.234 è un migliaio all'italiana, non 1 euro e 234
    numero = Decimal(testo).quantize(Decimal("0.01"))
    return -numero if negativo else numero


def _tabella(righe, formato):
    colonne, inizio = None, 0
    for i, riga in enumerate(righe[:40]):
        colonne = _intestazione(riga)
        if colonne:
            inizio = i + 1
            break
    if not colonne:
        raise EstrattoNonValido("Non trovo le colonne: servono almeno la data e l'importo (oppure dare e avere).")
    uscita, scartate = [], 0

    def cella(riga, campo):
        return riga[colonne[campo]] if campo in colonne and colonne[campo] < len(riga) else ""

    for riga in righe[inizio:]:
        if not any(str(c).strip() for c in riga):
            continue
        descrizione = str(cella(riga, "descrizione")).strip()
        grezzo = str(cella(riga, "data")).strip().lower()
        if not grezzo or grezzo.startswith(("saldo", "totale")) or descrizione.lower().startswith(("saldo iniziale", "saldo finale", "saldo contabile")):
            continue
        try:
            data = _data(cella(riga, "data"))
            if str(cella(riga, "importo")).strip():
                importo = _importo(cella(riga, "importo"))
            else:
                dare, avere = cella(riga, "dare"), cella(riga, "avere")
                importo = _importo(avere) if str(avere).strip() else -abs(_importo(dare))
            valuta = _data(cella(riga, "valuta")) if str(cella(riga, "valuta")).strip() else None
        except (ValueError, InvalidOperation):
            scartate += 1
            continue
        if not importo:
            continue
        uscita.append(Riga(data, importo, descrizione, valuta, str(cella(riga, "controparte")).strip()[:200], "", str(cella(riga, "riferimento")).strip()[:120]))
    return Estratto(formato, uscita, scartate)


# ---------- MT940 (SWIFT)

MT940_RE = re.compile(r"(?:^|\{4:)\s*:20:", re.M)
TAG_RE = re.compile(r"^:(\d{2}[A-Z]?):(.*)$")
SALDO_MT_RE = re.compile(r"^([DC])(\d{6})([A-Z]{3})(\d{1,15},\d{0,2})")
RIGA61_RE = re.compile(r"^(\d{6})(\d{4})?(RC|RD|C|D)([A-Z])?(\d{1,15},\d{0,2})([A-Z][A-Z0-9]{3})(.*)$")
CHIAVI_86 = "ORDP|BENM|NAME|REMI|EREF|IBAN|ADDR|ID|PURP|CHGS|MARF|PREF|RTRN|ULTB|ULTD|CREF|MREF|CSID"


def _yymmdd(testo):
    return datetime.date(2000 + int(testo[:2]), int(testo[2:4]), int(testo[4:6]))


def _data_contabile(mmdd, valuta):
    """Nel campo 61 la data contabile non ha l'anno: è quello della valuta, salvo a cavallo del capodanno."""
    mese, giorno = int(mmdd[:2]), int(mmdd[2:])
    anno = valuta.year + (1 if valuta.month == 12 and mese == 1 else -1 if valuta.month == 1 and mese == 12 else 0)
    return datetime.date(anno, mese, giorno)


def _campi_mt940(testo):
    """[[tag, valore]] nell'ordine del file; le righe senza tag continuano il campo prima. Via i blocchi SWIFT {1:…}{2:…}."""
    testo = re.sub(r"\{[1235]:[^}]*\}", "", testo).replace("{4:", "")
    campi = []
    for riga in testo.splitlines():
        riga = riga.rstrip()
        m = TAG_RE.match(riga)
        if m:
            campi.append([m[1], m[2]])
        elif campi and riga and riga not in ("-", "-}", "}"):
            campi[-1][1] += "\n" + riga
    return campi


def _saldo_mt940(tag, valore):
    m = SALDO_MT_RE.match(valore.strip())
    try:
        importo, data = Decimal(m[4].replace(",", ".")).quantize(Decimal("0.01")), _yymmdd(m[2])
    except (TypeError, ValueError, InvalidOperation) as e:
        raise EstrattoNonValido(f"Saldo non leggibile nel campo :{tag}: «{valore.strip()[:30]}»: non ho importato nulla.") from e
    return (-importo if m[1] == "D" else importo), data


def _riga61(valore):
    prima, _, supplemento = valore.partition("\n")
    m = RIGA61_RE.match(prima.strip())
    if not m:
        raise ValueError(prima)
    valuta = _yymmdd(m[1])
    contabile = _data_contabile(m[2], valuta) if m[2] else valuta
    importo = Decimal(m[5].replace(",", ".")).quantize(Decimal("0.01"))
    if m[3] in ("D", "RC"):                       # RC e RD sono storni: il segno si inverte
        importo = -importo
    rif_cliente, _, rif_banca = m[7].partition("//")
    riferimento = rif_banca.strip() or ("" if rif_cliente.strip() == "NONREF" else rif_cliente.strip())
    return Riga(contabile, importo, " ".join(supplemento.split()), valuta, riferimento=riferimento[:120])


def _arricchisci(riga, testo86):
    """Il campo 86 dice chi e perché: strutturato con ?20…?33, con /CHIAVI/, oppure testo libero."""
    testo = " ".join(testo86.split())
    nome = iban = riferimento = ""
    if re.search(r"\?\d{2}", testo):
        parti = re.findall(r"\?(\d{2})([^?]*)", testo)
        scopo = " ".join(v.strip() for k, v in parti if "20" <= k <= "29")
        nome = " ".join(v.strip() for k, v in parti if k in ("32", "33"))
        conto = next((v.strip() for k, v in parti if k == "31"), "")
        iban = conto if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", conto.replace(" ", "")) else ""
        m = re.search(r"EREF\+(\S+)", scopo)
        riferimento = m[1] if m else ""
        m = re.search(r"SVWZ\+(.*?)(?= [A-Z]{4}\+|$)", scopo)
        descrizione = m[1] if m else re.sub(r"\b[A-Z]{4}\+", "", scopo)
    elif re.search(rf"/({CHIAVI_86})/", testo):
        pezzi = re.split(rf"/({CHIAVI_86})/", testo)
        valori = {}
        for chiave, valore in zip(pezzi[1::2], pezzi[2::2]):
            valori.setdefault(chiave, valore.strip(" /"))
        descrizione = valori.get("REMI") or valori.get("PURP") or pezzi[0].strip(" /") or testo
        nome, iban, riferimento = valori.get("NAME", ""), valori.get("IBAN", ""), valori.get("EREF", "")
    else:
        descrizione = testo
    pezzi = [p for p in (riga.descrizione, descrizione.strip()) if p]
    riga.descrizione = " ".join(dict.fromkeys(pezzi))        # senza ripetere il supplemento del campo 61
    riga.controparte = riga.controparte or nome[:200]
    riga.iban_controparte = riga.iban_controparte or normalizza_iban(iban)[:34]
    riga.riferimento = riga.riferimento or riferimento[:120]


def _mt940(testo):
    campi = _campi_mt940(testo)
    righe, iban, saldo, saldo_al = [], "", None, None
    apertura = chiusura = None
    somma, ultima, aperto = Decimal(0), None, False

    def controlla():
        if not aperto:
            return
        if apertura is None or chiusura is None:
            raise EstrattoNonValido("Nel file MT940 manca il saldo iniziale (:60F:) o finale (:62F:): senza non posso controllare i movimenti.")
        _quadra(apertura[0], somma, chiusura[0])

    for tag, valore in campi:
        if tag == "20":
            controlla()
            apertura, chiusura, somma, ultima, aperto = None, None, Decimal(0), None, True
        elif tag == "25":
            iban = iban or _iban_in(valore)
        elif tag in ("60F", "60M"):
            apertura, aperto = _saldo_mt940(tag, valore), True
        elif tag in ("62F", "62M"):
            chiusura = _saldo_mt940(tag, valore)
            saldo, saldo_al = chiusura
        elif tag == "61":
            try:
                ultima = _riga61(valore)
            except (ValueError, InvalidOperation) as e:
                raise EstrattoNonValido(f"Movimento non leggibile nel campo :61: «{valore.splitlines()[0][:40]}»: non ho importato nulla.") from e
            righe.append(ultima)
            somma += ultima.importo
            aperto = True
        elif tag == "86" and ultima is not None:
            _arricchisci(ultima, valore)
            ultima = None
    controlla()
    if not aperto:
        raise EstrattoNonValido("Questo file MT940 non contiene movimenti.")
    return Estratto("MT940", righe, 0, iban, saldo, saldo_al)


# ---------- CBI (rendicontazione a tracciato fisso, 120 caratteri)

CBI_RE = re.compile(r"^.(RH|61\d{7})")
SALDO_CBI_RE = re.compile(r"(\d{6})([DC])(\d{15})")
RIGA62_RE = re.compile(r"^(\d{6})(\d{6})([DC])(\d{15})(\d{2})(.{3})(.{16})(.{16})(.{16})")


def _ggmmaa(testo):
    return datetime.date(2000 + int(testo[4:6]), int(testo[2:4]), int(testo[:2]))


def _centesimi(testo):
    return Decimal(int(testo)) / 100


def _saldo_cbi(record, n):
    """Data, segno e importo a 15 cifre stanno uno dietro l'altro: si cercano così, senza fidarsi delle colonne."""
    m = SALDO_CBI_RE.search(record[10:])
    if not m:
        raise EstrattoNonValido(f"Riga {n}: non trovo il saldo nel record {record[1:3]}. Non ho importato nulla.")
    try:
        data = _ggmmaa(m[1])
    except ValueError as e:
        raise EstrattoNonValido(f"Riga {n}: la data del saldo non è valida. Non ho importato nulla.") from e
    importo = _centesimi(m[3])
    return (-importo if m[2] == "D" else importo), data


def _coordinate_cbi(record):
    """ABI, CAB e numero di conto del record 61, se dove li aspetto ci sono davvero dei numeri."""
    abi, cab, conto = record[15:20], record[45:50], record[50:62].strip()
    return (abi, cab, conto.upper()) if abi.isdigit() and cab.isdigit() and conto.isalnum() else None


def _riga62(record, n):
    m = RIGA62_RE.match(record[10:])
    if not m:
        raise EstrattoNonValido(f"Riga {n}: movimento non leggibile. Non ho importato nulla.")
    try:
        valuta, contabile = _ggmmaa(m[1]), _ggmmaa(m[2])
    except ValueError as e:
        raise EstrattoNonValido(f"Riga {n}: la data del movimento non è valida. Non ho importato nulla.") from e
    importo = _centesimi(m[4])
    riferimento = m[8].strip() or m[9].strip() or m[7].strip()
    return Riga(contabile, -importo if m[3] == "D" else importo, f"Causale CBI {m[5]}", valuta, riferimento=riferimento[:120])


def _descrizione_cbi(riga, record):
    """I record 63 dicono chi e perché: ZZZ è testo libero, ID l'identificativo, IB1/IB2 l'IBAN della controparte."""
    flag, testo = record[10:13].strip(), " ".join(record[13:].split())
    if not testo:
        return
    if flag == "ID":
        riga.riferimento = riga.riferimento or testo[:120]
    elif flag in ("IB1", "IB2") and re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", testo.replace(" ", "")):
        riga.iban_controparte = normalizza_iban(testo)[:34]
    else:
        if riga.descrizione.startswith("Causale CBI"):
            riga.descrizione = ""
        riga.descrizione = f"{riga.descrizione} {testo}".strip()


def _cbi(testo):
    records = [r.rstrip("\r\n").ljust(120) for r in testo.splitlines() if r.strip()]
    righe, saldo, saldo_al, coordinate = [], None, None, None
    apertura = chiusura = None
    somma, ultima, aperto = Decimal(0), None, False

    def controlla():
        if not aperto:
            return
        if apertura is None or chiusura is None:
            raise EstrattoNonValido("Nel file CBI manca il record del saldo iniziale (61) o finale (64): senza non posso controllare i movimenti.")
        _quadra(apertura[0], somma, chiusura[0])

    for n, record in enumerate(records, 1):
        tipo = record[1:3]
        if tipo == "61":
            controlla()
            apertura, chiusura, somma, ultima, aperto = _saldo_cbi(record, n), None, Decimal(0), None, True
            coordinate = coordinate or _coordinate_cbi(record)
        elif tipo == "62":
            ultima = _riga62(record, n)
            righe.append(ultima)
            somma += ultima.importo
        elif tipo == "63":
            if ultima is not None:
                _descrizione_cbi(ultima, record)
        elif tipo == "64":
            chiusura = _saldo_cbi(record, n)
            saldo, saldo_al = chiusura
        elif tipo not in ("RH", "EF", "65"):
            raise EstrattoNonValido(f"Riga {n}: record «{tipo}» sconosciuto: questo non sembra un estratto CBI.")
    controlla()
    if not aperto:
        raise EstrattoNonValido("Questo file CBI non contiene nessun conto.")
    return Estratto("CBI", righe, 0, "", saldo, saldo_al, coordinate)
