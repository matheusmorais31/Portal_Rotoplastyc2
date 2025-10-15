# rh/api.py
from __future__ import annotations

import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

logger = logging.getLogger("rh.api")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("RH_API_BASE_URL", "").rstrip("/")
EMAIL    = os.getenv("RH_API_EMAIL")
PASSWORD = os.getenv("RH_API_PASSWORD")
TIMEOUT  = int(os.getenv("RH_API_TIMEOUT", "20"))

# controles de retry/backoff
RETRY_MAX           = int(os.getenv("RH_API_RETRY_MAX", "5"))         # tentativas p/ chamada
RETRY_BASE_WAIT_SEC = float(os.getenv("RH_API_RETRY_BASE_WAIT", "2")) # base para backoff exponencial
SLEEP_BETWEEN_CALLS = float(os.getenv("RH_API_THROTTLE", "0.05"))     # “descanso” entre chamadas

if not all((BASE_URL, EMAIL, PASSWORD)):
    sys.stderr.write("✖ RH_API_* variáveis ausentes.\n")
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
EP_LOGIN                = "/login"
EP_REFRESH              = "/refresh"
EP_ENTREGAS             = "/segurancaTrabalho/entregasEpi"
EP_CONTRATOS            = "/colaborador/contratos"
EP_CODIGO_ESTOQUE_EPI   = "/segurancaTrabalho/codigoEstoqueEpi"  # aceita POST (pode rejeitar GET)

# ---------------------------------------------------------------------------
# Token cache + helpers
# ---------------------------------------------------------------------------
class _Token:
    access: str | None = None
    refresh: str | None = None
    exp: datetime       = datetime.min.replace(tzinfo=timezone.utc)

    @classmethod
    def _store(cls, payload: Dict[str, Any]) -> None:
        cls.access  = payload["accessToken"]
        cls.refresh = payload["refreshToken"]
        # a API vem no formato ISO; garantir TZ
        exp_str = payload.get("expiracaoDoToken")
        if exp_str:
            cls.exp = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
        logger.info("Token obtido; expira %s", cls.exp)

    @classmethod
    def _login(cls) -> None:
        r = httpx.post(f"{BASE_URL}{EP_LOGIN}",
                       json={"email": EMAIL, "senha": PASSWORD},
                       timeout=TIMEOUT)
        r.raise_for_status()
        cls._store(r.json())

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
        # renovar um pouco antes de expirar
        if cls.access and datetime.now(tz=timezone.utc) + timedelta(seconds=60) < cls.exp:
            return cls.access
        # tenta refresh; se falhar, faz login
        if cls._refresh():
            return cls.access  # type: ignore[return-value]
        cls._login()
        return cls.access  # type: ignore[return-value]


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {_Token.bearer()}",
        "Accept": "application/json",
    }

# ---------------------------------------------------------------------------
# HTTP helpers com retry básico (401) e rethrow de erros para o caller tratar
# ---------------------------------------------------------------------------
def _respect_retry_after(response: httpx.Response, attempt: int) -> None:
    """Espera tempo indicado pelo servidor ou aplica backoff exponencial."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            wait = float(retry_after)
        except ValueError:
            wait = RETRY_BASE_WAIT_SEC * (attempt + 1)
    else:
        wait = RETRY_BASE_WAIT_SEC * (attempt + 1)
    logger.warning("Esperando %ss antes de repetir…", wait)
    time.sleep(wait)

def _get(url: str, *, params: Dict[str, Any] | None = None) -> httpx.Response:
    """Faz GET com retry único para 401 (token expirado)."""
    r = httpx.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
    if r.status_code == 401:
        logger.info("401 no GET; renovando token e repetindo uma vez.")
        _Token._login()  # força novo token
        r = httpx.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
    r.raise_for_status()
    if SLEEP_BETWEEN_CALLS:
        time.sleep(SLEEP_BETWEEN_CALLS)
    return r

def _post(url: str, *, json: Any) -> httpx.Response:
    """Faz POST com retry único para 401 (token expirado)."""
    r = httpx.post(url, headers=_headers(), json=json, timeout=TIMEOUT)
    if r.status_code == 401:
        logger.info("401 no POST; renovando token e repetindo uma vez.")
        _Token._login()
        r = httpx.post(url, headers=_headers(), json=json, timeout=TIMEOUT)
    r.raise_for_status()
    if SLEEP_BETWEEN_CALLS:
        time.sleep(SLEEP_BETWEEN_CALLS)
    return r

# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def list_entregas_epi() -> List[Dict]:
    """
    Baixa todas as páginas de entregas EPI.
    Lida com 429 aplicando backoff e repetindo a página.
    """
    out: List[Dict] = []
    page = 1
    while True:
        for attempt in range(RETRY_MAX):
            try:
                r = _get(f"{BASE_URL}{EP_ENTREGAS}", params={"pagina": page})
                chunk = r.json()
                break
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 429 and attempt < RETRY_MAX - 1:
                    logger.warning("Rate limit (429) em ENTREGAS página %s. Tentativa %s/%s.",
                                   page, attempt + 1, RETRY_MAX)
                    _respect_retry_after(exc.response, attempt)
                    continue
                raise  # propaga outros códigos

        if not chunk:
            # vazio = acabou as páginas
            break

        if isinstance(chunk, list):
            out.extend(chunk)
        else:
            logger.warning("Formato inesperado em ENTREGAS página %s: %r", page, type(chunk))
            # tentar converter se vier dict único
            if isinstance(chunk, dict):
                out.append(chunk)

        page += 1

    logger.info("Recebidas %s entregas de EPI", len(out))
    return out


def contratos_por_numero(numeros: List[int]) -> Dict[int, Dict[str, str]]:
    """
    Retorna { contrato: { "nome": <nome>, "centroCusto2": <cc2>, "descricaoCentroCusto2": <desc_cc2> } }
    consultando /colaborador/contratos com retry/backoff para 429.
    """
    contrato_info: Dict[int, Dict[str, str]] = {}
    for n in numeros:
        ok = False
        for attempt in range(RETRY_MAX):
            try:
                r = _get(f"{BASE_URL}{EP_CONTRATOS}", params={"contrato": n, "pagina": 1})
                data = r.json()
                if data:
                    first = data[0] if isinstance(data, list) else data
                    contrato_info[n] = {
                        "nome": first.get("nome", ""),
                        "centroCusto2": first.get("centroCusto2", ""),
                        "descricaoCentroCusto2": first.get("descricaoCentroCusto2", ""),
                    }
                else:
                    contrato_info[n] = {"nome": "", "centroCusto2": "", "descricaoCentroCusto2": ""}
                ok = True
                break
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 429 and attempt < RETRY_MAX - 1:
                    logger.warning("Contrato %s rate-limited (429). Tentativa %s/%s.", n, attempt + 1, RETRY_MAX)
                    _respect_retry_after(exc.response, attempt)
                    continue
                if code == 404:
                    logger.warning("Contrato %s inexistente (404).", n)
                    contrato_info[n] = {"nome": "", "centroCusto2": "", "descricaoCentroCusto2": ""}
                    ok = True
                    break
                logger.warning("Falha ao consultar contrato %s (%s).", n, code)
                contrato_info[n] = {"nome": "", "centroCusto2": "", "descricaoCentroCusto2": ""}
                ok = True
                break
            except Exception as e:
                logger.exception("Erro inesperado ao consultar contrato %s: %s", n, e)
                contrato_info[n] = {"nome": "", "centroCusto2": "", "descricaoCentroCusto2": ""}
                ok = True
                break
        if not ok and n not in contrato_info:
            # defesa extra: se saiu do loop sem preencher
            contrato_info[n] = {"nome": "", "centroCusto2": "", "descricaoCentroCusto2": ""}

    return contrato_info


def descricoes_epi(codigos: List[str]) -> Dict[str, str]:
    """
    Retorna {codigoEstoque: descricao}.
    Estratégia:
      1) Tenta GET ?codigoEstoque=<cod>
      2) Se 405/400/500, tenta POST com variações de payload:
         - {"codigoEstoque": <cod>}
         - {"codigo": <cod>}
         - {"codigoEstoqueEpi": <cod>}
         - (se for dígito) as mesmas chaves com int
      3) Para 429, aplica backoff e repete.
      4) Loga o corpo (truncado) em falhas 4xx/5xx para diagnóstico.
    """
    def _parse_desc(data: Any) -> str:
        if isinstance(data, list) and data:
            # comum: [{"descricao": "..."}]
            return str(data[0].get("descricao", "") or "")
        if isinstance(data, dict):
            # às vezes vem {"descricao": "..."} ou outro campo
            return str(data.get("descricao", "") or data.get("Descricao", "") or "")
        return ""

    def _safe_body(resp: httpx.Response) -> str:
        try:
            txt = resp.text or ""
        except Exception:
            return ""
        # evita logar gigabytes
        return txt.replace("\n", " ")[:300]

    descr: Dict[str, str] = {}

    for cod in codigos:
        if not cod or cod in descr:
            continue

        # ---------- 1) GET ----------
        got = False
        for attempt in range(RETRY_MAX):
            try:
                r = _get(f"{BASE_URL}{EP_CODIGO_ESTOQUE_EPI}", params={"codigoEstoque": cod})
                d = _parse_desc(r.json())
                descr[cod] = d
                got = True
                break
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code == 429 and attempt < RETRY_MAX - 1:
                    logger.warning("Rate limit (429) em descrição EPI GET %s. Tentativa %s/%s.",
                                   cod, attempt + 1, RETRY_MAX)
                    _respect_retry_after(exc.response, attempt)
                    continue
                if code in (405, 400, 500):
                    # parte pro POST
                    break
                logger.warning("Falha GET descrição do código %s (%s) body=%s",
                               cod, code, _safe_body(exc.response))
                descr[cod] = ""
                got = True
                break
            except Exception as e:
                logger.exception("Erro inesperado em GET descrição do código %s: %s", cod, e)
                descr[cod] = ""
                got = True
                break

        if got:
            continue

        # ---------- 2) POST com variações de payload ----------
        # gera combinações de payloads possíveis
        payloads = [
            {"codigoEstoque": cod},
            {"codigo": cod},
            {"codigoEstoqueEpi": cod},
        ]
        if str(cod).isdigit():
            icod = int(cod)
            payloads.extend([
                {"codigoEstoque": icod},
                {"codigo": icod},
                {"codigoEstoqueEpi": icod},
            ])

        posted_ok = False
        for payload in payloads:
            for attempt in range(RETRY_MAX):
                try:
                    r2 = _post(f"{BASE_URL}{EP_CODIGO_ESTOQUE_EPI}", json=payload)
                    d2 = _parse_desc(r2.json())
                    descr[cod] = d2
                    posted_ok = True
                    break
                except httpx.HTTPStatusError as exc2:
                    c2 = exc2.response.status_code
                    if c2 == 429 and attempt < RETRY_MAX - 1:
                        logger.warning("Rate limit (429) em descrição EPI POST %s payload=%s. Tentativa %s/%s.",
                                       cod, payload, attempt + 1, RETRY_MAX)
                        _respect_retry_after(exc2.response, attempt)
                        continue
                    # Loga o body para entender o 500
                    logger.warning("Falha POST descrição do código %s (%s) payload=%s body=%s",
                                   cod, c2, payload, _safe_body(exc2.response))
                    break  # muda o payload
                except Exception as e:
                    logger.exception("Erro inesperado em POST descrição do código %s payload=%s: %s",
                                     cod, payload, e)
                    break  # muda o payload
            if posted_ok:
                break

        if not posted_ok and cod not in descr:
            descr[cod] = ""

    return descr
