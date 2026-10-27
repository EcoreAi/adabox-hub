from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from core import importa, lavori

from .lista import VistaBase, urls_di

ANTEPRIMA = 5


class ImportaView(VistaBase):
    """Tre passi su una sola URL: carica → mappa (anteprima) → prova a secco → importa."""

    def _chiave(self):
        return f"import_{self.vista.modulo}_{self.vista.slug}"

    def _controlla(self, request):
        if not (self.vista.has_add_permission(request) or
                (self.vista.import_key and self.vista.has_change_permission(request))):
            raise PermissionDenied

    def _rendi(self, request, **ctx):
        vista = self.vista
        return render(request, "core/vista/importa.html", {
            "vista": vista, "urls": urls_di(vista), "campi": importa.campi(vista),
            "con_chiave": bool(vista.import_key), "chiave": vista.etichetta(vista.import_key) if vista.import_key else "",
            **ctx})

    def get(self, request):
        self._controlla(request)
        return self._rendi(request, fase="carica")

    def post(self, request):
        self._controlla(request)
        fase = request.POST.get("fase", "carica")
        if fase == "carica":
            return self._carica(request)
        stato = request.session.get(self._chiave())
        if not stato:
            messages.error(request, "Il file caricato non è più disponibile: ricaricalo.")
            return redirect(self.vista.url("importa"))
        try:
            intestazioni, righe = importa.leggi(stato["file"])
        except (importa.ImportNonValido, OSError) as e:
            messages.error(request, str(e))
            return redirect(self.vista.url("importa"))
        mappa = [request.POST.get(f"col_{i}", "") for i in range(len(intestazioni))]
        validi = dict(importa.campi(self.vista))
        mappa = [m if m in validi else "" for m in mappa]
        aggiorna = request.POST.get("aggiorna") == "1"
        ctx = {"fase": "mappa", "intestazioni": list(zip(range(len(intestazioni)), intestazioni, mappa)),
               "anteprima": righe[:ANTEPRIMA], "totale": len(righe), "aggiorna": aggiorna, "nome": stato["nome"]}
        if not any(mappa):
            messages.error(request, "Associa almeno una colonna a un campo.")
            return self._rendi(request, **ctx)
        if fase == "prova":
            operazioni, errori = importa.valida(self.vista, request, intestazioni, righe, mappa, aggiorna)
            return self._rendi(request, **ctx, provato=True, errori=errori[:200], n_errori=len(errori),
                               nuovi=sum(1 for _, n in operazioni if n), aggiornati=sum(1 for _, n in operazioni if not n))
        if len(righe) > settings.IMPORT_SINCRONO_MAX:
            lavori.accoda("core.importa.in_background", modulo=self.vista.modulo, slug=self.vista.slug,
                          utente_id=request.user.pk, azienda_id=getattr(getattr(request, "azienda", None), "pk", None),
                          file=stato["file"], mappa=mappa, aggiorna=aggiorna, utente=request.user)
            request.session.pop(self._chiave(), None)
            messages.info(request, f"Import di {len(righe)} righe avviato in background: l'esito ti arriva per email.")
            return redirect(self.vista.url("lista"))
        nuovi, aggiornati, errori = importa.esegui(self.vista, request, intestazioni, righe, mappa, aggiorna)
        if errori:
            return self._rendi(request, **ctx, provato=True, errori=errori[:200], n_errori=len(errori))
        importa.percorso(stato["file"]).unlink(missing_ok=True)
        request.session.pop(self._chiave(), None)
        messages.success(request, f"Import completato: {nuovi} nuovi, {aggiornati} aggiornati.")
        return redirect(self.vista.url("lista"))

    def _carica(self, request):
        file = request.FILES.get("file")
        if file is None:
            messages.error(request, "Scegli un file .csv o .xlsx.")
            return self._rendi(request, fase="carica")
        try:
            nome = importa.salva_caricato(file)
            intestazioni, righe = importa.leggi(nome)
        except Exception as e:                       # file illeggibile: lo si dice e si riparte
            messages.error(request, str(e) if isinstance(e, importa.ImportNonValido) else "File non leggibile.")
            return self._rendi(request, fase="carica")
        precedente = request.session.get(self._chiave())
        if precedente:
            importa.percorso(precedente["file"]).unlink(missing_ok=True)
        request.session[self._chiave()] = {"file": nome, "nome": file.name}
        mappa = importa.proponi(self.vista, intestazioni)
        return self._rendi(request, fase="mappa", intestazioni=list(zip(range(len(intestazioni)), intestazioni, mappa)),
                           anteprima=righe[:ANTEPRIMA], totale=len(righe), nome=file.name, aggiorna=False)
