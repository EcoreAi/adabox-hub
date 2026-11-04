"""Uno sportello di prova con l'AI e la conoscenza di un'azienda inventata: `genera` lo crea, `azzera` lo toglie."""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from discuss import assistente_sito
from discuss.models import Canale, ConversazioneEsterna, Notifica, Sportello, VoceConoscenza

NOME = "Acme Gestionali (prova)"
CARTELLA = Path(__file__).resolve().parents[2] / "demo_sito"


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("azione", choices=["genera", "azzera"])

    def handle(self, azione, **opzioni):
        self.azzera()
        if azione == "genera":
            self.genera()

    def azzera(self):
        for c in ConversazioneEsterna.objects.filter(sportello__nome=NOME).select_related("canale"):
            Notifica.objects.filter(url=f"/discuss/c/{c.canale_id}/").delete()
            Notifica.objects.filter(messaggio__canale=c.canale).delete()
            Canale.objects.filter(pk=c.canale_id).delete()
        Sportello.objects.filter(nome=NOME).delete()

    def genera(self):
        s = Sportello.objects.create(nome=NOME, modalita=Sportello.AI, nome_ai="Ada del sito",
                                     benvenuto="Ciao! Sono l'assistente virtuale di Acme Gestionali. Chiedimi di prezzi, tempi di avvio, assistenza o sviluppo su misura.",
                                     istruzioni="Acme Gestionali sviluppa un gestionale per PMI. Tono cordiale e professionale, dando del tu.")
        s.operatori.set(get_user_model().objects.filter(is_superuser=True, is_active=True))
        voci = []
        for blocco in re.split(r"^## ", (CARTELLA / "faq.md").read_text(encoding="utf-8"), flags=re.M)[1:]:
            domanda, _, risposta = blocco.partition("\n")
            voci.append(VoceConoscenza.objects.create(sportello=s, tipo=VoceConoscenza.FAQ, titolo=domanda.strip(), testo=risposta.strip()))
        for file in sorted(CARTELLA.glob("*.md")):
            if file.name == "faq.md":
                continue
            testo = file.read_text(encoding="utf-8")
            titolo = testo.splitlines()[0].lstrip("# ").strip()
            voci.append(VoceConoscenza.objects.create(sportello=s, tipo=VoceConoscenza.DOCUMENTO, titolo=titolo, testo=testo))
        for v in voci:                             # subito, senza aspettare il lavoratore
            assistente_sito.indicizza(v.pk)
        self.stdout.write(f"Sportello pronto: {s.pk} · {len(voci)} voci · /discuss/lc/{s.chiave}/")
