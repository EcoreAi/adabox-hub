"""Dashboard fatte da Ada: una frase, una conferma, una pagina di Analisi con indicatori e grafici veri."""
import pytest
from django.contrib.auth.models import User

from ai import strumenti
from ai.strumenti import ErroreStrumento
from fatturazione.tests.test_fatturazione import _fattura, scena  # noqa: F401  (fixture)
from grafici import ai as strumenti_analisi
from grafici.models import Grafico, Pagina

KPI_FATTURATO = {"tipo": "kpi", "misura_aziendale": "fatturazione.fatturato", "periodo": "mese"}
KPI_SCADUTO = {"tipo": "kpi", "misura_aziendale": "fatturazione.scaduto"}
PER_CLIENTE = {"tipo": "torta", "misura_aziendale": "fatturazione.fatturato", "per": "cliente", "titolo": "Fatturato per cliente"}
PER_MESE = {"tipo": "barre", "misura_aziendale": "fatturazione.fatturato", "per": "mese", "periodo": "trimestre"}
SCADUTO_PER_CLIENTE = {"tipo": "barre", "misura_aziendale": "fatturazione.scaduto", "per": "cliente",
                       "titolo": "Scaduto per cliente"}


@pytest.fixture
def contesto(scena):
    azienda, cliente, monitor, _ = scena
    _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")
    return strumenti.Contesto(utente=User.objects.create_superuser("capo", "capo@example.com", "x"), azienda=azienda)


def test_dashboard_con_un_colpo(contesto):
    pezzi = [PER_CLIENTE, KPI_FATTURATO, PER_MESE, KPI_SCADUTO]
    anteprima = strumenti_analisi.anteprima_crea_dashboard(contesto, "Vendite", pezzi)
    assert "Vendite" in anteprima["titolo"] and len([d for d in anteprima["dettagli"] if d["campo"] not in ("Tolti", "Dove")]) == 4
    r = strumenti_analisi.crea_dashboard(contesto, "Vendite", pezzi)
    p = Pagina.objects.get(pk=r["pagina"])
    assert p.titolo == "Vendite" and p.utente == contesto.utente and r["url"]
    grafici = {g.pk: g for g in Grafico.objects.filter(pk__in=r["grafici"])}
    assert len(grafici) == 4 and all(g.origine == Grafico.CHAT and g.dati for g in grafici.values())
    voci = p.layout["widget"]
    tipi = [grafici[int(v["id"][2:])].tipo for v in voci]
    assert tipi == ["kpi", "kpi", "torta", "barre"]                       # prima gli indicatori, poi l'ordine di Ada
    assert [v["w"] for v in voci] == [1, 1, 2, 2]
    torta = next(g for g in grafici.values() if g.tipo == "torta")
    assert torta.spec["periodo"] == "anno" and torta.titolo == "Fatturato per cliente"
    assert next(g for g in grafici.values() if g.tipo == "barre").spec["periodo"] == "trimestre"


def test_grafico_vuoto_tolto_kpi_a_zero_resta(contesto):
    pezzi = [KPI_SCADUTO, SCADUTO_PER_CLIENTE, PER_CLIENTE]
    anteprima = strumenti_analisi.anteprima_crea_dashboard(contesto, "Incassi", pezzi)
    tolti = [d["dopo"] for d in anteprima["dettagli"] if d["campo"] == "Tolti"]
    assert len(tolti) == 1 and "Scaduto per cliente" in tolti[0] and "nessun dato" in tolti[0]
    r = strumenti_analisi.crea_dashboard(contesto, "Incassi", pezzi)
    assert sorted(Grafico.objects.filter(pk__in=r["grafici"]).values_list("tipo", flat=True)) == ["kpi", "torta"]
    assert "Scaduto per cliente" in r["esito"]                             # Ada sa dire che cosa ha tolto


def test_pezzo_sbagliato_tolto_con_il_motivo(contesto):
    pezzi = [KPI_FATTURATO, PER_CLIENTE, {"tipo": "barre", "misura_aziendale": "nessuna.misura", "per": "cliente"}]
    anteprima = strumenti_analisi.anteprima_crea_dashboard(contesto, "Prova", pezzi)
    assert any(d["campo"] == "Tolti" and "nessuna.misura" in d["dopo"] for d in anteprima["dettagli"])
    assert len(strumenti_analisi.crea_dashboard(contesto, "Prova", pezzi)["grafici"]) == 2


def test_meno_di_due_pezzi_niente_dashboard(contesto):
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Vuota", [KPI_FATTURATO, SCADUTO_PER_CLIENTE])
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.crea_dashboard(contesto, "Vuota", [KPI_FATTURATO, SCADUTO_PER_CLIENTE])
    assert not Pagina.objects.filter(titolo="Vuota").exists() and not Grafico.objects.exists()


def test_titolo_gia_usato(contesto):
    Pagina.objects.create(utente=contesto.utente, titolo="Vendite")
    with pytest.raises(ErroreStrumento, match="esiste già"):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "vendite", [KPI_FATTURATO, PER_CLIENTE])


def test_piu_di_otto_pezzi(contesto):
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Troppi", [KPI_FATTURATO] * 9)


def test_pezzi_non_lista(contesto):
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Testo", '[{"tipo": "kpi"}]')
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Testo", [KPI_FATTURATO, "fatturato"])


def test_composizioni_solo_misure_installate(db, monkeypatch):
    from core import misure
    testo = strumenti_analisi.testo_composizioni()
    assert "- Vendite:" in testo and "vendite.ordinato" in testo and "fatturazione.scaduto" in testo
    senza_vendite = [m for m in misure.tutte() if not m.nome.startswith("vendite.")]
    monkeypatch.setattr(misure, "tutte", lambda: senza_vendite)
    testo = strumenti_analisi.testo_composizioni()
    assert "- Vendite:" not in testo and "vendite." not in testo            # modulo non installato: niente traccia
    assert "- Fatturazione e incassi:" in testo


def test_strumento_registrato_con_le_composizioni(db):
    from ai.strumenti.registro import _registro
    s = _registro["analisi_crea_dashboard"]
    d = s.definizione()
    assert "Vendite:" in d["descrizione"] and s.rischio == "scrittura" and s.anteprima is not None
    pezzi = d["schema"]["properties"]["pezzi"]
    assert pezzi["type"] == "array" and pezzi["maxItems"] == 8 and pezzi["minItems"] == 2
    assert "misura_aziendale" in pezzi["items"]["properties"] and "pagina" not in pezzi["items"]["properties"]
    assert d["schema"]["required"] == ["titolo", "pezzi"]


def test_scheda_dell_app_non_blocca_il_titolo(contesto):
    Pagina.objects.create(utente=contesto.utente, titolo="Fatturazione", app="fatturazione")
    r = strumenti_analisi.crea_dashboard(contesto, "Fatturazione", [KPI_FATTURATO, PER_CLIENTE])
    assert Pagina.objects.get(pk=r["pagina"]).app == ""


def test_grafico_a_somma_zero_tolto(contesto, scena):
    """Una fattura e una nota di credito uguali: la serie ha il cliente ma a zero, la card sarebbe vuota."""
    azienda, cliente, monitor, _ = scena
    altro = cliente.__class__.objects.create(azienda=azienda, nome="Bianchi Spa", cliente=True)
    _fattura(azienda, altro, [(monitor, "1")], stato="emessa")
    _fattura(azienda, altro, [(monitor, "1")], stato="emessa", tipo="TD04")
    validi, tolti = strumenti_analisi.prepara_pezzi(contesto, [{**PER_CLIENTE, "filtri": None}])
    assert len(validi) == 1 and not tolti                                 # Rossi c'è: il grafico resta
    assert strumenti_analisi._vuoto("barre", {"serie": [("Bianchi Spa", 0)]})
    assert not strumenti_analisi._vuoto("kpi", {"valore": 0}) and strumenti_analisi._vuoto("kpi", {"valore": None})


def test_grafico_per_cliente_mostra_i_primi(contesto):
    validi, _ = strumenti_analisi.prepara_pezzi(contesto, [PER_CLIENTE, {**PER_MESE, "titolo": "mese"},
                                                           {**PER_CLIENTE, "titolo": "cinque", "primi": 5}])
    per_titolo = {v["titolo"]: v["spec"] for v in validi}
    assert per_titolo["Fatturato per cliente"]["primi"] == 10 and per_titolo["cinque"]["primi"] == 5
    assert "primi" not in per_titolo["mese"]                             # per mese: tutti i mesi


def test_anche_nelle_chat_di_un_app(contesto, monkeypatch):
    """Nella chat limitata al CRM «fammi una dashboard» deve funzionare: Analisi raccoglie i numeri di tutte le app."""
    from ai.strumenti.registro import _registro, disponibili
    for nome, s in _registro.items():                # come li carica ai.strumenti.app in produzione: dell'app grafici
        if nome.startswith("analisi_"):
            monkeypatch.setattr(s, "app", "grafici")
    nomi = {s.nome for s in disponibili(contesto.utente, "crm", contesto.azienda)}
    assert {"analisi_crea_dashboard", "analisi_salva_grafico"} <= nomi
    assert "analisi_crea_pagina" not in nomi                              # gli altri strumenti di Analisi restano fuori


# ---------- caselle di spunta nella scheda di conferma: si tolgono pezzi prima di confermare ----------

def _proposta(contesto, pezzi):
    from ai import proposte
    from ai.models import Conversazione, Proposta
    from ai.strumenti.registro import _registro
    contesto.conversazione = Conversazione.objects.create(utente=contesto.utente, titolo="Dashboard")
    proposte.prepara(_registro["analisi_crea_dashboard"], contesto, {"titolo": "Vendite", "pezzi": pezzi})
    return Proposta.objects.get()


def test_scheda_con_una_casella_per_pezzo(contesto):
    p = _proposta(contesto, [PER_CLIENTE, KPI_FATTURATO, SCADUTO_PER_CLIENTE])
    voci = [d.get("voce") for d in p.dettagli]
    assert voci[:2] == [1, 0]                      # KPI in testa: la casella porta l'indice del pezzo chiesto da Ada
    assert all(v is None for v in voci[2:])        # «Tolti» e «Dove» senza casella


def test_conferma_solo_i_pezzi_spuntati(contesto):
    from ai import proposte
    p = _proposta(contesto, [KPI_FATTURATO, PER_CLIENTE, PER_MESE, KPI_SCADUTO])
    proposte.conferma(p, contesto.utente, contesto.azienda, tieni={0, 2})
    p.refresh_from_db()
    assert p.stato == "eseguita"
    assert sorted(Grafico.objects.values_list("tipo", flat=True)) == ["barre", "kpi"]
    assert len(p.argomenti["pezzi"]) == 2 and "2 pezzi" in p.titolo   # la scheda dice che cosa è stato creato
    assert len([d for d in p.dettagli if d.get("voce") is not None]) == 2


def test_troppo_pochi_spuntati_resta_da_confermare(contesto):
    from ai import proposte
    p = _proposta(contesto, [KPI_FATTURATO, PER_CLIENTE, PER_MESE])
    with pytest.raises(ErroreStrumento, match="almeno 2"):
        proposte.conferma(p, contesto.utente, contesto.azienda, tieni={1})
    p.refresh_from_db()
    assert p.stato == "in_attesa" and len(p.argomenti["pezzi"]) == 3 and not Grafico.objects.exists()


def test_scheda_html_e_conferma_dal_bottone(contesto, client):
    p = _proposta(contesto, [KPI_FATTURATO, PER_CLIENTE, PER_MESE])
    from django.template.loader import render_to_string
    client.force_login(contesto.utente)
    html = render_to_string("ai/_proposta.html", {"p": p})
    assert html.count('name="voce"') == 3 and 'name="voci_scelte"' in html and 'value="0" checked' in html
    assert f'form="ai-proposta-{p.pk}-conferma"' in html and f'id="ai-proposta-{p.pk}-conferma"' in html
    r = client.post(f"/ai/proposta/{p.pk}/conferma/", {"voci_scelte": "1", "voce": ["0", "1"]}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and Grafico.objects.count() == 2
    assert 'name="voce"' not in r.content.decode()                       # eseguita: niente più caselle
    p2 = _proposta_altra(contesto, p)
    r = client.post(f"/ai/proposta/{p2.pk}/conferma/", {"voci_scelte": "1", "voce": ["2"]}, HTTP_HX_REQUEST="true")
    assert "almeno 2" in r.content.decode()                               # l'errore nella scheda, che resta lì


def _proposta_altra(contesto, p):
    from ai import proposte
    from ai.models import Proposta
    from ai.strumenti.registro import _registro
    proposte.prepara(_registro["analisi_crea_dashboard"], contesto, {"titolo": "Altra", "pezzi": [KPI_FATTURATO, PER_CLIENTE, PER_MESE]})
    return Proposta.objects.exclude(pk=p.pk).get()


def test_conferma_senza_scelta_crea_tutto(contesto):
    """Da un canale senza caselle (o una scheda vecchia) la conferma crea tutti i pezzi, come prima."""
    from ai import proposte
    p = _proposta(contesto, [KPI_FATTURATO, PER_CLIENTE, PER_MESE])
    proposte.conferma(p, contesto.utente, contesto.azienda)
    assert Grafico.objects.count() == 3
