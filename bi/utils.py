# bi/utils.py 
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Dict, Optional

import msal
import requests
from django.conf import settings
from django.core.cache import cache  # aponte para Redis em settings.py

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
    _EXP = time.time() + result.get("expires_in", 0) - 60
    _REFRESH_EXP = time.time() + result.get("ext_expires_in", 0) - 60


def _token_valid() -> bool:  # pragma: no cover
    return bool(_token_cache) and _EXP and time.time() < _EXP  # type: ignore[return-value]


def _acquire_token_ropc() -> Optional[Dict[str, Any]]:
    logger.info("PBI-Auth: ROPC inicial (username+password).")
    app = msal.ConfidentialClientApplication(
        client_id=settings.POWERBI_CLIENT_ID,
        client_credential=settings.POWERBI_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}",
    )
    res = app.acquire_token_by_username_password(
        username=settings.POWERBI_USERNAME,
        password=settings.POWERBI_PASSWORD,
        scopes=[settings.POWERBI_SCOPE],
    )
    if "access_token" in res:
        _save_tokens(res)
        return res
    logger.error("PBI-Auth: falha ROPC – %s | %s", res.get("error"), res.get("error_description"))
    return None


def _refresh_token() -> Optional[Dict[str, Any]]:
    if not _token_cache or "refresh_token" not in _token_cache:
        return None
    if _REFRESH_EXP and time.time() > _REFRESH_EXP:
        return None

    logger.info("PBI-Auth: tentando refresh_token.")
    app = msal.ConfidentialClientApplication(
        client_id=settings.POWERBI_CLIENT_ID,
        client_credential=settings.POWERBI_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}",
    )
    res = app.acquire_token_by_refresh_token(
        refresh_token=_token_cache["refresh_token"],
        scopes=[settings.POWERBI_SCOPE],
    )
    if "access_token" in res:
        _save_tokens(res)
        return res
    logger.warning("PBI-Auth: refresh_token falhou – voltando ao ROPC.")
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
# 2) EMBED – token & url por relatório
# ════════════════════════════════════════
_EMBED_TTL      = 50 * 60  # 50 min
_MIN_LIFETIME   = 5 * 60   # 5 min
_CACHE_PREFIX   = "pbi:embed:"


# ------------ util para TTL (token com 2 segmentos) ---------------
def _get_pbi_token_exp(token: str) -> Optional[float]:
    """Extrai claim exp do embed_token PBI (gzip-base64, 2 segmentos)."""
    try:
        if isinstance(token, bytes):
            token = token.decode()
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)  # pad
        payload_raw = base64.urlsafe_b64decode(payload_b64)
        payload     = json.loads(payload_raw)
        return float(payload.get("exp", 0))
    except Exception:
        return None


def _is_token_still_safe(embed_token: str) -> bool:
    exp = _get_pbi_token_exp(embed_token)
    if not exp:
        return False  # não conseguimos ler – gera novo
    return (exp - time.time()) > _MIN_LIFETIME


# ------------ geração de embed_token ------------------------------
def _generate_embed_token(report_id: str, group_id: str, access_token: str) -> Optional[dict]:
    headers = {"Authorization": f"Bearer {access_token}"}

    # 1️⃣  info do relatório
    info_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports/{report_id}"
    try:
        info = requests.get(info_url, headers=headers, timeout=15)
        info.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PBI: erro ao obter embedUrl – %s", exc)
        return None

    meta        = info.json()
    embed_url   = meta.get("embedUrl")
    report_name = meta.get("name", report_id)
    dataset_id  = meta.get("datasetId")

    # 1.1  log de flags do dataset
    if dataset_id:
        ds_url = f"https://api.powerbi.com/v1.0/myorg/datasets/{dataset_id}"
        try:
            ds = requests.get(ds_url, headers=headers, timeout=15)
            if ds.ok:
                js = ds.json()
                logger.info(
                    "PBI-DBG: Dataset %s | identityRequired=%s | rolesRequired=%s",
                    dataset_id,
                    js.get("isEffectiveIdentityRequired"),
                    js.get("isEffectiveIdentityRolesRequired"),
                )
        except requests.RequestException:
            logger.warning("PBI-DBG: não consegui ler dataset %s", dataset_id)

    # 2️⃣  GenerateToken
    try:
        gen = requests.post(
            f"{info_url}/GenerateToken",
            json={"accessLevel": "View"},
            headers=headers,
            timeout=15,
        )
        gen.raise_for_status()
        embed_token = gen.json().get("token")
    except requests.RequestException as exc:
        logger.error("PBI: erro GenerateToken – %s", exc)
        return None

    return {
        "embed_url":   embed_url,
        "embed_token": embed_token,
        "report_name": report_name,
    }


# ------------ API pública usada pelas views -----------------------
def get_embed_params_user_owns_data(report_id: str, group_id: str) -> Optional[dict]:
    cache_key = f"{_CACHE_PREFIX}{group_id}:{report_id}"
    cached: Optional[dict] = cache.get(cache_key)  # type: ignore[assignment]

    if cached and _is_token_still_safe(cached["embed_token"]):
        logger.debug("PBI: [%s] embed_token vindo do cache → %s",
                     cached.get("report_name", report_id), cache_key)
        return cached
    elif cached:
        logger.info("PBI: [%s] token a <5min de expirar – descartando cache.",
                    cached.get("report_name", report_id))

    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("PBI: falha ao obter access_token – não foi possível gerar embed_token.")
        return None

    embed = _generate_embed_token(report_id, group_id, access_token)
    if embed:
        cache.set(cache_key, embed, timeout=_EMBED_TTL)
        logger.info("PBI: [%s] embed_token gerado e salvo em cache (%s s) → %s",
                    embed["report_name"], _EMBED_TTL, cache_key)
    return embed
