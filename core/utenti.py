"""Utenti, ruoli e dipartimenti: chi entra, con quale ruolo, in quali app lavora e che cosa può fare in ogni modulo, senza
passare dall'admin di Django."""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from . import dipartimenti, licenza, ruoli
from .models import Azienda, Dipartimento, DueFattori, Ruolo
from .signals import crea_profilo

User = get_user_model()
GESTIONE = "auth.change_user"
GESTIONE_RUOLI = "core.change_ruolo"
GESTIONE_DIPARTIMENTI = "core.change_dipartimento"


def _utenti(request):
    """I superutenti li vede e li tocca solo un superutente."""
    qs = User.objects.select_related("profilo", "profilo__ruolo").order_by("-is_active", "first_name", "last_name", "username")
    return qs if request.user.is_superuser else qs.filter(is_superuser=False)


def _utente(request, pk):
    return get_object_or_404(_utenti(request), pk=pk)


def _classi(form):
    for campo in form.fields.values():
        if not isinstance(campo.widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
            campo.widget.attrs.setdefault("class", "ui-input")
    return form


class UtenteForm(forms.ModelForm):
    ruolo = forms.ModelChoiceField(Ruolo.objects.all(), required=False, label="Ruolo", empty_label="Nessun ruolo: gruppi gestiti a mano")
    aziende = forms.ModelMultipleChoiceField(Azienda.objects.filter(attiva=True), required=False, label="Aziende", widget=forms.CheckboxSelectMultiple)
    dipartimenti = forms.ModelMultipleChoiceField(Dipartimento.objects.all(), required=False, label="Dipartimenti", widget=forms.CheckboxSelectMultiple,
                                                  help_text="Vede solo le app dei suoi dipartimenti e quelle comuni. Nessuno: tutte quelle che il ruolo consente.")
    invito = forms.BooleanField(required=False, initial=True, label="Mandagli l'email per scegliere la password")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "username", "is_active"]
        labels = {"first_name": "Nome", "last_name": "Cognome", "email": "Email", "username": "Nome utente", "is_active": "Attivo"}

    def __init__(self, *args, tecnico_ammesso=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not tecnico_ammesso:                      # il ruolo che rende superutente lo dà solo un superutente
            self.fields["ruolo"].queryset = Ruolo.objects.filter(tecnico=False)
        self.fields["email"].required = True
        self.fields["username"].required = False
        self.fields["username"].help_text = "Vuoto: la parte dell'email prima della chiocciola"
        _classi(self)

    def clean_is_active(self):
        attivo = self.cleaned_data.get("is_active")
        nuovo_attivo = attivo and not (self.instance.pk and User.objects.filter(pk=self.instance.pk, is_active=True).exists())
        if nuovo_attivo and licenza.posti_finiti():
            raise forms.ValidationError(f"La licenza copre {licenza.attuale().utenti} utenti attivi e sono già tutti occupati.")
        return attivo

    def clean(self):
        dati = super().clean()
        if "dipartimenti" in dati and not self.errors:
            attivo = bool(dati.get("is_active")) and not (self.instance.pk and self.instance.is_superuser)
            for errore in dipartimenti.oltre_il_tetto(utente_modificato=(self.instance.pk, [d.pk for d in dati["dipartimenti"]], attivo)):
                self.add_error("dipartimenti", errore)
        return dati

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("C'è già un utente con questa email.")
        return email

    def clean_username(self):
        nome = (self.cleaned_data.get("username") or "").strip() or (self.cleaned_data.get("email") or "").split("@")[0]
        if not nome:
            raise forms.ValidationError("Serve l'email, o un nome utente.")
        base, i = nome, 1
        while User.objects.filter(username__iexact=nome).exclude(pk=self.instance.pk).exists():
            i += 1
            nome = f"{base}{i}"
        return nome


class RuoloForm(forms.ModelForm):
    class Meta:
        model = Ruolo
        fields = ["nome", "descrizione", "livello_base", "amministra", "tecnico", "predefinito", "ordine"]

    def __init__(self, *args, tecnico_ammesso=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not tecnico_ammesso:
            del self.fields["tecnico"]
        _classi(self)


def _livelli_dal_post(request, prefisso="livello_"):
    """{slug: livello} dai campi del modulo; vuoto = come il ruolo (o come la base)."""
    ammessi = dict(ruoli.LIVELLI)
    return {slug: request.POST[f"{prefisso}{slug}"] for slug, _ in ruoli.moduli_gestibili()
            if request.POST.get(f"{prefisso}{slug}") in ammessi}


def invia_invito(utente):
    """L'email con il link per scegliere la password: lo stesso del «password dimenticata»."""
    sito = settings.SITO_URL
    contesto = {"user": utente, "site_name": settings.THEME.get("brand", "Adabox"), "protocol": sito.split("://")[0],
                "domain": sito.split("://", 1)[-1], "uid": urlsafe_base64_encode(force_bytes(utente.pk)),
                "token": default_token_generator.make_token(utente)}
    oggetto = "".join(render_to_string("registration/password_reset_subject.txt", contesto).splitlines())
    EmailMessage(oggetto, render_to_string("registration/password_reset_email.html", contesto), to=[utente.email]).send()


# ---------- utenti

@login_required
@permission_required(GESTIONE, raise_exception=True)
def lista(request):
    utenti = _utenti(request).prefetch_related("profilo__aziende", "profilo__dipartimenti")
    if request.GET.get("stato") != "tutti":
        utenti = utenti.filter(is_active=True)
    con_2fa = set(DueFattori.objects.filter(attiva_dal__isnull=False).values_list("utente_id", flat=True))
    righe = [{"u": u, "profilo": getattr(u, "profilo", None), "due_fattori": u.pk in con_2fa} for u in utenti]
    return render(request, "core/utenti/lista.html", {"righe": righe, "tutti": request.GET.get("stato") == "tutti",
                                                       "ruoli": Ruolo.objects.all(), "puo_ruoli": request.user.has_perm(GESTIONE_RUOLI),
                                                       "puo_dipartimenti": request.user.has_perm(GESTIONE_DIPARTIMENTI)})


def _righe_moduli(profilo, ruolo):
    righe = []
    consentite = dipartimenti.del_profilo(profilo)
    for slug, m in ruoli.moduli_gestibili():
        del_ruolo = (ruolo.livelli.get(slug, ruolo.livello_base) if ruolo else None)
        righe.append({"slug": slug, "nome": m.name, "del_ruolo": del_ruolo, "del_ruolo_testo": ruoli.ETICHETTE.get(del_ruolo, "—"),
                      "eccezione": (profilo.eccezioni if profilo else {}).get(slug, ""),
                      "fuori": not dipartimenti.dentro(slug, consentite)})
    return righe


@login_required
@permission_required(GESTIONE, raise_exception=True)
def scheda(request, pk=None):
    utente = _utente(request, pk) if pk else None
    profilo = crea_profilo(utente) if utente else None
    se_stesso = utente is not None and utente == request.user
    if request.method == "POST":
        form = UtenteForm(request.POST, instance=utente, tecnico_ammesso=request.user.is_superuser)
        if form.is_valid():
            with transaction.atomic():
                nuovo = utente is None
                utente = form.save(commit=False)
                if nuovo:
                    utente.set_unusable_password()
                if se_stesso:
                    utente.is_active = True                    # non ci si chiude fuori da soli
                utente.save()
                profilo = crea_profilo(utente)
                if not se_stesso:
                    profilo.ruolo = form.cleaned_data["ruolo"]
                profilo.eccezioni = _livelli_dal_post(request)
                aziende = list(form.cleaned_data["aziende"])
                profilo.aziende.set(aziende)
                profilo.dipartimenti.set(form.cleaned_data["dipartimenti"])
                if profilo.azienda_predefinita not in aziende:
                    profilo.azienda_predefinita = aziende[0] if aziende else None
                profilo.save()                                 # il segnale riallinea i gruppi
            if nuovo and form.cleaned_data["invito"]:
                try:
                    invia_invito(utente)
                    messages.success(request, f"{utente.get_full_name() or utente.username} creato: gli è arrivata l'email per scegliere la password.")
                except Exception:
                    messages.warning(request, f"{utente.username} creato, ma l'email non è partita: controlla la posta in uscita e rimanda l'invito dalla scheda.")
            else:
                messages.success(request, f"{utente.get_full_name() or utente.username} salvato." + (" Il tuo ruolo e lo stato attivo non si cambiano da soli." if se_stesso else ""))
            return redirect("core:utente", pk=utente.pk)
    else:
        iniziali = {"ruolo": profilo.ruolo_id if profilo else (ruoli.predefinito() or Ruolo.objects.filter(nome="Collaboratore").first()),
                    "aziende": list(profilo.aziende.all()) if profilo else list(Azienda.objects.filter(attiva=True)),
                    "dipartimenti": list(profilo.dipartimenti.all()) if profilo else []}
        form = UtenteForm(instance=utente, initial=iniziali, tecnico_ammesso=request.user.is_superuser)
    ruolo_scelto = profilo.ruolo if profilo else form.initial.get("ruolo")
    if isinstance(ruolo_scelto, int):
        ruolo_scelto = Ruolo.objects.filter(pk=ruolo_scelto).first()
    return render(request, "core/utenti/scheda.html", {
        "form": form, "utente": utente, "profilo": profilo, "se_stesso": se_stesso, "livelli": ruoli.LIVELLI,
        "moduli": _righe_moduli(profilo, ruolo_scelto), "ruoli": Ruolo.objects.all(),
        "livelli_ruoli": {r.pk: {slug: r.livelli.get(slug, r.livello_base) for slug, _ in ruoli.moduli_gestibili()} for r in Ruolo.objects.all()},
        "due_fattori": DueFattori.objects.filter(utente=utente, attiva_dal__isnull=False).exists() if utente else False,
        "gruppi": list(utente.groups.order_by("name").values_list("name", flat=True)) if utente else []})


@login_required
@permission_required(GESTIONE, raise_exception=True)
@require_POST
def invito(request, pk):
    utente = _utente(request, pk)
    if not utente.email:
        messages.error(request, "L'utente non ha un'email.")
    else:
        try:
            invia_invito(utente)
            messages.success(request, f"Email per la password mandata a {utente.email}.")
        except Exception:
            messages.error(request, "L'email non è partita: controlla la posta in uscita.")
    return redirect("core:utente", pk=pk)


@login_required
@permission_required(GESTIONE, raise_exception=True)
@require_POST
def due_fattori_azzera(request, pk):
    """Telefono e codici persi: via la verifica in due passaggi, l'utente rientra con la sola password e la riattiva."""
    utente = _utente(request, pk)
    DueFattori.objects.filter(utente=utente).delete()
    messages.success(request, f"Verifica in due passaggi azzerata per {utente.username}.")
    return redirect("core:utente", pk=pk)


@login_required
@permission_required(GESTIONE, raise_exception=True)
@require_POST
def livello(request, pk):
    """Una cella della matrice: l'eccezione di un utente in un modulo («ruolo» la toglie)."""
    utente = _utente(request, pk)
    slug, valore = request.POST.get("modulo", ""), request.POST.get("livello", "")
    moduli = dict(ruoli.moduli_gestibili(anche_spenti=True))
    if slug not in moduli or (valore != "ruolo" and valore not in ruoli.ETICHETTE):
        return HttpResponseBadRequest("modulo o livello non valido")
    profilo = crea_profilo(utente)
    if valore == "ruolo":
        profilo.eccezioni.pop(slug, None)
    else:
        profilo.eccezioni[slug] = valore
    profilo.save()
    return render(request, "core/utenti/_cella.html", {"u": utente, "cella": _cella(utente, profilo, slug, moduli[slug])})


def _cella(utente, profilo, slug, manifest, consentite=dipartimenti.NESSUN_LIMITE, calcola=True):
    """Il livello nella matrice. `consentite` le app dei suoi dipartimenti; con calcola=True si leggono qui."""
    if calcola:
        consentite = dipartimenti.del_profilo(profilo)
    liv, fuori = ruoli.livello_effettivo(profilo, slug, consentite)
    if liv is None:
        liv = ruoli.livello_dai_gruppi(set(utente.groups.values_list("name", flat=True)), manifest)
        if liv != ruoli.NESSUNO and not dipartimenti.dentro(slug, consentite, profilo.eccezioni):
            liv, fuori = ruoli.NESSUNO, True
    return {"slug": slug, "livello": liv, "testo": ruoli.ETICHETTE[liv], "eccezione": slug in profilo.eccezioni,
            "con_ruolo": profilo.ruolo_id is not None, "livelli": ruoli.LIVELLI, "fuori": fuori}


@login_required
@permission_required(GESTIONE, raise_exception=True)
def matrice(request):
    moduli = ruoli.moduli_gestibili()
    utenti = _utenti(request).filter(is_active=True).exclude(profilo__esterno=True).prefetch_related("groups")
    righe = []
    for u in utenti:
        profilo = crea_profilo(u)
        consentite = dipartimenti.del_profilo(profilo)
        righe.append({"u": u, "profilo": profilo, "celle": [_cella(u, profilo, slug, m, consentite, calcola=False) for slug, m in moduli]})
    return render(request, "core/utenti/matrice.html", {"moduli": moduli, "righe": righe})


# ---------- ruoli

@login_required
@permission_required(GESTIONE_RUOLI, raise_exception=True)
def ruoli_lista(request):
    nomi = {slug: m.name for slug, m in ruoli.moduli_gestibili()}
    righe = [{"r": r, "utenti": r.profili.count(), "base": ruoli.ETICHETTE[r.livello_base],
              "diversi": ", ".join(f"{nomi.get(s, s)}: {ruoli.ETICHETTE.get(l, l)}" for s, l in r.livelli.items())}
             for r in Ruolo.objects.all()]
    return render(request, "core/utenti/ruoli.html", {"righe": righe})


@login_required
@permission_required(GESTIONE_RUOLI, raise_exception=True)
def ruolo(request, pk=None):
    istanza = get_object_or_404(Ruolo, pk=pk) if pk else None
    if istanza is not None and istanza.tecnico and not request.user.is_superuser:
        raise PermissionDenied                       # un ruolo che rende superutente lo tocca solo un superutente
    if request.method == "POST":
        form = RuoloForm(request.POST, instance=istanza, tecnico_ammesso=request.user.is_superuser)
        if form.is_valid():
            with transaction.atomic():
                r = form.save(commit=False)
                r.livelli = _livelli_dal_post(request)
                if r.predefinito:
                    Ruolo.objects.exclude(pk=r.pk).update(predefinito=False)
                r.save()                                       # il segnale riallinea chi ha il ruolo
            messages.success(request, f"Ruolo «{r}» salvato: vale già per chi lo ha.")
            return redirect("core:ruolo", pk=r.pk)
    else:
        form = RuoloForm(instance=istanza, tecnico_ammesso=request.user.is_superuser)
    righe = [{"slug": slug, "nome": m.name, "livello": (istanza.livelli.get(slug, "") if istanza else "")} for slug, m in ruoli.moduli_gestibili()]
    return render(request, "core/utenti/ruolo.html", {"form": form, "ruolo": istanza, "moduli": righe, "livelli": ruoli.LIVELLI,
                                                       "utenti": istanza.profili.count() if istanza else 0})


@login_required
@permission_required("core.delete_ruolo", raise_exception=True)
@require_POST
def ruolo_elimina(request, pk):
    r = get_object_or_404(Ruolo, pk=pk)
    if r.profili.exists():
        messages.error(request, f"«{r}» è il ruolo di {r.profili.count()} utent{'e' if r.profili.count() == 1 else 'i'}: assegna loro un altro ruolo prima di eliminarlo.")
        return redirect("core:ruolo", pk=pk)
    r.delete()
    messages.success(request, f"Ruolo «{r}» eliminato.")
    return redirect("core:ruoli")


# ---------- dipartimenti

class DipartimentoForm(forms.ModelForm):
    class Meta:
        model = Dipartimento
        fields = ["nome", "descrizione", "responsabile", "tutte", "ordine"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["responsabile"].queryset = User.objects.filter(is_active=True).exclude(profilo__esterno=True).order_by("first_name", "last_name", "username")
        self.fields["responsabile"].empty_label = "Nessuno"
        _classi(self)


def _app_per_colonna(scelte):
    """Le app attive divise come nel menu «Altre», con la spunta su quelle scelte e il segno su quelle comuni."""
    from . import barra
    comuni = dipartimenti.comuni()
    voci = [{"slug": s, "label": m.nav_label or m.name, "categoria": m.category, "scelta": s in scelte, "comune": s in comuni}
            for s, m in dipartimenti.applicazioni().items()]
    return barra.gruppi(voci)


def _nomi_app(slugs):
    app = dipartimenti.applicazioni()
    return sorted((app[s].nav_label or app[s].name) for s in slugs if s in app)


@login_required
@permission_required(GESTIONE_DIPARTIMENTI, raise_exception=True)
def dipartimenti_lista(request):
    comuni = dipartimenti.comuni()
    posti = {r["slug"]: r for r in dipartimenti.posti_suite()}
    righe = []
    for d in Dipartimento.objects.prefetch_related("profili__utente"):
        righe.append({"d": d, "app": "Tutte" if d.tutte else ", ".join(_nomi_app(set(d.app) - comuni)) or "Solo le comuni",
                      "persone": [p.utente for p in d.profili.all() if p.utente.is_active], "posti": posti.get(d.suite)})
    return render(request, "core/utenti/dipartimenti.html", {
        "righe": righe, "comuni": _nomi_app(comuni),
        "senza": _utenti(request).filter(is_active=True, profilo__dipartimenti__isnull=True).exclude(profilo__esterno=True).count()})


@login_required
@permission_required(GESTIONE_DIPARTIMENTI, raise_exception=True)
def dipartimento(request, pk=None):
    istanza = get_object_or_404(Dipartimento, pk=pk) if pk else None
    persone = list(_utenti(request).filter(is_active=True).exclude(profilo__esterno=True))
    if request.method == "POST":
        form = DipartimentoForm(request.POST, instance=istanza)
        attive = dipartimenti.applicazioni()
        app = sorted(s for s in request.POST.getlist("app") if s in attive)
        membri = {u.pk for u in persone if str(u.pk) in request.POST.getlist("membri")}
        if form.is_valid():
            tutte = form.cleaned_data["tutte"]
            errori = dipartimenti.oltre_il_tetto(dip_modificato=(istanza.pk if istanza else None, app, tutte), membri_modificati=membri)
            for e in errori:
                form.add_error(None, e)
        if form.is_valid():
            with transaction.atomic():
                d = form.save(commit=False)
                fuori = set(d.app) - set(attive)                      # le app spente o non ancora arrivate restano
                d.app = sorted(set(app) | fuori)
                d.save()
                visibili = {u.pk for u in persone}
                restano = [p for p in d.profili.all() if p.utente_id not in visibili]   # i superutenti, per chi non li vede
                d.profili.set(restano + [crea_profilo(u) for u in persone if u.pk in membri])
            messages.success(request, f"Dipartimento «{d}» salvato: vale già per chi ne fa parte.")
            return redirect("core:dipartimento", pk=d.pk)
        scelte, membri_scelti = set(app), membri
    else:
        form = DipartimentoForm(instance=istanza)
        scelte = set(istanza.app) if istanza else set()
        membri_scelti = set(istanza.profili.values_list("utente_id", flat=True)) if istanza else set()
    portate = sorted(dipartimenti.con_dipendenze(scelte) - scelte - dipartimenti.comuni())
    posti = next((r for r in dipartimenti.posti_suite() if istanza and r["slug"] == istanza.suite), None)
    return render(request, "core/utenti/dipartimento.html", {
        "form": form, "dipartimento": istanza, "colonne": _app_per_colonna(scelte), "portate": _nomi_app(portate),
        "persone": [{"u": u, "scelta": u.pk in membri_scelti} for u in persone], "posti": posti})


@login_required
@permission_required("core.delete_dipartimento", raise_exception=True)
@require_POST
def dipartimento_elimina(request, pk):
    d = get_object_or_404(Dipartimento, pk=pk)
    nome = str(d)
    d.delete()                                        # il segnale riallinea chi ne faceva parte
    messages.success(request, f"Dipartimento «{nome}» eliminato: chi ne faceva parte segue gli altri suoi dipartimenti, o il solo ruolo.")
    return redirect("core:dipartimenti")
