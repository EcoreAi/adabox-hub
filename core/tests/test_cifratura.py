import pytest

from core import cifratura


def test_cifra_e_decifra(settings):
    segreto = cifratura.cifra("sk-ant-prova-1234")
    assert segreto and "sk-ant" not in segreto and cifratura.decifra(segreto) == "sk-ant-prova-1234"
    assert cifratura.cifra("") == "" and cifratura.decifra("") == ""
    assert cifratura.mascherato("sk-ant-prova-1234") == "••••1234"


def test_chiave_cambiata(settings):
    segreto = cifratura.cifra("x")
    settings.SECRET_KEY = "un'altra"
    with pytest.raises(cifratura.SegretoIlleggibile):
        cifratura.decifra(segreto)


def test_chiave_esplicita(settings):
    from cryptography.fernet import Fernet
    settings.CHIAVE_CIFRATURA = Fernet.generate_key().decode()
    assert cifratura.decifra(cifratura.cifra("y")) == "y"
