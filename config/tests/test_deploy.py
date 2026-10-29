import os
import re
import subprocess
import sys
from pathlib import Path

from django.core.management.utils import get_random_secret_key

ROOT = Path(__file__).resolve().parents[2]


def test_check_deploy_segnala_solo_hsts_e_ssl_redirect():
    env = {
        **os.environ,
        "DEBUG": "False",
        "SECRET_KEY": get_random_secret_key() + get_random_secret_key(),
        "ALLOWED_HOSTS": "localhost",
    }
    for k in ("SECURE_HSTS_SECONDS", "SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
        env.pop(k, None)
    r = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert set(re.findall(r"security\.W\d+", out)) == {"security.W004", "security.W008"}, out


def test_secret_key_che_inizia_con_il_dollaro():
    """django-environ interpreta "$..." come riferimento a un'altra variabile: la chiave deve restare quella data."""
    chiave = "$" + get_random_secret_key()
    r = subprocess.run([sys.executable, "manage.py", "shell", "-c",
                        "from django.conf import settings; print(settings.SECRET_KEY)"],
                       cwd=ROOT, env={**os.environ, "SECRET_KEY": chiave}, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip().splitlines()[-1] == chiave
