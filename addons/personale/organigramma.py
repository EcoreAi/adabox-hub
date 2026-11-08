"""Organigramma: l'albero disegnato dalla catena dei responsabili, e le posizioni con organico scoperto."""
from dataclasses import dataclass, field

from .models import Posizione


@dataclass
class Nodo:
    dipendente: object
    figli: list = field(default_factory=list)

    @property
    def sotto(self):
        """Quante persone ci sono sotto, a tutti i livelli."""
        return sum(1 + f.sotto for f in self.figli)


def albero(dipendenti):
    """[Nodo] radice dai dipendenti dati: in cima chi non ha un responsabile tra loro. Un giro nella catena
    (dati vecchi o importati) non blocca la pagina: chi resta fuori va in cima."""
    persone = {d.pk: d for d in dipendenti}
    nodi = {pk: Nodo(d) for pk, d in persone.items()}
    for pk, d in persone.items():
        if d.responsabile_id in nodi and d.responsabile_id != pk:
            nodi[d.responsabile_id].figli.append(nodi[pk])
    radici = [nodi[pk] for pk, d in persone.items() if d.responsabile_id not in nodi or d.responsabile_id == pk]
    raggiunti = set()

    def visita(n):
        raggiunti.add(n.dipendente.pk)
        n.figli = [f for f in n.figli if f.dipendente.pk not in raggiunti]
        for f in n.figli:
            visita(f)
    for r in radici:
        visita(r)
    for pk in persone:                                          # i giri: il primo di ognuno va in cima
        if pk not in raggiunti:
            nodi[pk].figli = [f for f in nodi[pk].figli if f.dipendente.pk not in raggiunti and f.dipendente.pk != pk]
            radici.append(nodi[pk])
            visita(nodi[pk])
    ordina = lambda lista: sorted(lista, key=lambda n: (-n.sotto, str(n.dipendente)))   # noqa: E731
    for n in nodi.values():
        n.figli = ordina(n.figli)
    return ordina(radici)


def scoperte(azienda, reparto=None):
    """[(posizione, occupati, mancano)] delle posizioni attive con meno persone dell'organico previsto."""
    qs = Posizione.objects.filter(azienda=azienda, attiva=True).select_related("reparto")
    if reparto is not None:
        qs = qs.filter(reparto=reparto)
    risultato = []
    for p in qs:
        occupati = p.occupati()
        if occupati < p.organico:
            risultato.append((p, occupati, p.organico - occupati))
    return risultato
