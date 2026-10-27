"""Azienda corrente: dalla sessione se consentita, altrimenti la predefinita del profilo."""
CHIAVE_SESSIONE = "azienda_id"


def consentite(user):
    if not user.is_authenticated:
        return []
    profilo = getattr(user, "profilo", None)
    return list(profilo.aziende.filter(attiva=True)) if profilo else []


def corrente(request):
    aziende = consentite(request.user)
    if not aziende:
        return None
    pk = request.session.get(CHIAVE_SESSIONE)
    for a in aziende:
        if a.pk == pk:
            return a
    predefinita = request.user.profilo.azienda_predefinita
    return predefinita if predefinita in aziende else aziende[0]
