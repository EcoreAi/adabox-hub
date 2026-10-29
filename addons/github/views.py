from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from core import lavori
from core.viste import register
from progetti.models import Compito, progetti_visibili
from progetti.views import DelProgettoVisibile

from .models import Repository, nuovo_segreto


class RepositoryForm(forms.ModelForm):
    token = forms.CharField(label="Token di accesso", required=False, widget=forms.PasswordInput,
                            help_text="facoltativo, per aprire le issue: un fine-grained token con permesso Issues "
                                      "(lettura e scrittura) sul repository; vuoto = resta quello salvato")
    togli_token = forms.BooleanField(label="Togli il token salvato", required=False)

    class Meta:
        model = Repository
        fields = ["nome", "progetto", "chiudi_al_merge", "attivo"]

    def save(self, commit=True):
        if self.cleaned_data.get("togli_token"):
            self.instance.token = ""
        elif self.cleaned_data.get("token"):
            self.instance.token = self.cleaned_data["token"]
        return super().save(commit)


@register
class RepositoryView(DelProgettoVisibile):
    model = Repository
    slug = "repository"
    verbose_name_plural = "repository GitHub"
    list_display = ["nome", "progetto", "chiudi_al_merge", "attivo"]
    list_filter = ["progetto", "attivo"]
    search_fields = ["nome", "progetto__nome"]
    form_class = RepositoryForm
    form_layout = [("Repository", [("nome", "progetto"), ("chiudi_al_merge", "attivo")]),
                   ("Issue da Adabox", [("token", "togli_token")])]
    company_field = "azienda"
    chatter = True
    buttons = ["nuovo_segreto"]

    def nuovo_segreto(self, request, obj):
        obj.segreto = nuovo_segreto()
        obj.save(update_fields=["segreto"])
        return "Nuovo segreto creato: aggiornalo nel webhook su GitHub."
    nuovo_segreto.short_description = "Rigenera il segreto"


@login_required
@require_POST
def crea_issue(request, pk):
    if not request.user.has_perm("github.add_collegamento"):
        raise PermissionDenied
    compito = get_object_or_404(Compito.objects.filter(progetto__in=progetti_visibili(request.user).values("pk")),
                                pk=pk)
    repository = get_object_or_404(Repository, pk=request.POST.get("repository"), progetto_id=compito.progetto_id)
    if not repository.token_cifrato:
        messages.error(request, f"Il repository {repository} non ha un token: aggiungilo nella sua scheda.")
    else:
        lavori.accoda("github.api.crea_issue", compito_id=compito.pk, repository_id=repository.pk,
                      utente_id=request.user.pk, azienda=compito.azienda, utente=request.user)
        messages.success(request, f"Issue in preparazione su {repository}: il collegamento compare tra pochi secondi.")
    return redirect("progetti:compiti_dettaglio", pk=pk)
