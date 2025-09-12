# sqlhub/fields.py
from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken
import base64
import hashlib

_TOKEN_PREFIX = "fe:"

def _build_fernets():
    keys = []
    for k in getattr(settings, "FERNET_KEYS", []) or []:
        if not k:
            continue
        if isinstance(k, str):
            k = k.encode()
        # valida / ajusta formato
        try:
            Fernet(k)
            keys.append(k)
        except Exception:
            dig = hashlib.sha256(k).digest()
            keys.append(base64.urlsafe_b64encode(dig))
    if not keys:
        dig = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        keys = [base64.urlsafe_b64encode(dig)]
    return [Fernet(k) for k in keys]

_FERNETS = None
def _get_fernets():
    global _FERNETS
    if _FERNETS is None:
        _FERNETS = _build_fernets()
    return _FERNETS

def _encrypt(plaintext: str) -> str:
    if plaintext is None:
        return None
    token = _get_fernets()[0].encrypt(str(plaintext).encode("utf-8")).decode("utf-8")
    return _TOKEN_PREFIX + token

def _try_decrypt(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    raw = value[len(_TOKEN_PREFIX):] if isinstance(value, str) and value.startswith(_TOKEN_PREFIX) else value
    for f in _get_fernets():
        try:
            return f.decrypt(raw.encode("utf-8")).decode("utf-8")
        except (InvalidToken, Exception):
            continue
    return value

class EncryptedTextField(models.TextField):
    description = "TextField stored encrypted with Fernet"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return _try_decrypt(value)

    def to_python(self, value):
        if value is None:
            return value
        return _try_decrypt(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8", "ignore")
        if isinstance(value, str) and value.startswith(_TOKEN_PREFIX):
            return value
        return _encrypt(value)
