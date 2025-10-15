import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .conf import config

# Sessão com retries/backoff
_session = requests.Session()
_retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST", "PUT"],
)
_adapter = HTTPAdapter(max_retries=_retries)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

def _auth_headers():
    return {
        "authorization": config.api_key or "",
        "accept": "application/json",
        "content-type": "application/json",
    }

def get(path: str, params: dict | None = None, timeout: int = 30):
    """
    Faz GET em https://integration.altforce.com.br/{company_id}{path}
    Ex.: path="/orders"
    """
    base = config.base_company_url.rstrip("/")
    url = f"{base}{path}"
    resp = _session.get(url, headers=_auth_headers(), params=params or {}, timeout=timeout)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        logging.error("AltForce GET falhou (%s): %s | body: %s", resp.status_code, url, resp.text[:800])
        raise
    return resp.json()
