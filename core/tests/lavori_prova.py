"""Funzioni usate come lavori nei test."""
import time

from core.models import Azienda

ESEGUITI = []


def somma(a, b):
    return a + b


def esplode():
    raise RuntimeError("boom")


def crea_e_esplode(nome):
    Azienda.objects.create(nome=nome)
    raise RuntimeError("dopo la scrittura")


def lento(n):
    time.sleep(0.05)
    ESEGUITI.append(n)
