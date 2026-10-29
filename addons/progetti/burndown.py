"""Burndown dello sprint in SVG: punti rimasti giorno per giorno e retta ideale."""
from html import escape

from django.utils.safestring import mark_safe

from core import svg


def disegna(sprint, oggi=None):
    reale, ideale = sprint.burndown(oggi)
    if not ideale:
        return ""
    dati = [(g.strftime("%d/%m"), v) for g, v in ideale]
    valori_reali = [v for _, v in reale]

    def linee(sx, su, w, h, massimo, passo_x):
        def punti(valori):
            return " ".join(f"{sx + passo_x * (i + 0.5):.1f},{su + h - h * float(v) / massimo:.1f}"
                            for i, v in enumerate(valori))
        out = [f'<polyline points="{punti([v for _, v in dati])}" fill="none" stroke="{svg.ASSE}" '
               f'stroke-width="2" stroke-dasharray="6 5"><title>ideale</title></polyline>']
        if valori_reali:
            out.append(f'<polyline points="{punti(valori_reali)}" fill="none" stroke="{svg.PALETTE[1]}" '
                       f'stroke-width="2.5" stroke-linejoin="round"/>')
            for i, v in enumerate(valori_reali):
                out.append(f'<circle cx="{sx + passo_x * (i + 0.5):.1f}" cy="{su + h - h * float(v) / massimo:.1f}" '
                           f'r="3.5" fill="{svg.PALETTE[1]}"><title>{escape(dati[i][0])}: {v} punti</title></circle>')
        return "".join(out)
    return mark_safe(svg._assi(dati, 720, 300, f"Burndown di {sprint.nome}", linee))
