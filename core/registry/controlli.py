"""`modulo controlla`: le regole di un modulo, lette dal codice senza eseguirlo. Un errore va corretto prima di
consegnare; un avviso può essere voluto, ma qualcuno deve averci pensato. I controlli sono euristici: non sostituiscono
i test né la revisione, e non vedono ciò che passa da funzioni di altri file."""
import ast
import re
from dataclasses import dataclass
from pathlib import Path

from django.apps import apps

from . import manifest, modules

ERRORE, AVVISO = "errore", "avviso"
SEGRETO = re.compile(r"(^|_)(token|password|segreto|secret|api_?key)($|_)")
COMANDATI = {"login_required", "permission_required", "staff_member_required", "portale"}


@dataclass
class Rilievo:
    livello: str
    regola: str
    file: str
    riga: int
    testo: str

    def __str__(self):
        posto = f"{self.file}:{self.riga}" if self.riga else self.file
        return f"[{self.livello}] {self.regola} {posto}: {self.testo}"


def _chiusura(slug, info):
    visti, da_vedere = set(), list(modules.dipendenze(slug, info)) if slug in info else []
    while da_vedere:
        s = da_vedere.pop()
        if s not in visti:
            visti.add(s)
            if s in info:
                da_vedere.extend(modules.dipendenze(s, info))
    return visti


def _sorgenti(cartella):
    for f in sorted(cartella.rglob("*.py")):
        relativo = f.relative_to(cartella)
        if relativo.parts[0] in ("tests", "migrations") or "__pycache__" in relativo.parts:
            continue
        try:
            yield str(relativo), ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as e:
            yield str(relativo), e


def _nomi_base(classe):
    return {getattr(b, "id", getattr(b, "attr", "")) for b in classe.bases}


def _assegnati(classe):
    nomi = {}
    for n in classe.body:
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    nomi[t.id] = n.value
    return nomi


def _modelli(alberi):
    """{nome classe: dati} dei modelli del modulo, da models.py."""
    risultato = {}
    albero = alberi.get("models.py")
    if albero is None:
        return risultato
    for n in albero.body:
        if not isinstance(n, ast.ClassDef):
            continue
        basi, campi = _nomi_base(n), _assegnati(n)
        meta = next((x for x in n.body if isinstance(x, ast.ClassDef) and x.name == "Meta"), None)
        astratto = meta is not None and any(isinstance(v, ast.Constant) and v.value is True and k == "abstract" for k, v in _assegnati(meta).items())
        if astratto or not ({"Model", "AziendaMixin"} & basi or any(b.endswith("Mixin") for b in basi)):
            continue
        padri = [k for k, v in campi.items() if isinstance(v, ast.Call) and getattr(v.func, "attr", "") == "ForeignKey"]
        risultato[n.name] = {"riga": n.lineno, "azienda": "AziendaMixin" in basi or "azienda" in campi, "padri": padri, "campi": campi}
    return risultato


def _con_azienda(locali):
    nomi = {m for m, d in locali.items() if d["azienda"]}
    for m in apps.get_models():                      # anche i modelli degli altri moduli importati qui
        if any(f.name == "azienda" for f in m._meta.fields):
            nomi.add(m.__name__)
    return nomi


def _manifest(cartella, slug, rilievi):
    try:
        m = manifest.leggi(cartella)
    except manifest.ManifestNonValido as e:
        rilievi.extend(Rilievo(ERRORE, "manifest", "__manifest__.py", 0, err) for err in e.errori)
        return None
    if m.application and m.icon and not (cartella / "static" / m.icon).is_file():
        rilievi.append(Rilievo(AVVISO, "icona", "__manifest__.py", 0, f"icona {m.icon} non trovata in static/"))
    if not (cartella / "tests").is_dir():
        rilievi.append(Rilievo(AVVISO, "test", "tests/", 0, "il modulo non ha test: il collaudo prova solo l'installazione"))
    return m


def _import(alberi, slug, ammessi, altri, testi, m, rilievi):
    """Un altro modulo si usa solo se è una dipendenza dichiarata, oppure dentro un controllo apps.is_installed."""
    for file, albero in alberi.items():
        for n in ast.walk(albero):
            nomi = [a.name.split(".")[0] for a in n.names] if isinstance(n, ast.Import) else (
                [n.module.split(".")[0]] if isinstance(n, ast.ImportFrom) and n.module and n.level == 0 else [])
            for x in nomi:
                if x == slug or x not in altri or x in ammessi:
                    continue
                solo_con_ai = x == "ai" and m is not None and m.ai and file == f"{m.ai.split('.')[-1]}.py"
                if solo_con_ai:
                    continue
                if n.col_offset == 0:
                    rilievi.append(Rilievo(ERRORE, "dipendenze", file, n.lineno, f"importa «{x}» senza dichiararlo in depends: senza quel modulo non parte"))
                elif f'"{x}"' not in testi[file] and f"'{x}'" not in testi[file] and "is_installed" not in testi[file] and "ADDONS_ATTIVI" not in testi[file]:
                    rilievi.append(Rilievo(AVVISO, "dipendenze", file, n.lineno, f"importa «{x}» senza apps.is_installed: fallirebbe se non è installato"))


def _viste(alberi, locali, rilievi, su_misura=False):
    con_vista = set()
    for file, albero in alberi.items():
        for n in ast.walk(albero):
            if not (isinstance(n, ast.ClassDef) and "ModelView" in _nomi_base(n)):
                continue
            attr = _assegnati(n)
            modello = getattr(attr.get("model"), "id", None)
            con_vista.add(modello)
            metodi = {x.name: x for x in n.body if isinstance(x, ast.FunctionDef)}
            if su_misura and "ai_descrizione" not in attr:
                rilievi.append(Rilievo(AVVISO, "ada", file, n.lineno, f"{n.name}: senza ai_descrizione, tra molti moduli Ada può scegliere un'altra vista"))
            dati = locali.get(modello)
            filtra_da_sola = "get_queryset" in metodi and "azienda" in ast.unparse(metodi["get_queryset"])
            if dati and dati["azienda"] and "company_field" not in attr and "tra_aziende" not in attr and not filtra_da_sola:
                rilievi.append(Rilievo(ERRORE, "azienda", file, n.lineno, f"{n.name}: il modello ha l'azienda ma la vista non dichiara company_field: si vedrebbero i dati di tutte le aziende (se è una pagina di amministrazione, scrivi tra_aziende = True)"))
            if dati and not dati["azienda"] and "company_field" not in attr and "tra_aziende" not in attr and "get_queryset" not in metodi:
                figli = [p for p in dati["padri"] if p not in ("utente", "creato_da")]
                if figli:
                    rilievi.append(Rilievo(AVVISO, "azienda", file, n.lineno, f"{n.name}: modello senza azienda legato a {figli[0]}: filtra in get_queryset sull'azienda del padre"))
            if q := metodi.get("get_queryset"):
                for x in ast.walk(q):
                    if isinstance(x, ast.IfExp) and isinstance(x.orelse, ast.Name) and "azienda" in ast.unparse(x.test):
                        rilievi.append(Rilievo(ERRORE, "azienda", file, x.lineno, f"{n.name}.get_queryset: senza azienda restituisce tutti i record; deve restituire qs.none()"))
    for modello, dati in locali.items():
        if dati["azienda"] and modello not in con_vista:
            rilievi.append(Rilievo(AVVISO, "vista", "models.py", dati["riga"], f"{modello} non ha una ModelView: niente pagine, API, permessi gestiti né accesso di Ada"))


def _modelli_regole(locali, cartella, rilievi):
    for modello, dati in locali.items():
        if not dati["azienda"] and not dati["padri"]:
            rilievi.append(Rilievo(AVVISO, "azienda", "models.py", dati["riga"], f"{modello} non ha l'azienda: è condiviso da tutte le aziende dell'istanza. È voluto?"))
        for campo, valore in dati["campi"].items():
            if SEGRETO.search(campo) and not campo.endswith(("_cifrato", "_hash")) and isinstance(valore, ast.Call) and getattr(valore.func, "attr", "") in ("CharField", "TextField"):
                rilievi.append(Rilievo(AVVISO, "segreti", "models.py", valore.lineno, f"{modello}.{campo} sembra un segreto in chiaro: usa core.cifratura"))
    if locali and not any((cartella / "migrations").glob("0*.py")):
        rilievi.append(Rilievo(ERRORE, "migrazioni", "migrations/", 0, "il modulo ha modelli ma nessuna migrazione: makemigrations"))


def _richieste(alberi, nomi_azienda, rilievi):
    """Una funzione che riceve la richiesta e legge un modello con azienda deve passare da queryset() o nominarla."""
    for file, albero in alberi.items():
        for n in ast.walk(albero):
            if not (isinstance(n, ast.FunctionDef) and "request" in [a.arg for a in n.args.args]):
                continue
            testo = ast.unparse(n)
            if "azienda" in testo or "queryset(" in testo or "get_queryset" in testo or "request.user" in testo:
                continue
            trovati = set()
            for x in ast.walk(n):
                if isinstance(x, ast.Attribute) and x.attr == "objects" and getattr(x.value, "id", None) in nomi_azienda:
                    trovati.add(x.value.id)
                if isinstance(x, ast.Call) and getattr(x.func, "id", "") == "get_object_or_404" and x.args and getattr(x.args[0], "id", None) in nomi_azienda:
                    trovati.add(x.args[0].id)
            if trovati:
                rilievi.append(Rilievo(AVVISO, "azienda", file, n.lineno, f"{n.name} legge {', '.join(sorted(trovati))} senza limitarsi all'azienda corrente: usa core.dashboard.queryset"))


def _pagine(alberi, rilievi):
    """Le funzioni collegate in urls.py: una pagina senza login è pubblica, deve essere una scelta."""
    urls = alberi.get("urls.py")
    if urls is None:
        return
    collegate = {x.args[1].attr: getattr(x.args[1].value, "id", "") for x in ast.walk(urls) if isinstance(x, ast.Call) and getattr(x.func, "id", "") == "path"
                 and len(x.args) > 1 and isinstance(x.args[1], ast.Attribute)}
    for file, albero in alberi.items():
        modulo = Path(file).stem
        for n in albero.body:
            if isinstance(n, ast.FunctionDef) and collegate.get(n.name) == modulo:
                decoratori = {getattr(d.func if isinstance(d, ast.Call) else d, "id", "") for d in n.decorator_list}
                if not decoratori & COMANDATI:
                    rilievi.append(Rilievo(AVVISO, "accesso", file, n.lineno, f"{n.name} risponde anche a chi non ha fatto l'accesso: è voluto?"))
                if "csrf_exempt" in decoratori:
                    rilievi.append(Rilievo(AVVISO, "accesso", file, n.lineno, f"{n.name} è senza CSRF: serve un'altra verifica, per esempio una firma"))


def _sicurezza(alberi, cartella, rilievi):
    for file, albero in alberi.items():
        for n in ast.walk(albero):
            if not isinstance(n, ast.Call):
                continue
            nome = getattr(n.func, "id", getattr(n.func, "attr", ""))
            if isinstance(n.func, ast.Name) and nome in ("eval", "exec"):
                rilievi.append(Rilievo(ERRORE, "sicurezza", file, n.lineno, f"{nome}() esegue codice arbitrario"))
            elif nome == "mark_safe" or nome == "raw" and isinstance(n.func, ast.Attribute):
                rilievi.append(Rilievo(AVVISO, "sicurezza", file, n.lineno, f"{nome}: controlla che nessun dato dell'utente ci arrivi senza escape"))
            elif nome == "execute" and "cursor" in ast.unparse(n.func):
                rilievi.append(Rilievo(AVVISO, "sicurezza", file, n.lineno, "SQL scritto a mano: niente testo dell'utente nella query, e l'azienda va filtrata a mano"))
            elif nome in ("get", "post", "put", "patch", "delete", "request", "stream") and getattr(n.func.value if isinstance(n.func, ast.Attribute) else None, "id", "") in ("httpx", "requests") \
                    and n.args and not isinstance(n.args[0], (ast.Constant, ast.JoinedStr)):
                rilievi.append(Rilievo(AVVISO, "sicurezza", file, n.lineno, "chiamata di rete verso un indirizzo variabile: se lo decide un utente, usa core.rete"))
    for t in sorted(cartella.rglob("*.html")):
        testo = t.read_text(encoding="utf-8", errors="ignore")
        for i, riga in enumerate(testo.splitlines(), 1):
            if "|safe" in riga or "autoescape off" in riga:
                rilievi.append(Rilievo(AVVISO, "sicurezza", str(t.relative_to(cartella)), i, "testo senza escape: controlla che non contenga dati degli utenti"))


def controlla(cartella):
    """I rilievi su una cartella di modulo, prima gli errori."""
    cartella = Path(cartella)
    slug, rilievi = cartella.resolve().name if cartella.name == "" else cartella.name, []
    m = _manifest(cartella, slug, rilievi)
    alberi, testi = {}, {}
    for file, albero in _sorgenti(cartella):
        if isinstance(albero, SyntaxError):
            rilievi.append(Rilievo(ERRORE, "sintassi", file, albero.lineno or 0, str(albero.msg)))
        else:
            alberi[file] = albero
            testi[file] = (cartella / file).read_text(encoding="utf-8")
    info = {s: i for s, i in modules.scopri().items() if i.manifest is not None}
    ammessi = _chiusura(slug, info) | set(m.depends if m else [])
    _import(alberi, slug, ammessi, set(info), testi, m, rilievi)
    locali = _modelli(alberi)
    _viste(alberi, locali, rilievi, su_misura=bool(m and m.su_misura))
    _modelli_regole(locali, cartella, rilievi)
    _richieste(alberi, _con_azienda(locali), rilievi)
    _pagine(alberi, rilievi)
    _sicurezza(alberi, cartella, rilievi)
    return sorted(rilievi, key=lambda r: (r.livello != ERRORE, r.file, r.riga))
