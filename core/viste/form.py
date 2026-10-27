from django.http import Http404

from .lista import VistaBase


class FormView(VistaBase):
    def dispatch(self, request, *args, **kwargs):
        raise Http404
