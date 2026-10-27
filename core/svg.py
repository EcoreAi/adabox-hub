"""Grafici in SVG generati dal server: barre, linee, torta. Niente librerie JS."""
import math
from html import escape

PALETTE = ["#1e3a8a", "#2f80ed", "#34c759", "#ff9f0a", "#ff3b30", "#5856d6", "#00a3a3", "#8e8e93"]
TESTO, GRIGLIA, ASSE = "#6e6e73", "#e5e5ea", "#c7c7cc"


def _svg(larghezza, altezza, titolo, corpo):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {larghezza} {altezza}" role="img" '
            f'class="ui-grafico-svg" font-family="inherit" font-size="12"><title>{escape(titolo)}</title>{corpo}</svg>')


def _scala(massimo):
    """Massimo arrotondato e passo della griglia (4 righe), numeri 'tondi'."""
    if massimo <= 0:
        return 1, 0.25
    grezzo = massimo / 4
    potenza = 10 ** math.floor(math.log10(grezzo))
    passo = next(m * potenza for m in (1, 2, 2.5, 5, 10) if m * potenza >= grezzo)
    return passo * 4, passo


def _fmt(v):
    return f"{v:,.0f}".replace(",", ".") if float(v).is_integer() else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _assi(dati, larghezza, altezza, titolo, disegna):
    sx, dx, su, giu = 56, 16, 16, 70 if len(dati) > 8 else 36
    w, h = larghezza - sx - dx, altezza - su - giu
    massimo, passo = _scala(max((float(v) for _, v in dati), default=0))
    parti = []
    for i in range(5):
        y = su + h - h * (i * passo) / massimo
        parti.append(f'<line x1="{sx}" y1="{y:.1f}" x2="{sx + w}" y2="{y:.1f}" stroke="{GRIGLIA}"/>'
                     f'<text x="{sx - 8}" y="{y + 4:.1f}" text-anchor="end" fill="{TESTO}">{_fmt(i * passo)}</text>')
    passo_x = w / max(len(dati), 1)
    for i, (etichetta, _) in enumerate(dati):
        x = sx + passo_x * (i + 0.5)
        if len(dati) > 8:
            parti.append(f'<text x="{x:.1f}" y="{su + h + 12}" text-anchor="end" fill="{TESTO}" '
                         f'transform="rotate(-40 {x:.1f} {su + h + 12})">{escape(str(etichetta))[:24]}</text>')
        else:
            parti.append(f'<text x="{x:.1f}" y="{su + h + 20}" text-anchor="middle" fill="{TESTO}">{escape(str(etichetta))[:24]}</text>')
    parti.append(f'<line x1="{sx}" y1="{su + h}" x2="{sx + w}" y2="{su + h}" stroke="{ASSE}"/>')
    parti.append(disegna(sx, su, w, h, massimo, passo_x))
    return _svg(larghezza, altezza, titolo, "".join(parti))


def barre(dati, titolo="", larghezza=720, altezza=320):
    def disegna(sx, su, w, h, massimo, passo_x):
        out = []
        for i, (etichetta, v) in enumerate(dati):
            alto = h * float(v) / massimo
            x = sx + passo_x * i + passo_x * 0.15
            out.append(f'<rect x="{x:.1f}" y="{su + h - alto:.1f}" width="{passo_x * 0.7:.1f}" height="{alto:.1f}" '
                       f'rx="3" fill="{PALETTE[0]}"><title>{escape(str(etichetta))}: {_fmt(float(v))}</title></rect>')
            if len(dati) <= 15:
                out.append(f'<text x="{x + passo_x * 0.35:.1f}" y="{su + h - alto - 6:.1f}" text-anchor="middle" '
                           f'fill="#1d1d1f">{_fmt(float(v))}</text>')
        return "".join(out)
    return _assi(dati, larghezza, altezza, titolo, disegna)


def linee(dati, titolo="", larghezza=720, altezza=320):
    def disegna(sx, su, w, h, massimo, passo_x):
        punti = [(sx + passo_x * (i + 0.5), su + h - h * float(v) / massimo) for i, (_, v) in enumerate(dati)]
        out = [f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in punti)}" fill="none" '
               f'stroke="{PALETTE[1]}" stroke-width="2.5" stroke-linejoin="round"/>'] if punti else []
        for (x, y), (etichetta, v) in zip(punti, dati):
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{PALETTE[1]}">'
                       f'<title>{escape(str(etichetta))}: {_fmt(float(v))}</title></circle>')
        return "".join(out)
    return _assi(dati, larghezza, altezza, titolo, disegna)


def torta(dati, titolo="", larghezza=720, altezza=320):
    totale = sum(float(v) for _, v in dati)
    cx, cy, r = 160, altezza / 2, min(140, altezza / 2 - 10)
    parti = []
    if totale <= 0:
        parti.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{GRIGLIA}"/>')
    angolo = -math.pi / 2
    for i, (etichetta, v) in enumerate(dati):
        quota = float(v) / totale if totale else 0
        colore = PALETTE[i % len(PALETTE)]
        if quota >= 0.9999:
            parti.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{colore}"><title>{escape(str(etichetta))}</title></circle>')
        elif quota > 0:
            fine = angolo + 2 * math.pi * quota
            x1, y1 = cx + r * math.cos(angolo), cy + r * math.sin(angolo)
            x2, y2 = cx + r * math.cos(fine), cy + r * math.sin(fine)
            grande = 1 if quota > 0.5 else 0
            parti.append(f'<path d="M{cx},{cy} L{x1:.2f},{y1:.2f} A{r},{r} 0 {grande} 1 {x2:.2f},{y2:.2f} Z" '
                         f'fill="{colore}" stroke="#fff" stroke-width="1.5"><title>{escape(str(etichetta))}: '
                         f'{_fmt(float(v))}</title></path>')
            angolo = fine
        y = 30 + i * 22
        if y < altezza - 10:
            percentuale = f"{quota * 100:.0f}%" if totale else "0%"
            parti.append(f'<rect x="340" y="{y - 10}" width="12" height="12" rx="2" fill="{colore}"/>'
                         f'<text x="360" y="{y}" fill="#1d1d1f">{escape(str(etichetta))[:30]} '
                         f'<tspan fill="{TESTO}">{_fmt(float(v))} · {percentuale}</tspan></text>')
    return _svg(larghezza, altezza, titolo, "".join(parti))


DISEGNI = {"barre": barre, "linee": linee, "torta": torta}
