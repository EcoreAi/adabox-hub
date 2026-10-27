from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import ProfiloForm
from .models import Cliente


@login_required
def home(request):
    qs = Cliente.objects.all()
    da_30_giorni = timezone.now() - timedelta(days=30)
    ctx = {
        "totale": qs.count(),
        "attivi": qs.filter(attivo=True).count(),
        "recenti": qs.filter(creato__gte=da_30_giorni).count(),
        "ultimi": qs[:10],
    }
    return render(request, "core/home.html", ctx)


@login_required
def stile(request):
    return render(request, "core/stile.html")


@login_required
def profilo(request):
    form = ProfiloForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilo aggiornato.")
        return redirect("core:profilo")
    return render(request, "core/profilo.html", {"form": form})
