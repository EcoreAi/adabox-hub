from django.http import Http404

from .lista import VistaBase


class AzioneView(VistaBase):
    def dispatch(self, request, *args, **kwargs):
        raise Http404


class BottoneView(AzioneView):
    pass
