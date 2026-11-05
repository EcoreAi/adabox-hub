"""Le istanze ospitate: niente sovrascritture, segreti diversi e protetti, aggiornamento che torna indietro e si ferma."""
import importlib.util
import json
import stat
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.db import DatabaseError

from core.models import Azienda, Ruolo

percorso = Path(__file__).resolve().parents[2] / "deploy" / "flotta.py"
spec = importlib.util.spec_from_file_location("flotta_in_prova", percorso)
flotta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flotta)


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Nessun docker vero: si ricorda i comandi, risponde come il portale e come primo_admin."""
    monkeypatch.setenv("FLOTTA_RADICE", str(tmp_path))
    comandi = []

    def esegui(comando, entrata=None, uscita=None, ambiente=None, controlla=True):
        comandi.append((comando, ambiente or {}))
        if uscita:
            Path(uscita).write_bytes(b"dati")
        if "rivendita_istanza" in comando:
            return json.dumps({"codice": "cod-1", "token": "TOKEN-SEGRETO", "chiave_pubblica": "CHIAVE"}) + "\n"
        if "primo_admin" in comando:
            return "PASSWORD=pw-iniziale\n"
        return ""
    monkeypatch.setattr(flotta, "esegui", esegui)
    monkeypatch.setattr(flotta, "in_salute", lambda dati, attesa=0: True)
    return comandi


def _argomenti(slug="rossi", **extra):
    a = ["crea", slug, "--cliente", "Rossi Srl", "--dominio", "hub.rossi.it", "--email", "a@rossi.it", "--piano", "Base", "--versione", "1.0", "--url-portale", "https://p/api"]
    for k, v in extra.items():
        a += [f"--{k}", v]
    return a


def _testi(comandi):
    return [" ".join(c) for c, _ in comandi]


def test_crea_fa_tutto_in_ordine(ambiente, capsys):
    flotta.main(_argomenti())
    testi = _testi(ambiente)
    passi = ["rivendita_istanza crea", "up -d", "licenza sincronizza", "primo_admin"]
    posizioni = [next(i for i, t in enumerate(testi) if p in t) for p in passi]
    assert posizioni == sorted(posizioni)
    uscita = capsys.readouterr().out
    assert "pw-iniziale" in uscita and "TOKEN-SEGRETO" not in uscita
    assert "-p adabox_rossi" in next(t for t in testi if "up -d" in t)


def test_segreti_nel_file_protetto_e_diversi_per_istanza(ambiente):
    flotta.main(_argomenti("rossi"))
    flotta.main(_argomenti("bianchi"))
    a, b = (flotta.cartella(s) / ".env" for s in ("rossi", "bianchi"))
    assert stat.S_IMODE(a.stat().st_mode) == 0o600 and stat.S_IMODE(flotta.cartella("rossi").stat().st_mode) == 0o700
    valori = [dict(r.split("=", 1) for r in f.read_text().splitlines()) for f in (a, b)]
    for chiave in ("SECRET_KEY", "CHIAVE_CIFRATURA", "POSTGRES_PASSWORD", "SESSION_COOKIE_NAME"):
        assert valori[0][chiave] != valori[1][chiave]
    assert valori[0]["LICENZA_TOKEN"] == "TOKEN-SEGRETO" and valori[0]["DEBUG"] == "False" and valori[0]["SESSION_COOKIE_SECURE"] == "True"
    assert valori[0]["SITO_URL"] == "https://hub.rossi.it" and valori[0]["MODULI_FIRMA_OBBLIGATORIA"] == "True"
    from cryptography.fernet import Fernet
    Fernet(valori[0]["CHIAVE_CIFRATURA"])
    assert "TOKEN-SEGRETO" not in (flotta.cartella("rossi") / "istanza.json").read_text()


def test_porte_diverse_e_mai_sovrascrivere(ambiente):
    flotta.main(_argomenti("rossi"))
    flotta.main(_argomenti("bianchi"))
    assert flotta.leggi("rossi")["porta"] != flotta.leggi("bianchi")["porta"]
    prima = (flotta.cartella("rossi") / ".env").read_text()
    with pytest.raises(SystemExit, match="non la sovrascrivo"):
        flotta.main(_argomenti("rossi"))
    assert (flotta.cartella("rossi") / ".env").read_text() == prima


@pytest.mark.parametrize("slug", ["R", "a", "../x", "a b", "a;rm", "A1"])
def test_nomi_non_validi(ambiente, slug):
    with pytest.raises(SystemExit, match="non valido"):
        flotta.main(_argomenti(slug))
    assert not ambiente


@pytest.mark.parametrize("dominio", ["a b", "../x", "x/y", "x;y"])
def test_domini_non_validi(ambiente, dominio):
    a = _argomenti()
    a[a.index("hub.rossi.it")] = dominio
    with pytest.raises(SystemExit, match="dominio"):
        flotta.main(a)


def test_serve_l_indirizzo_del_portale(ambiente, monkeypatch):
    monkeypatch.delenv("FLOTTA_URL_PORTALE", raising=False)
    a = _argomenti()
    with pytest.raises(SystemExit, match="url-portale"):
        flotta.main(a[:-2])


def test_istanza_che_non_parte_lo_dice(ambiente, monkeypatch):
    monkeypatch.setattr(flotta, "in_salute", lambda dati, attesa=0: False)
    with pytest.raises(SystemExit, match="non risponde"):
        flotta.main(_argomenti())


def test_aggiornamento_riuscito_salva_prima(ambiente):
    flotta.main(_argomenti())
    ambiente.clear()
    flotta.main(["aggiorna", "rossi", "--versione", "2.0"])
    testi = _testi(ambiente)
    assert next(i for i, t in enumerate(testi) if "pg_dump" in t) < next(i for i, t in enumerate(testi) if "up -d" in t)
    su = next(a for c, a in ambiente if "up" in c)
    d = flotta.leggi("rossi")
    assert su["VERSIONE"] == "2.0" and d["versione"] == "2.0" and d["storia"][-1]["esito"] == "ok"


def test_aggiornamento_fallito_torna_indietro_e_ferma_le_altre(ambiente, monkeypatch):
    for s in ("prova", "rossi", "bianchi"):
        flotta.main(_argomenti(s))
    ambiente.clear()
    risposte = iter([False, True])
    monkeypatch.setattr(flotta, "in_salute", lambda dati, attesa=0: next(risposte))
    with pytest.raises(SystemExit, match="mi fermo su prova") as e:
        flotta.main(["aggiorna", "--tutte", "--versione", "2.0", "--prima", "prova"])
    assert "Non toccate: bianchi, rossi" in str(e.value)
    testi = _testi(ambiente)
    assert any("pg_restore" in t for t in testi) and not any("adabox_rossi" in t or "adabox_bianchi" in t for t in testi)
    d = flotta.leggi("prova")
    assert d["versione"] == "1.0" and d["storia"][-1]["esito"] == "ripristinata"


def test_se_i_container_non_partono_si_torna_indietro(ambiente, monkeypatch):
    flotta.main(_argomenti())
    originale = flotta.esegui
    fallito = []

    def esegui(comando, entrata=None, uscita=None, ambiente=None, controlla=True):
        if "up" in comando and ambiente["VERSIONE"] == "2.0":
            fallito.append(comando)
            raise flotta.Errore("dependency failed to start")
        return originale(comando, entrata, uscita, ambiente, controlla)
    monkeypatch.setattr(flotta, "esegui", esegui)
    with pytest.raises(SystemExit, match="mi fermo su rossi"):
        flotta.main(["aggiorna", "rossi", "--versione", "2.0"])
    d = flotta.leggi("rossi")
    assert fallito and d["versione"] == "1.0" and d["storia"][-1]["esito"] == "ripristinata"
    assert any("pg_restore" in t for t in _testi(ambiente))


def test_i_moduli_si_scaricano_da_web_non_dal_worker(ambiente):
    flotta.main(_argomenti())
    assert " web python manage.py licenza sincronizza" in next(t for t in _testi(ambiente) if "licenza sincronizza" in t)


def test_stessa_versione_non_fa_nulla(ambiente):
    flotta.main(_argomenti())
    ambiente.clear()
    flotta.main(["aggiorna", "rossi", "--versione", "1.0"])
    assert not [t for t in _testi(ambiente) if "pg_dump" in t or "up -d" in t]


def test_backup_vuoto_e_un_errore(ambiente, monkeypatch):
    flotta.main(_argomenti())

    def vuoto(comando, entrata=None, uscita=None, ambiente=None, controlla=True):
        if uscita:
            Path(uscita).write_bytes(b"")
        return ""
    monkeypatch.setattr(flotta, "esegui", vuoto)
    with pytest.raises(SystemExit, match="backup vuoto"):
        flotta.main(["backup", "rossi"])


def test_i_backup_vecchi_si_tolgono_e_sono_protetti(ambiente, monkeypatch):
    flotta.main(_argomenti())
    monkeypatch.setattr(flotta, "BACKUP_DA_TENERE", 2)
    cartella = flotta.cartella("rossi") / "backup"
    for i in range(3):
        (cartella / f"2020010{i}-000000-x.dump").write_bytes(b"d")
        (cartella / f"2020010{i}-000000-x.file.tgz").write_bytes(b"d")
    flotta.main(["backup", "rossi"])
    dump = sorted(cartella.glob("*.dump"))
    assert len(dump) == 2 and len(list(cartella.glob("*.file.tgz"))) == 2 and stat.S_IMODE(dump[-1].stat().st_mode) == 0o600


def test_eliminare_chiede_conferma_e_tiene_il_salvataggio(ambiente):
    flotta.main(_argomenti())
    ambiente.clear()
    with pytest.raises(SystemExit, match="--conferma rossi"):
        flotta.main(["elimina", "rossi", "--conferma", "altro"])
    assert not ambiente
    flotta.main(["elimina", "rossi", "--conferma", "rossi"])
    testi = _testi(ambiente)
    assert any("pg_dump" in t for t in testi) and any("down -v" in t for t in testi) and any("revoca --codice cod-1" in t for t in testi)
    assert list((flotta.cartella("rossi") / "backup").glob("*.dump")) and not (flotta.cartella("rossi") / ".env").exists()
    assert "rossi" not in flotta.tutte()


def test_se_il_salvataggio_fallisce_non_elimina(ambiente, monkeypatch):
    flotta.main(_argomenti())

    def rotto(comando, entrata=None, uscita=None, ambiente=None, controlla=True):
        raise flotta.Errore("giù")
    monkeypatch.setattr(flotta, "esegui", rotto)
    with pytest.raises(SystemExit, match="non elimino"):
        flotta.main(["elimina", "rossi", "--conferma", "rossi"])
    assert (flotta.cartella("rossi") / ".env").exists()


def test_frammento_del_proxy():
    testo = flotta.frammento_proxy({"dominio": "hub.rossi.it", "porta": 8201})
    assert "hub.rossi.it" in testo and "127.0.0.1:8201" in testo and "X-Forwarded-Proto https" in testo


def test_il_compose_non_espone_le_porte_all_esterno():
    testo = flotta.COMPOSE.read_text()
    assert '"127.0.0.1:${PORTA' in testo and "5432:" not in testo


def test_il_proxy_https_arriva_a_django():
    testo = (flotta.REPO / "deploy" / "nginx.conf").read_text()
    assert "X-Forwarded-Proto $protocollo" in testo and "X-Forwarded-Proto $scheme" not in testo


@pytest.mark.django_db
def test_salute(client, monkeypatch):
    r = client.get("/salute/")
    assert r.status_code == 200 and r.json() == {"stato": "ok"}
    from django.db import connection

    def rotto():
        raise DatabaseError("giù")
    monkeypatch.setattr(connection, "ensure_connection", rotto)
    r = client.get("/salute/")
    assert r.status_code == 503 and "giù" not in r.content.decode()


@pytest.mark.django_db
def test_primo_admin_e_non_tocca_chi_esiste():
    uscita = StringIO()
    call_command("primo_admin", "--email", "a@rossi.it", "--azienda", "Rossi Srl", stdout=uscita)
    u = User.objects.get(email="a@rossi.it")
    password = uscita.getvalue().split("PASSWORD=")[1].strip()
    assert u.check_password(password) and not u.is_superuser and u.profilo.ruolo == Ruolo.objects.get(nome="Admin")
    assert Azienda.objects.order_by("pk").first().nome == "Rossi Srl" and u.profilo.azienda_predefinita.nome == "Rossi Srl"
    uscita = StringIO()
    call_command("primo_admin", "--email", "altro@rossi.it", stdout=uscita)
    assert "PASSWORD" not in uscita.getvalue() and not User.objects.filter(email="altro@rossi.it").exists()


@pytest.mark.django_db
def test_rivendita_istanza(settings, tmp_path):
    from core.registry import pacchetti
    from rivendita.models import Istanza, ModuloVendibile, Piano
    privata, _ = pacchetti.genera_chiavi()
    chiave = tmp_path / "k.pem"
    chiave.write_bytes(privata)
    settings.MODULI_CHIAVE_PRIVATA = str(chiave)
    Piano.objects.create(nome="Base", prezzo_mese=10)
    with pytest.raises(CommandError, match="inesistente"):
        call_command("rivendita_istanza", "crea", "--cliente", "X", "--piano", "Nessuno", "--scadenza", "2030-01-01")
    with pytest.raises(CommandError, match="non in vendita"):
        call_command("rivendita_istanza", "crea", "--cliente", "X", "--piano", "Base", "--scadenza", "2030-01-01", "--moduli", "boh")
    uscita = StringIO()
    call_command("rivendita_istanza", "crea", "--cliente", "Rossi", "--piano", "Base", "--scadenza", "2030-01-01", stdout=uscita)
    dati = json.loads(uscita.getvalue())
    i = Istanza.objects.get(codice=dati["codice"])
    assert Istanza.per_token(dati["token"]) == i and i.ospitata and dati["chiave_pubblica"] and ModuloVendibile
    call_command("rivendita_istanza", "revoca", "--codice", dati["codice"], stdout=StringIO())
    assert Istanza.per_token(dati["token"]) is None
