# bi/utils.py
import os, time, logging, requests, msal
from django.conf import settings

logger = logging.getLogger(__name__)

# ------------------ cache simples em memória (substitua por Redis se quiser) --
_token_cache: dict[str, str] = {}
_EXP: float | None = None          # epoch em segundos
_REFRESH_EXP: float | None = None  # tempo limite para tentar refresh

def _save_tokens(result: dict):
    global _token_cache, _EXP, _REFRESH_EXP
    _token_cache = result
    _EXP = time.time() + result["expires_in"] - 60        # 1 min de folga
    _REFRESH_EXP = time.time() + result["ext_expires_in"] - 60

def _token_valid() -> bool:
    return _token_cache and _EXP and time.time() < _EXP

# ------------------ aquisições ------------------------------------------------
def _acquire_token_ropc() -> dict | None:
    """ROPC inicial usando usuário/senha."""
    logger.info("PBI-Auth: ROPC inicial (username+password).")
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
    logger.error("PBI-Auth: falha ROPC – %s | %s", result.get("error"), result.get("error_description"))
    return None

def _refresh_token() -> dict | None:
    """Tenta usar refresh_token antes de expirar totalmente."""
    if not _token_cache or "refresh_token" not in _token_cache:
        return None
    if _REFRESH_EXP and time.time() > _REFRESH_EXP:
        return None  # refresh_token expirou
    logger.info("PBI-Auth: usando refresh_token.")
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
    logger.warning("PBI-Auth: refresh_token falhou – voltando ao ROPC.")
    return None

def get_powerbi_access_token() -> str | None:
    """Retorna sempre um access_token válido, renovando se precisar."""
    if _token_valid():
        return _token_cache["access_token"]
    if _refresh_token():
        return _token_cache["access_token"]
    if _acquire_token_ropc():
        return _token_cache["access_token"]
    return None
# -----------------------------------------------------------------------------


def get_embed_params_user_owns_data(report_id: str, group_id: str) -> dict | None:
    """
    Devolve {'embed_url': ..., 'embed_token': ...}
    usando o access-token da conta fixa.
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return None

    headers = {"Authorization": f"Bearer {access_token}"}
    # 1️⃣ pega detalhes do relatório
    info_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports/{report_id}"
    try:
        info = requests.get(info_url, headers=headers, timeout=15)
        info.raise_for_status()
        embed_url = info.json().get("embedUrl")
    except requests.RequestException as exc:
        logger.error("PBI: erro ao obter embedUrl – %s", exc)
        return None

    # 2️⃣ gera embedToken
    gen_url = f"{info_url}/GenerateToken"
    payload = {"accessLevel": "View"}
    try:
        gen = requests.post(gen_url, json=payload, headers=headers, timeout=15)
        gen.raise_for_status()
        embed_token = gen.json().get("token")
    except requests.RequestException as exc:
        logger.error("PBI: erro GenerateToken – %s", exc)
        return None

    return {"embed_url": embed_url, "embed_token": embed_token}
