# rh/api.py
from __future__ import annotations
import os, sys, logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
import httpx

logger = logging.getLogger("rh.api")

BASE_URL = os.getenv("RH_API_BASE_URL", "").rstrip("/")
EMAIL    = os.getenv("RH_API_EMAIL")
PASSWORD = os.getenv("RH_API_PASSWORD")
TIMEOUT  = int(os.getenv("RH_API_TIMEOUT", "20"))

if not all((BASE_URL, EMAIL, PASSWORD)):
    sys.stderr.write("✖ RH_API_* variáveis ausentes.\n")
    raise SystemExit(1)

# endpoints fixos ------------------------------------------------------------
EP_LOGIN         = "/login"
EP_REFRESH       = "/refresh"
EP_ENTREGAS      = "/segurancaTrabalho/entregasEpi"
EP_CONTRATOS     = "/colaborador/contratos"
EP_CODIGO_ESTOQUE_EPI = "/segurancaTrabalho/codigoEstoqueEpi" # POST

# token cache ---------------------------------------------------------------
class _Token:
    access: str | None = None
    refresh: str | None = None
    exp: datetime       = datetime.min.replace(tzinfo=timezone.utc)

    @classmethod
    def _store(cls, payload: Dict[str, Any]) -> None:
        cls.access  = payload["accessToken"]
        cls.refresh = payload["refreshToken"]
        cls.exp     = datetime.fromisoformat(payload["expiracaoDoToken"].replace("Z", "+00:00"))

    @classmethod
    def _login(cls) -> None:
        r = httpx.post(f"{BASE_URL}{EP_LOGIN}",
                       json={"email": EMAIL, "senha": PASSWORD},
                       timeout=TIMEOUT)
        r.raise_for_status()
        cls._store(r.json())
        logger.info("Token obtido; expira %s", cls.exp)

    @classmethod
    def _refresh(cls) -> bool:
        if not cls.refresh:
            return False
        r = httpx.post(f"{BASE_URL}{EP_REFRESH}",
                       params={"refreshToken": cls.refresh},
                       timeout=TIMEOUT)
        if r.status_code != 200:
            return False
        cls._store(r.json())
        return True

    @classmethod
    def bearer(cls) -> str:
        if cls.access and datetime.now(tz=timezone.utc)+timedelta(seconds=60) < cls.exp:
            return cls.access
        if cls._refresh():
            return cls.access
        cls._login()
        return cls.access


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_Token.bearer()}"}


# helpers --------------------------------------------------------------------
def _get(url: str, *, params: Dict[str, Any] | None = None) -> httpx.Response:
    r = httpx.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r

def _post(url: str, *, json: Any) -> httpx.Response:
    r = httpx.post(url, headers=_headers(), json=json, timeout=TIMEOUT)
    r.raise_for_status()
    return r


# API pública ----------------------------------------------------------------
def list_entregas_epi() -> List[Dict]:
    """Baixa todas as páginas de entregas EPI."""
    out, page = [], 1
    while True:
        chunk = _get(f"{BASE_URL}{EP_ENTREGAS}", params={"pagina": page}).json()
        if not chunk:
            break
        out.extend(chunk)
        page += 1
    logger.info("Recebidas %s entregas de EPI", len(out))
    return out


# --- AQUI ESTÁ A MUDANÇA IMPORTANTE ---
# A função agora retorna um dicionário de dicionários
def contratos_por_numero(numeros: list[int]) -> Dict[int, Dict[str, str]]:
    """
    Retorna { contrato: { "nome": <nome>, "centroCusto2": <cc2>, "descricaoCentroCusto2": <desc_cc2> } }
    consultando /colaborador/contratos.
    """
    contrato_info: Dict[int, Dict[str, str]] = {}
    for n in numeros:
        try:
            r = _get(f"{BASE_URL}{EP_CONTRATOS}", params={"contrato": n, "pagina": 1})
            data = r.json()
            if data:
                contrato_info[n] = {
                    "nome": data[0].get("nome", ""),
                    "centroCusto2": data[0].get("centroCusto2", ""),
                    "descricaoCentroCusto2": data[0].get("descricaoCentroCusto2", ""), # <-- Adicione esta linha
                }
            else:
                contrato_info[n] = {
                    "nome": "",
                    "centroCusto2": "",
                    "descricaoCentroCusto2": "", # <-- Adicione aqui também para consistência
                }
        except httpx.HTTPStatusError as exc:
            logger.warning("Contrato %s não encontrado (%s)", n, exc.response.status_code)
            contrato_info[n] = {
                "nome": "",
                "centroCusto2": "",
                "descricaoCentroCusto2": "", # <-- E aqui
            }
    return contrato_info



def descricoes_epi(codigos: list[str]) -> Dict[str, str]:
    """
    GET /segurancaTrabalho/codigoEstoqueEpi?codigoEstoque=<cód>
    Retorna {codigoEstoque: descricao}. Faz 1-a-1 com cache local.
    """
    descr: Dict[str, str] = {}
    for cod in codigos:
        if not cod:
            continue
        if cod in descr:                            # cache simples
            continue
        try:
            r = _get(f"{BASE_URL}{EP_CODIGO_ESTOQUE_EPI}",
                     params={"codigoEstoque": cod})
            data = r.json()
            if isinstance(data, list) and data:
                descr[cod] = data[0].get("descricao", "")
            elif isinstance(data, dict):
                descr[cod] = data.get("descricao", "")
        except httpx.HTTPStatusError as exc:
            logger.warning("CódigoEstoque %s não encontrado (%s)",
                           cod, exc.response.status_code)
            descr[cod] = ""
    return descr