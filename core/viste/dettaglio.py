from django.http import Http404

from .lista import VistaBase


class DettaglioView(VistaBase):
    def dispatch(self, request, *args, **kwargs):
        raise Http404
