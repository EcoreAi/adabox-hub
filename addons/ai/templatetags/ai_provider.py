from django import template

from core import cifratura

register = template.Library()


@register.simple_tag
def provider_scheda(provider, utente=None):
    try:
        chiave = cifratura.mascherato(cifratura.decifra(provider.chiave_cifrata)) if provider.chiave_cifrata else "nessuna"
    except cifratura.SegretoIlleggibile:
        chiave = "illeggibile: inseriscila di nuovo con «Modifica»"
    modelli = list(provider.modelli.order_by("-attivo", "etichetta"))
    from ..catalogo_remoto import CON_CATALOGO
    return {"chiave": chiave, "modelli": modelli, "con_catalogo": provider.tipo in CON_CATALOGO,
            "senza_prezzo": any(m.prezzo_input is None or m.prezzo_output is None for m in modelli),
            "modificabile": not provider.gestito or bool(getattr(utente, "is_superuser", False))}
