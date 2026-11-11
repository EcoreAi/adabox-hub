"""Le sezioni del portale: ogni app registra la sua (nel ready(), se il portale è installato) e il portale le mostra
nella testata e in home. Il cliente vede solo i documenti del suo cliente (AccessoPortale.contatti()).

    from portale import sezioni
    sezioni.registra("fatture", "Fatture", "fatturazione:portale_fatture", ordine=30,
                     riepilogo="fatturazione.portale.riepilogo", attive=["portale_fatture"])

`riepilogo(accesso)` restituisce {"conta": int, "nota": str, "voci": [(titolo, url, nota)]} per la scheda in home.
`visibile(accesso)` (facoltativo) dice se la sezione c'è per quel cliente (es. l'assistente, solo se configurato)."""
from django.urls import NoReverseMatch, reverse
from django.utils.module_loading import import_string

_sezioni = {}


def registra(chiave, titolo, url_name, ordine=100, riepilogo=None, attive=(), visibile=None):
    _sezioni[chiave] = {"chiave": chiave, "titolo": titolo, "url_name": url_name, "ordine": ordine, "riepilogo": riepilogo,
                        "attive": set(attive) | {url_name.split(":")[-1]}, "visibile": visibile}


def per(accesso, con_riepilogo=False):
    """Le sezioni dei moduli installati e accesi, in ordine; con il riepilogo per la home."""
    from core.registry.modules import disattivati
    spenti = disattivati()
    uscita = []
    for s in sorted(_sezioni.values(), key=lambda v: (v["ordine"], v["titolo"])):
        if s["url_name"].split(":")[0] in spenti:
            continue
        if s["visibile"] and accesso is not None:
            try:
                if not import_string(s["visibile"])(accesso):
                    continue
            except Exception:                              # noqa: BLE001 - nel dubbio la sezione non si mostra
                import logging
                logging.getLogger("portale").exception("visibilità della sezione %s", s["chiave"])
                continue
        try:
            url = reverse(s["url_name"])
        except NoReverseMatch:
            continue
        voce = {**s, "url": url}
        if con_riepilogo and s["riepilogo"]:
            try:
                voce["dati"] = import_string(s["riepilogo"])(accesso)
            except Exception:                              # noqa: BLE001 - una sezione rotta non spegne la home
                import logging
                logging.getLogger("portale").exception("riepilogo della sezione %s", s["chiave"])
        uscita.append(voce)
    return uscita
