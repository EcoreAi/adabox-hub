"""Pagine della 2FA: secondo passo dell'accesso e gestione dal profilo."""
import time

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.utils import timezone

from . import due_fattori as df2

ATTESA = "due_fattori_attesa"
CODICI_NUOVI = "due_fattori_codici"
MINUTI_ATTESA = 5


class Accedi(LoginView):
    """Password giusta e 2FA attiva: si passa alla pagina del codice, l'utente non è ancora collegato."""
    redirect_authenticated_user = True

    def form_valid(self, form):
        utente = form.get_user()
        df = df2.di(utente)
        if df is None or df.attiva_dal is None or df2.dispositivo_fidato(self.request, df):
            return super().form_valid(form)
        self.request.session[ATTESA] = {"u": utente.pk, "b": utente.backend, "t": time.time(),
                                        "next": self.get_success_url()}
        return redirect("due_fattori_accesso")


def accesso(request):
    attesa = request.session.get(ATTESA)
    if not attesa or time.time() - attesa["t"] > MINUTI_ATTESA * 60:
        request.session.pop(ATTESA, None)
        if attesa:
            messages.info(request, "È passato troppo tempo: accedi di nuovo.")
        return redirect("login")
    utente = get_user_model().objects.filter(pk=attesa["u"], is_active=True).first()
    df = df2.di(utente) if utente else None
    if df is None or df.attiva_dal is None:
        request.session.pop(ATTESA, None)
        return redirect("login")
    errore = None
    if request.method == "POST":
        esito = df2.verifica(df, request.POST.get("codice"))
        if esito:
            del request.session[ATTESA]
            login(request, utente, backend=attesa["b"])
            risposta = redirect(attesa["next"])
            if request.POST.get("ricorda"):
                df2.ricorda_dispositivo(risposta, df)
            if esito == "recupero":
                messages.warning(request, f"Hai usato un codice di recupero: te ne restano {len(df.codici_recupero)}.")
                df2.avvisa(utente, "Accesso con un codice di recupero", "Hai effettuato l'accesso con un codice di recupero.")
            return risposta
        errore = ("Troppi tentativi: riprova tra qualche minuto." if df2.bloccata(df)
                  else "Il codice non è corretto: controlla l'ora del telefono e riprova.")
    return render(request, "registration/due_fattori.html", {"errore": errore}, status=429 if df2.bloccata(df) else 200)


@login_required
def gestione(request):
    utente = request.user
    df = df2.di(utente)
    attiva = df is not None and df.attiva_dal is not None
    if request.method == "POST":
        azione = request.POST.get("azione")
        codice = request.POST.get("codice")
        if azione == "attiva" and not attiva:
            df = df2.prepara(utente)
            if df2.verifica(df, codice, recupero_ammesso=False):
                df.attiva_dal = timezone.now()
                df.save(update_fields=["attiva_dal"])
                request.session[CODICI_NUOVI] = df2.nuovi_codici(df)
                df2.avvisa(utente, "Verifica in due passaggi attivata", "La verifica in due passaggi è ora attiva sul tuo account.")
                messages.success(request, "Verifica in due passaggi attivata.")
            else:
                messages.error(request, "Il codice non è corretto: riprova con quello che vedi ora nell'app.")
        elif attiva and azione in ("disattiva", "rigenera"):
            if not utente.check_password(request.POST.get("password", "")):
                messages.error(request, "La password non è corretta.")
            elif not df2.verifica(df, codice):
                messages.error(request, "Il codice non è corretto.")
            elif azione == "rigenera":
                request.session[CODICI_NUOVI] = df2.nuovi_codici(df)
                messages.success(request, "Nuovi codici di recupero creati: quelli vecchi non valgono più.")
            elif df2.obbligatoria_per(utente):
                messages.error(request, "La tua azienda richiede la verifica in due passaggi: non si può disattivare.")
            else:
                df.delete()
                df2.avvisa(utente, "Verifica in due passaggi disattivata", "La verifica in due passaggi è stata disattivata sul tuo account.")
                messages.success(request, "Verifica in due passaggi disattivata.")
        elif attiva and azione == "revoca_fidati":
            df.generazione += 1
            df.save(update_fields=["generazione"])
            messages.success(request, "I dispositivi fidati dovranno inserire di nuovo il codice.")
        return redirect("core:due_fattori")
    contesto = {"attiva": attiva, "obbligatoria": df2.obbligatoria_per(utente),
                "codici": request.session.pop(CODICI_NUOVI, None)}
    if attiva:
        contesto.update(df=df, codici_rimasti=len(df.codici_recupero), giorni_fidato=df2.GIORNI_FIDATO)
    else:
        df = df2.prepara(utente)
        contesto.update(qr=df2.qr_svg(df), segreto=df2.segreto_a_gruppi(df))
    return render(request, "core/due_fattori.html", contesto)
