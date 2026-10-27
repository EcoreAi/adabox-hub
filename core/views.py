from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import ProfiloForm


@login_required
def home(request):
    return render(request, "core/home.html")


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
