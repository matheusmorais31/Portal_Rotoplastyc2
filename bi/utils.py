# bi/utils.py – versão com nome de relatório nos logs + cache de EmbedToken + proteção <5 min
# -----------------------------------------------------------------------------------
"""Power BI helper utils (App‑Owns‑Data – Master User)

• Garante *access_token* válido via ROPC/refresh.
• Gera *embed_token* 1×/h por relatório e guarda no Redis (50 min TTL¹).
• Usa o nome do relatório nos logs.
• **Descarta** token em cache se faltar < 5 min para expirar (evita 401/403 durante carregamento).

¹ TTL = 50 min → sempre entrega token com ≥ 10 min de vida útil; 60 min é o limite imposto pela API.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import jwt  # PyJWT – para ler a claim `exp` do embed_token
import msal
import requests
from django.conf import settings
from django.core.cache import cache  # configure Redis/Memcached em settings.py

logger = logging.getLogger(__name__)

# ════════════════════════════════════════
# 1) AUTH – access_token da conta mestre
# ════════════════════════════════════════
_token_cache: Dict[str, str] = {}
_EXP: Optional[float] = None          # expiração do access_token (epoch seg)
_REFRESH_EXP: Optional[float] = None  # expiração do refresh_token (epoch seg)


def _save_tokens(result: Dict[str, Any]) -> None:
    global _token_cache, _EXP, _REFRESH_EXP
    _token_cache = result
    _EXP = time.time() + result.get("expires_in", 0) - 60  # 1 min folga
    _REFRESH_EXP = time.time() + result.get("ext_expires_in", 0) - 60


def _token_valid() -> bool:  # pragma: no cover
    return bool(_token_cache) and _EXP and time.time() < _EXP  # type: ignore[return-value]


def _acquire_token_ropc() -> Optional[Dict[str, Any]]:
    logger.info("PBI‑Auth: ROPC inicial (username+password).")
    app = msal.ConfidentialClientApplication(
        client_id=settings.POWERBI_CLIENT_ID,
        client_credential=settings.POWERBI_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}",
    )
    result = app.acquire_token_by_username_password(
        username=settings.POWERBI_USERNAME,
        password=settings.POWERBI_PASSWORD,
        scopes=[settings.POWERBI_SCOPE],
    )
    if "access_token" in result:
        _save_tokens(result)
        return result
    logger.error("PBI‑Auth: falha ROPC – %s | %s", result.get("error"), result.get("error_description"))
    return None


def _refresh_token() -> Optional[Dict[str, Any]]:
    if not _token_cache or "refresh_token" not in _token_cache:
        return None
    if _REFRESH_EXP and time.time() > _REFRESH_EXP:
        return None

    logger.info("PBI‑Auth: tentando refresh_token.")
    app = msal.ConfidentialClientApplication(
        client_id=settings.POWERBI_CLIENT_ID,
        client_credential=settings.POWERBI_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}",
    )
    result = app.acquire_token_by_refresh_token(
        refresh_token=_token_cache["refresh_token"],
        scopes=[settings.POWERBI_SCOPE],
    )
    if "access_token" in result:
        _save_tokens(result)
        return result
    logger.warning("PBI‑Auth: refresh_token falhou – voltando ao ROPC.")
    return None


def get_powerbi_access_token() -> Optional[str]:
    if _token_valid():
        return _token_cache["access_token"]
    if _refresh_token():
        return _token_cache["access_token"]
    if _acquire_token_ropc():
        return _token_cache["access_token"]
    return None


# ════════════════════════════════════════
# 2) EMBED – token & url por relatório (com cache)
# ════════════════════════════════════════

_EMBED_TTL = 50 * 60       # 50 min => entrega token com >=10 min de vida
_MIN_LIFETIME = 5 * 60     # 5 min – se faltar menos que isso descarta cache
_CACHE_PREFIX = "pbi:embed:"


def _generate_embed_token(report_id: str, group_id: str, access_token: str) -> Optional[Dict[str, str]]:
    headers = {"Authorization": f"Bearer {access_token}"}
    info_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports/{report_id}"
    try:
        resp_info = requests.get(info_url, headers=headers, timeout=15)
        resp_info.raise_for_status()
        info = resp_info.json()
        embed_url = info.get("embedUrl")
        report_name = info.get("name", report_id)
    except requests.RequestException as exc:
        logger.error("PBI: erro ao obter embedUrl – %s", exc)
        return None

    gen_url = f"{info_url}/GenerateToken"
    payload = {"accessLevel": "View"}
    try:
        resp_gen = requests.post(gen_url, json=payload, headers=headers, timeout=15)
        resp_gen.raise_for_status()
        embed_token = resp_gen.json().get("token")
    except requests.RequestException as exc:
        logger.error("PBI: erro GenerateToken – %s", exc)
        return None

    return {
        "embed_url": embed_url,
        "embed_token": embed_token,
        "report_name": report_name,
    }


def _is_token_still_safe(embed_token: str) -> bool:
    """Retorna True se o token tiver > _MIN_LIFETIME segundos restantes.
    Se não conseguir decodificar (PyJWT “not enough segments” etc.), assume **seguro**—
    dessa forma evitamos descartar cache indevidamente.
    """
    try:
        if isinstance(embed_token, bytes):
            embed_token = embed_token.decode()
        if embed_token.count(".") < 2:
            # token não parece JWT – mantém cache
            return True
        payload = jwt.decode(embed_token, options={"verify_signature": False, "verify_exp": False})
        return (payload.get("exp", 0) - time.time()) > _MIN_LIFETIME
    except Exception as exc:
        logger.debug("PBI: falha ao decodificar exp do embed_token (%s) – assumindo ainda válido.", exc)
        return True  # força regeneração


def get_embed_params_user_owns_data(report_id: str, group_id: str) -> Optional[Dict[str, str]]:
    cache_key = f"{_CACHE_PREFIX}{group_id}:{report_id}"
    cached: Optional[Dict[str, str]] = cache.get(cache_key)  # type: ignore[assignment]

    if cached and _is_token_still_safe(cached["embed_token"]):
        logger.debug("PBI: [%s] embed_token vindo do cache → %s", cached.get("report_name", report_id), cache_key)
        return cached
    elif cached:
        logger.info("PBI: [%s] token a <5 min de expirar – descartando cache.", cached.get("report_name", report_id))

    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("PBI: falha ao obter access_token – não foi possível gerar embed_token.")
        return None

    embed = _generate_embed_token(report_id, group_id, access_token)
    if embed:
        cache.set(cache_key, embed, timeout=_EMBED_TTL)
        logger.info("PBI: [%s] embed_token gerado e salvo em cache (%s s) → %s", embed["report_name"], _EMBED_TTL, cache_key)
    return embed
