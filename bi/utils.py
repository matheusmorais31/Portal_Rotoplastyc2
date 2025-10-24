# bi/utils.py
from __future__ import annotations

import base64
import json
import logging
import time
import re
from typing import Any, Dict, Optional, Iterable, Tuple, List

import datetime as dt

import msal
import requests
from django.conf import settings
from django.core.cache import cache  # aponte para Redis em settings.py
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

# ════════════════════════════════════════
# Config & helpers de log
# ════════════════════════════════════════

def _api_level() -> int:
    """
    Quando POWERBI_LOG_VERBOSE_API=True, logs “de wire” vão em INFO.
    Caso contrário, ficam em DEBUG (com eventos principais em INFO).
    """
    return logging.INFO if getattr(settings, "POWERBI_LOG_VERBOSE_API", False) else logging.DEBUG

def _short(s: str | bytes | None, n: int = 500) -> str:
    """Retorna apenas um trecho (máx n chars) do payload para log seguro."""
    if s is None:
        return ""
    if isinstance(s, bytes):
        try:
            s = s.decode("utf-8", "replace")
        except Exception:
            s = repr(s)
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


# ════════════════════════════════════════
# Sticky “hint” compartilhado de refresh (para pílula “via api”)
# ════════════════════════════════════════

REFRESH_HINT_TTL = int(getattr(settings, "POWERBI_REFRESH_HINT_TTL", 20 * 60))  # 20 min

def refresh_hint_key(group_id: str, dataset_id: str) -> str:
    return f"pbi:refresh-hint:{str(group_id).lower()}:{str(dataset_id).lower()}"

def set_refresh_hint(group_id: str, dataset_id: str, started_at_epoch: int, origin: str = "api") -> None:
    """
    Salva um “hint” de refresh iniciado via API para todo mundo enxergar imediatamente.
    """
    cache.set(
        refresh_hint_key(group_id, dataset_id),
        {"origin": origin, "started_at": int(started_at_epoch)},
        REFRESH_HINT_TTL,
    )

def get_refresh_hint(group_id: str, dataset_id: str) -> Optional[dict]:
    """
    Lê o hint (ou None).
    """
    return cache.get(refresh_hint_key(group_id, dataset_id))

def clear_refresh_hint(group_id: str, dataset_id: str) -> None:
    """
    Apaga o hint.
    """
    cache.delete(refresh_hint_key(group_id, dataset_id))


# ════════════════════════════════════════
# HTTP – timeouts, UA e tentativa única de retry em 401
# ════════════════════════════════════════

DEFAULT_TIMEOUT = int(getattr(settings, "POWERBI_HTTP_TIMEOUT_SECONDS", 20))
USER_AGENT = getattr(settings, "POWERBI_USER_AGENT", "django-bi/1.0 (+PowerBI)")

def _auth_headers(token: str, extra: Optional[dict] = None) -> dict:
    h = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
    if extra:
        h.update(extra)
    return h

def _request(method: str, url: str, *, json_body: Any = None, headers: Optional[dict] = None,
             timeout: Optional[int] = None) -> requests.Response:
    """
    Invólucro fino sobre requests com:
      - timeout configurável (defaults a DEFAULT_TIMEOUT)
      - User-Agent
      - log básico
    *Não* faz retry automático aqui. Retry 401 (token expirado) é feito pontualmente onde agrega valor.
    """
    to = int(timeout or DEFAULT_TIMEOUT)
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    logger.log(_api_level(), "HTTP %s %s", method, url)
    if json_body is not None:
        try:
            logger.debug("HTTP body(out): %s", _short(json.dumps(json_body, ensure_ascii=False)))
        except Exception:
            logger.debug("HTTP body(out): <unserializable>")
    resp = requests.request(method.upper(), url, json=json_body, headers=h, timeout=to)
    logger.log(_api_level(), "HTTP ← %s", resp.status_code)
    if not resp.ok:
        logger.debug("HTTP body(in): %s", _short(resp.text))
    return resp


# ════════════════════════════════════════
# 1) AUTH – access_token via Service Principal (client_credentials)
# ════════════════════════════════════════

_token_cache: Dict[str, Any] = {}
_EXP: Optional[float] = None  # expiração do access_token (epoch seg)

def _oauth_scope() -> str:
    # Fallback padrão do AAD p/ Power BI se não configurado.
    return getattr(settings, "POWERBI_SCOPE", "https://analysis.windows.net/powerbi/api/.default")

def _save_tokens(result: Dict[str, Any]) -> None:
    """Guarda token em cache de processo, com margem de expiração."""
    global _token_cache, _EXP
    _token_cache = result
    _EXP = time.time() + result.get("expires_in", 0) - 60  # margem de 60s

def _token_valid() -> bool:  # pragma: no cover
    return bool(_token_cache) and _EXP is not None and time.time() < _EXP  # type: ignore[return-value]

def _acquire_token_client_credentials() -> Optional[Dict[str, Any]]:
    """
    Obtém access_token via client_credentials (Service Principal).
    """
    logger.log(_api_level(), "PBI-Auth: client_credentials (service principal).")
    app = msal.ConfidentialClientApplication(
        client_id=settings.POWERBI_CLIENT_ID,
        client_credential=settings.POWERBI_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}",
    )
    res = app.acquire_token_for_client(scopes=[_oauth_scope()])
    if "access_token" in res:
        _save_tokens(res)
        logger.debug("PBI-Auth: token adquirido, expires_in=%s", res.get("expires_in"))
        return res

    logger.error(
        "PBI-Auth: falha client_credentials – %s | %s",
        res.get("error"), res.get("error_description")
    )
    return None

def get_powerbi_access_token() -> Optional[str]:
    """
    Retorna um access_token válido para chamar as APIs do Power BI.
    """
    if _token_valid():
        return _token_cache["access_token"]
    if _acquire_token_client_credentials():
        return _token_cache["access_token"]
    return None


# ════════════════════════════════════════
# 2) EMBED – token & url por relatório
# ════════════════════════════════════════

_EMBED_TTL = 50 * 60  # 50 min
_MIN_LIFETIME = 5 * 60  # 5 min
_CACHE_PREFIX = "pbi:embed:"

def _get_pbi_token_exp(token: str) -> Optional[float]:
    """Extrai claim 'exp' do embed_token PBI (JWT-like com 2+ segmentos)."""
    try:
        if isinstance(token, bytes):
            token = token.decode()
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)  # pad
        payload_raw = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_raw)
        return float(payload.get("exp", 0))
    except Exception:
        return None

def _is_token_still_safe(embed_token: str) -> bool:
    """True se o token ainda tem > _MIN_LIFETIME segundos de vida."""
    exp = _get_pbi_token_exp(embed_token)
    if not exp:
        return False  # não conseguimos ler – gere novo
    return (exp - time.time()) > _MIN_LIFETIME

def _generate_embed_token(report_id: str, group_id: str, access_token: str) -> Optional[dict]:
    headers = _auth_headers(access_token)

    # 1) info do relatório
    info_url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/reports/{report_id}"
    try:
        info = _request("GET", info_url, headers=headers)
        if info.status_code == 401:
            # tenta renovar token 1x
            access_token2 = get_powerbi_access_token()  # força refresh
            if not access_token2:
                return None
            info = _request("GET", info_url, headers=_auth_headers(access_token2))
        info.raise_for_status()
    except requests.RequestException as exc:
        logger.error("PBI: erro ao obter embedUrl – %s", exc)
        return None

    meta = info.json() or {}
    embed_url = meta.get("embedUrl")
    report_name = meta.get("name", report_id)
    dataset_id = meta.get("datasetId")
    logger.log(_api_level(), "PBI: report %s → dataset_id=%s", report_name, dataset_id)

    # Opcional: ler dataset para log de flags
    if dataset_id:
        ds_url = f"https://api.powerbi.com/v1.0/myorg/datasets/{dataset_id}"
        try:
            ds = _request("GET", ds_url, headers=headers)
            logger.log(_api_level(), "PBI-DBG: GET dataset (myorg) HTTP %s", ds.status_code)
            if ds.ok:
                js = ds.json()
                logger.debug(
                    "PBI-DBG: Dataset %s | identityRequired=%s | rolesRequired=%s",
                    dataset_id,
                    js.get("isEffectiveIdentityRequired"),
                    js.get("isEffectiveIdentityRolesRequired"),
                )
        except requests.RequestException as exc:
            logger.debug("PBI-DBG: não consegui ler dataset %s — %s", dataset_id, exc)

    # 2) GenerateToken (View)
    try:
        gen = _request(
            "POST",
            f"{info_url}/GenerateToken",
            json_body={"accessLevel": "View"},
            headers=headers,
        )
        if gen.status_code == 401:
            access_token2 = get_powerbi_access_token()
            if not access_token2:
                return None
            gen = _request(
                "POST",
                f"{info_url}/GenerateToken",
                json_body={"accessLevel": "View"},
                headers=_auth_headers(access_token2),
            )
        gen.raise_for_status()
        embed_token = gen.json().get("token")
    except requests.RequestException as exc:
        logger.error("PBI: erro GenerateToken — %s", exc)
        return None

    return {
        "embed_url": embed_url,
        "embed_token": embed_token,
        "report_name": report_name,
    }

def get_embed_params_user_owns_data(report_id: str, group_id: str) -> Optional[dict]:
    """
    Retorna {embed_url, embed_token, report_name} para um report.
    Usa cache (Django cache) e renova o token se ele estiver a <5 min de expirar.
    """
    cache_key = f"{_CACHE_PREFIX}{group_id}:{report_id}"
    cached: Optional[dict] = cache.get(cache_key)  # type: ignore[assignment]

    if cached and _is_token_still_safe(cached["embed_token"]):
        logger.debug("PBI: [%s] embed_token (cache) → %s", cached.get("report_name", report_id), cache_key)
        return cached
    elif cached:
        logger.log(_api_level(), "PBI: [%s] token a <5min de expirar – descartando cache.", cached.get("report_name", report_id))

    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("PBI: falha ao obter access_token – não foi possível gerar embed_token.")
        return None

    embed = _generate_embed_token(report_id, group_id, access_token)
    if embed:
        cache.set(cache_key, embed, timeout=_EMBED_TTL)
        logger.info("PBI: [%s] embed_token gerado e cacheado (%ss).", embed["report_name"], _EMBED_TTL)
    return embed


# ════════════════════════════════════════
# 3) REAL-TIME – última atualização do dataset do relatório
# ════════════════════════════════════════

def _parse_pbi_dt_to_utc(dt_str: str | None) -> Optional[timezone.datetime]:
    """Converte string ISO do Power BI para datetime aware em UTC."""
    if not dt_str:
        return None
    try:
        parsed = parse_datetime(dt_str)
        if not parsed:
            return None
        if timezone.is_naive(parsed):
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        else:
            parsed = parsed.astimezone(dt.timezone.utc)
        return parsed
    except Exception:
        return None

def _pick_newest_refresh_dt(refreshes: list[dict]) -> Optional[timezone.datetime]:
    """Pega somente o último refresh CONCLUÍDO."""
    VALID = {"Completed"}
    newest: Optional[timezone.datetime] = None
    for r in refreshes or []:
        status = (r.get("status") or "").strip()
        if status not in VALID:
            continue
        for cand in (_parse_pbi_dt_to_utc(r.get("endTime")), _parse_pbi_dt_to_utc(r.get("startTime"))):
            if cand and (newest is None or cand > newest):
                newest = cand
    return newest


# ════════════════════════════════════════
# 4) RESOLUÇÃO DE DATASET (report → dataset) + cache
# ════════════════════════════════════════

_RESOLVE_TTL = int(getattr(settings, "POWERBI_RESOLVE_CACHE_TTL", 300))
_RESOLVE_CACHE_PREFIX = "pbi:resolve:"

def _probe_dataset_workspace(dataset_id: str, candidates: list[str], headers: dict) -> Optional[str]:
    """Descobre em qual workspace o dataset existe (primeiro 200)."""
    for gid in candidates:
        url = f"https://api.powerbi.com/v1.0/myorg/groups/{gid}/datasets/{dataset_id}"
        try:
            r = _request("GET", url, headers=headers)
            logger.log(_api_level(), "PBI: probe dataset %s → HTTP %s (group %s)", dataset_id, r.status_code, gid)
            if r.status_code == 200:
                return gid
        except requests.RequestException as exc:
            logger.debug("PBI: probe dataset %s falhou no group %s — %s", dataset_id, gid, exc)
    return None

def _resolve_dataset_ids(report_id: str, report_group_id: str, headers: dict) -> tuple[str, str] | None:
    """
    Retorna (dataset_id, dataset_workspace_id) a partir de um report, com cache.
    """
    ckey = f"{_RESOLVE_CACHE_PREFIX}{report_group_id}:{report_id}"
    cached = cache.get(ckey)
    if cached:
        logger.debug("PBI: resolve cache HIT → %s", ckey)
        return cached

    info_url = f"https://api.powerbi.com/v1.0/myorg/groups/{report_group_id}/reports/{report_id}"
    try:
        ir = _request("GET", info_url, headers=headers)
        logger.log(_api_level(), "PBI: reports/{id} HTTP %s", ir.status_code)
        if ir.status_code != 200:
            ir.raise_for_status()
        js = ir.json() or {}
        dataset_id = js.get("datasetId")
        ds_group_id = js.get("datasetWorkspaceId") or report_group_id
        logger.log(_api_level(), "PBI: report→dataset: dataset_id=%s | ds_group_id=%s", dataset_id, ds_group_id)
        if not dataset_id:
            logger.warning("PBI: report %s não tem datasetId", report_id)
            return None
    except requests.RequestException as exc:
        logger.error("PBI: erro obtendo report %s — %s", report_id, exc)
        return None

    candidates = []
    if ds_group_id:
        candidates.append(ds_group_id)
    if report_group_id not in candidates:
        candidates.append(report_group_id)
    extras = getattr(settings, "POWERBI_PROBE_GROUP_IDS", []) or []
    for gid in extras:
        if gid not in candidates:
            candidates.append(gid)

    real_gid = _probe_dataset_workspace(dataset_id, candidates, headers) or ds_group_id
    if real_gid != ds_group_id:
        logger.debug("PBI: datasetWorkspaceId ajustado via probe: %s → %s", ds_group_id, real_gid)

    cache.set(ckey, (dataset_id, real_gid), timeout=_RESOLVE_TTL)
    return dataset_id, real_gid


# ════════════════════════════════════════
# 5) REAL-TIME – última atualização (usando resolução cacheada)
# ════════════════════════════════════════

def get_report_last_refresh_time_rt(report_id: str, report_group_id: str) -> Optional[timezone.datetime]:
    """
    Busca em tempo real a última atualização do dataset do relatório.
    Retorna datetime aware (UTC) se USE_TZ=True; caso contrário, naive local.
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("RT: sem_access_token.")
        return None

    headers = _auth_headers(access_token)

    # Resolver dataset via endpoint direto (com cache)
    ids = _resolve_dataset_ids(report_id, report_group_id, headers)
    if not ids:
        return None
    dataset_id, ds_group_id = ids

    # Buscar refreshes do dataset e pegar o mais recente (com 1 retry em ReadTimeout)
    ref_url = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/refreshes?$top=50"
    try:
        rr = _request("GET", ref_url, headers=headers)
    except requests.ReadTimeout:
        logger.warning("RT: timeout lendo refreshes — tentando novamente com timeout maior.")
        try:
            rr = _request("GET", ref_url, headers=headers, timeout=DEFAULT_TIMEOUT * 2)
        except Exception as e:
            logger.error("RT: erro buscando refreshes (retry) – %s", e)
            return None
    except Exception as e:
        logger.error("RT: erro buscando refreshes – %s", e, exc_info=True)
        return None

    logger.log(_api_level(), "RT: refreshes HTTP %s", rr.status_code)
    if not rr.ok:
        return None

    try:
        newest = _pick_newest_refresh_dt((rr.json() or {}).get("value", []))
    except Exception:
        logger.debug("RT: payload inválido ao ler refreshes.")
        newest = None

    if not newest:
        return None

    if not settings.USE_TZ:
        try:
            local_tz = timezone.get_current_timezone()
            return timezone.localtime(newest, local_tz).replace(tzinfo=None)
        except Exception:
            return None
    return newest


# ════════════════════════════════════════
# 6) REFRESH – dataset
# ════════════════════════════════════════

def _parse_service_error(raw: dict) -> tuple[str, str]:
    """Extrai (error_code, error_message) de payloads do Power BI."""
    code = ""
    msg_parts: list[str] = []

    def add(s):
        if isinstance(s, str):
            s = s.strip()
            if s and s not in msg_parts:
                msg_parts.append(s)

    add(raw.get("message"))

    if isinstance(raw.get("error"), dict):
        e = raw["error"]
        code = e.get("code") or code
        add(e.get("message"))

        pe = e.get("pbi.error")
        if isinstance(pe, dict):
            code = pe.get("code") or code
            add(pe.get("message"))

            details = pe.get("details") or []
            if isinstance(details, list):
                for d in details:
                    dcode = (d.get("code") or "").strip()
                    dval  = (d.get("detail") or {}).get("value")

                    if dcode.endswith("UnderlyingErrorMessage"):
                        add(dval)
                    elif dcode.endswith("Message"):
                        add(dval)
                    elif "Microsoft.Data.Mashup.ValueError.Detail" in dcode:
                        add(str(dval))
                    elif isinstance(dval, str) and dval:
                        add(dval)

    sj = raw.get("serviceExceptionJson")
    if isinstance(sj, str) and sj.strip():
        try:
            j = json.loads(sj)
            c2, m2 = _parse_service_error(j)
            code = c2 or code
            add(m2)
        except Exception:
            add(sj)

    code = (raw.get("errorCode") or raw.get("code") or code or "").strip()

    if not msg_parts:
        HINTS = {
            "DM_GWPipeline_Gateway_MashupDataAccessError": "Falha no gateway ao acessar a fonte de dados (caminho/permissão/arquivo).",
            "ModelRefresh_ShortMessage_ProcessingError": "Erro de processamento do modelo durante o refresh.",
            "DM_GWPipeline_Client_GatewayUnreachable": "Gateway indisponível ou offline.",
        }
        hint = HINTS.get(code, "")
        if hint:
            add(hint)

    return code, " — ".join(msg_parts).strip()

def trigger_dataset_refresh(report_id: str, report_group_id: str, refresh_type: str = "Full") -> tuple[bool, str]:
    """
    Dispara o refresh do dataset do report.
    Retorna (ok, detalhe).
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return False, "sem_access_token"
    headers = _auth_headers(access_token, {"Content-Type": "application/json"})

    ids = _resolve_dataset_ids(report_id, report_group_id, headers)
    if not ids:
        return False, "dataset_nao_encontrado"
    dataset_id, ds_group_id = ids

    url = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/refreshes"
    payload = {"type": refresh_type, "notifyOption": "NoNotification"}
    logger.log(_api_level(), "PBI: POST refresh dataset url=%s payload=%s", url, payload)

    try:
        r = _request("POST", url, json_body=payload, headers=headers)
        if r.status_code == 401:
            # refresh 1x o token e tenta novamente
            access_token2 = get_powerbi_access_token()
            if access_token2:
                r = _request("POST", url, json_body=payload, headers=_auth_headers(access_token2, {"Content-Type": "application/json"}))
        if r.status_code in (200, 202):
            logger.info(
                "PBI: refresh acionado para dataset %s (group %s) [%s]",
                dataset_id, ds_group_id, refresh_type
            )
            return True, "accepted"
        try:
            j = r.json()
        except Exception:
            j = {}

        code, msg = _parse_service_error(j)
        detail = f"http_{r.status_code}"
        if code:
            detail += f":{code}"
        if msg:
            detail += f" — {msg[:300]}"  # limita tamanho
        logger.error("PBI: refresh dataset falhou %s — %s", r.status_code, j)
        return False, detail
    except requests.RequestException as exc:
        logger.error("PBI: erro POST refresh dataset — %s", exc)
        return False, "request_exception"


# ════════════════════════════════════════
# 7) STATUS DO REFRESH – checagem do último job (opcional)
# ════════════════════════════════════════

def _infer_refresh_type(rec: dict) -> str:
    """
    Normaliza um rótulo amigável de 'refresh_type' para o front-end.
    Preferências:
      - requestType: Scheduled | OnDemand | ViaApi (varia por tenant)
      - refreshType: idem em alguns payloads
      - type: Full | Incremental | Calculate (não é origem, mas ajuda)
    """
    req = (rec.get("requestType") or rec.get("refreshType") or "").strip().lower()
    if req in {"scheduled"}:
        return "scheduled"
    if req in {"ondemand", "on_demand"}:
        return "manual"
    if req in {"viaapi", "api"}:
        return "api"
    typ = (rec.get("type") or "").strip().lower()
    # se vier só o "type" (ex.: Full/Incremental), devolve-o
    return typ or (req or "")

def get_latest_refresh_status(report_id: str, report_group_id: str, *, after_epoch: Optional[int] = None) -> dict:
    """
    Lê o último refresh do dataset do report e retorna um resumo.
    Se after_epoch for informado, e o último registro for mais antigo que esse
    instante (com pequena tolerância negativa), retorna status "Unknown".
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return {"ok": False, "error": "sem_access_token"}

    headers = _auth_headers(access_token)

    ids = _resolve_dataset_ids(report_id, report_group_id, headers)
    if not ids:
        return {"ok": False, "error": "dataset_nao_encontrado"}

    dataset_id, ds_group_id = ids
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/refreshes?$top=1"

    try:
        r = _request("GET", url, headers=headers)
        logger.log(_api_level(), "PBI: latest refresh HTTP %s", r.status_code)
        if not r.ok:
            return {"ok": False, "error": f"http_{r.status_code}"}
        data = r.json() or {}
        rows = data.get("value") or []
        last = rows[0] if rows else {}

        status = (last.get("status") or "Unknown").strip()
        start_dt = _parse_pbi_dt_to_utc(last.get("startTime"))
        end_dt = _parse_pbi_dt_to_utc(last.get("endTime"))

        # Ajuste: label de tipo de refresh para o front
        refresh_type = _infer_refresh_type(last)

        # Ajuste: filtro opcional por after_epoch (evita confundir com execuções antigas)
        if after_epoch is not None:
            guard_neg = int(getattr(settings, "POWERBI_REFRESH_START_GUARD_NEG_S", 10))
            base = max(0, int(after_epoch) - guard_neg)
            start_ok = bool(start_dt and int(start_dt.timestamp()) >= base)
            end_ok = bool(end_dt and int(end_dt.timestamp()) >= base)
            if not (start_ok or end_ok):
                # Não qualifica como "o refresh que estamos acompanhando"
                return {
                    "ok": True,
                    "status": "Unknown",
                    "start_epoch": None,
                    "end_epoch": None,
                    "error_code": "",
                    "error_message": "",
                    "refresh_type": "",
                }

        error_code, error_message = _parse_service_error(last)

        return {
            "ok": True,
            "status": status,
            "start_epoch": int(start_dt.timestamp()) if start_dt else None,
            "end_epoch": int(end_dt.timestamp()) if end_dt else None,
            "error_code": error_code,
            "error_message": error_message,
            "refresh_type": refresh_type,
        }
    except requests.RequestException as exc:
        logger.error("PBI: erro lendo refreshes — %s", exc)
        return {"ok": False, "error": "request_exception"}
    except Exception:
        logger.exception("PBI: exceção inesperada lendo refreshes")
        return {"ok": False, "error": "internal_error"}


# ════════════════════════════════════════
# 8) CASCATA – descoberta de dataflows (Gen1-friendly) e refresh
# ════════════════════════════════════════

def _dedup(seq: Iterable[dict], key=lambda x: (x.get("group_id"), x.get("dataflow_id"))) -> list[dict]:
    seen = set()
    out = []
    for it in seq or []:
        k = key(it)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out

def _extract_dataflows_from_datasources(js: dict, default_group_id: str) -> list[dict]:
    """Extrai dataflows de /datasets/{id}/datasources (heurístico)."""
    values = (js or {}).get("value") or []
    found: list[dict] = []

    for i, d in enumerate(values):
        typ = (d.get("datasourceType") or d.get("type") or "").lower()
        conn = d.get("connectionDetails")

        if isinstance(conn, str):
            raw_conn = conn
            try:
                conn = json.loads(conn)
            except Exception:
                conn = {}
        else:
            raw_conn = json.dumps(conn, ensure_ascii=False) if isinstance(conn, dict) else str(conn)

        logger.log(_api_level(), "PBI: datasources[%s] type=%s", i, typ or "—")
        logger.debug("PBI: datasources[%s] connectionDetails: %s", i, _short(raw_conn))

        if not isinstance(conn, dict):
            conn = {}

        df_id = (
            conn.get("dataflowId")
            or conn.get("dataflowObjectId")
            or conn.get("objectId")
            or conn.get("dataflow")
            or conn.get("dataflow_id")
        )
        df_group = (
            conn.get("workspaceId")
            or conn.get("groupId")
            or conn.get("workspace")
            or default_group_id
        )

        if not df_id:
            for k in ("path", "location", "entityPath", "cdmFolder", "url", "connectionString"):
                v = conn.get(k)
                if isinstance(v, str):
                    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", v, re.I)
                    if m:
                        df_id = m.group(0)
                        logger.debug("PBI: datasources[%s] GUID extraído de %s → %s", i, k, df_id)
                        break

        if df_id:
            item = {
                "dataflow_id": str(df_id).lower(),
                "group_id": str(df_group or default_group_id).lower(),
            }
            logger.log(_api_level(), "PBI: datasources[%s] → candidato dataflow %s/%s", i, item["group_id"], item["dataflow_id"])
            found.append(item)

    return _dedup(found)

def _extract_dataflows_from_lineage(js: dict, dataset_id: str, default_group_id: str) -> list[dict]:
    """Usa grafo de linhagem do workspace para achar dataflows → dataset."""
    graph = js.get("lineageGraph") or js
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or graph.get("lineageEdges") or []

    idx = {n.get("id"): n for n in nodes}

    ds_node_ids = set()
    for n in nodes:
        node_type = (n.get("nodeType") or n.get("type") or "").lower()
        obj_id = (n.get("objectId") or n.get("entityId") or n.get("datasetId") or "").lower()
        if "dataset" in node_type and obj_id == dataset_id.lower():
            ds_node_ids.add(n.get("id"))

    if not ds_node_ids:
        for e in edges:
            tgt_obj = (e.get("targetEntityId") or e.get("targetObjectId") or "").lower()
            if tgt_obj == dataset_id.lower():
                ds_node_ids.add(e.get("targetNodeId"))

    found: list[dict] = []
    for e in edges:
        if e.get("targetNodeId") not in ds_node_ids:
            continue
        src = idx.get(e.get("sourceNodeId")) or {}
        s_type = (src.get("nodeType") or src.get("type") or "").lower()
        if "dataflow" not in s_type:
            continue

        df_id = src.get("objectId") or src.get("entityId") or src.get("dataflowId")
        df_group = src.get("workspaceId") or src.get("groupId") or default_group_id
        if df_id:
            found.append({
                "dataflow_id": str(df_id).lower(),
                "group_id": str(df_group or default_group_id).lower(),
            })
    return _dedup(found)

def _extract_dataflows_from_upstream(js: dict, default_group_id: str) -> list[dict]:
    """Extrai de /datasets/{id}/upstreamDataflows."""
    vals = []
    if isinstance(js, dict):
        vals = js.get("value") or js.get("upstreamDataflows") or []
    elif isinstance(js, list):
        vals = js
    out: list[dict] = []
    for d in vals or []:
        df_id = (d.get("dataflowId") or d.get("objectId") or d.get("id") or "").strip()
        df_group = (d.get("groupId") or d.get("workspaceId") or default_group_id or "").strip()
        if df_id:
            out.append({
                "dataflow_id": str(df_id).lower(),
                "group_id": str(df_group or default_group_id).lower(),
            })
    return _dedup(out)

def _list_upstream_datasets(dataset_id: str, ds_group_id: str, headers: dict) -> list[str]:
    """Lista datasets “pais” (upstream) de um dataset (nem todo tenant suporta)."""
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/upstreamDatasets"
    try:
        r = _request("GET", url, headers=headers)
        logger.log(_api_level(), "PBI: upstreamDatasets HTTP %s (group %s/dataset %s)", r.status_code, ds_group_id, dataset_id)
        if r.status_code == 404 or not r.ok:
            return []
        js = r.json() or {}
        vals = js.get("value") or []
        ids = [v.get("id") for v in vals if v.get("id")]
        return [str(x) for x in ids]
    except requests.RequestException as exc:
        logger.debug("PBI: upstreamDatasets erro — %s", exc)
        return []

# --------- Dataflows do workspace (Gen1) -------------
def _list_workspace_dataflows(group_id: str, headers: dict):
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/dataflows"
    try:
        r = _request("GET", url, headers=headers)
        logger.log(_api_level(), "PBI: list dataflows HTTP %s (group %s)", r.status_code, group_id)
        if r.status_code == 403:
            return {"ok": False, "error": "forbidden", "status": 403}
        if not r.ok:
            return {"ok": False, "error": f"http_{r.status_code}", "status": r.status_code}
        js = r.json() or {}
        vals = js.get("value") or []
        out = []
        for v in vals:
            df_id = v.get("objectId") or v.get("id")
            name = v.get("name") or v.get("displayName") or ""
            if df_id:
                out.append({"dataflow_id": str(df_id), "group_id": group_id, "name": str(name)})
        return {"ok": True, "items": out}
    except requests.RequestException as exc:
        logger.debug("PBI: list dataflows erro — %s", exc)
        return {"ok": False, "error": "request_exception", "status": 502}

def list_workspace_dataflows(group_id: str):
    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("PBI: list_workspace_dataflows – sem_access_token")
        return {"ok": False, "error": "sem_access_token", "status": 401}
    headers = _auth_headers(access_token)
    return _list_workspace_dataflows(group_id, headers)

# --------- Hints por nome (settings) -------------
def _name_hints_for(report_id: str, dataset_id: str) -> list[str]:
    conf = getattr(settings, "POWERBI_UPSTREAM_NAMES_HINTS", None)
    if not conf:
        return []
    if isinstance(conf, dict):
        by_ds = conf.get("by_dataset") or {}
        by_rp = conf.get("by_report") or {}
        glob = conf.get("global") or []
        hints = by_ds.get(dataset_id) or by_rp.get(report_id) or glob
        if isinstance(hints, str):
            hints = [hints]
        return [str(h).strip() for h in (hints or []) if str(h).strip()]
    if isinstance(conf, (list, tuple)):
        return [str(h).strip() for h in conf if str(h).strip()]
    return []

def _match_dataflows_by_name(group_id: str, headers: dict, hints: list[str]) -> list[dict]:
    if not hints:
        return []
    dataflows = _list_workspace_dataflows(group_id, headers)
    out = []
    low_hints = [h.lower() for h in hints]
    for df in dataflows if isinstance(dataflows, list) else (dataflows.get("items") or []):
        nm = (df.get("name") or "").lower()
        if any(h in nm for h in low_hints):
            out.append({"dataflow_id": df["dataflow_id"], "group_id": group_id})
    if out:
        logger.debug("PBI: matched por nome (%s) → %s", hints, [o["dataflow_id"] for o in out])
    return _dedup(out)

# --------- Override por BD (tela de edição) -------------
def _load_upstream_override_db(report_id: str, dataset_id: str, default_group_id: str) -> list[dict]:
    """Lê BIReport.upstream_dataflows (prioridade > settings)."""
    try:
        from .models import BIReport
        qs = BIReport.objects.filter(report_id=report_id, group_id=default_group_id)[:1]
        if not qs:
            qs = BIReport.objects.filter(report_id=report_id)[:1]
        if not qs:
            qs = BIReport.objects.filter(embed_code__icontains=report_id)[:1]
        if not qs:
            return []

        cfg = qs[0].upstream_dataflows or []
        out = []
        for it in (cfg if isinstance(cfg, list) else []):
            df = (it.get("dataflow_id") or it.get("id") or it.get("objectId") or "").strip()
            gid = (it.get("group_id") or it.get("workspaceId") or it.get("groupId") or default_group_id or "").strip()
            if df:
                out.append({"group_id": (gid or default_group_id).lower(), "dataflow_id": df.lower()})
        return _dedup(out)
    except Exception as exc:
        logger.debug("PBI: override DB erro — %s", exc, exc_info=True)
        return []

# --------- Descoberta (com fallbacks Gen1) -------------
def _discover_upstream_dataflows(dataset_id: str, ds_group_id: str, headers: dict, *, report_id: str = "") -> list[dict]:
    """
    Descoberta automática (apenas quando habilitada explicitamente).
    """
    # 1) upstreamDataflows
    url_up = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/upstreamDataflows"
    try:
        ru = _request("GET", url_up, headers=headers)
        logger.log(_api_level(), "PBI: upstreamDataflows HTTP %s (group %s/dataset %s)", ru.status_code, ds_group_id, dataset_id)
        if ru.ok:
            out = _extract_dataflows_from_upstream(ru.json() or {}, ds_group_id)
            if out:
                return out
    except requests.RequestException as exc:
        logger.debug("PBI: upstreamDataflows erro — %s", exc)

    # 2) lineage
    url_lineage = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/lineage"
    try:
        rl = _request("GET", url_lineage, headers=headers)
        logger.log(_api_level(), "PBI: lineage HTTP %s (workspace %s)", rl.status_code, ds_group_id)
        if rl.ok:
            ups = _extract_dataflows_from_lineage(rl.json() or {}, dataset_id, ds_group_id)
            if ups:
                return ups
    except requests.RequestException as exc:
        logger.debug("PBI: lineage erro — %s", exc)

    # 3) datasources
    url_ds = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/datasources"
    try:
        rds = _request("GET", url_ds, headers=headers)
        logger.log(_api_level(), "PBI: datasources HTTP %s (group %s/dataset %s)", rds.status_code, ds_group_id, dataset_id)
        if rds.ok:
            ups = _extract_dataflows_from_datasources(rds.json() or {}, ds_group_id)
            if ups:
                return ups
    except requests.RequestException as exc:
        logger.debug("PBI: datasources erro — %s", exc)

    # 4) upstreamDatasets (pais) → datasources dos pais
    parents = _list_upstream_datasets(dataset_id, ds_group_id, headers)
    agg: list[dict] = []
    for p in parents:
        try:
            url_p = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{p}/datasources"
            rp = _request("GET", url_p, headers=headers)
            logger.log(_api_level(), "PBI: datasources(pai) HTTP %s (group %s/dataset %s)", rp.status_code, ds_group_id, p)
            if rp.ok:
                agg.extend(_extract_dataflows_from_datasources(rp.json() or {}, ds_group_id))
        except requests.RequestException as exc:
            logger.debug("PBI: datasources(pai) erro — %s", exc)
    agg = _dedup(agg)
    if agg:
        return agg

    # 5) Hints por nome
    name_hints = _name_hints_for(report_id, dataset_id)
    if name_hints:
        matched = _match_dataflows_by_name(ds_group_id, headers, name_hints)
        if matched:
            logger.debug("PBI: fallback Gen1 por HINT de nome → %s", [f"{m['group_id']}/{m['dataflow_id']}" for m in matched])
            return matched

    # 6) Singleton/All fallbacks
    try_singleton = bool(getattr(settings, "POWERBI_FALLBACK_REFRESH_SINGLETON", False))
    try_refresh_all = bool(getattr(settings, "POWERBI_FALLBACK_REFRESH_ALL", False))
    dflist = _list_workspace_dataflows(ds_group_id, headers)

    if try_singleton and isinstance(dflist, dict) and dflist.get("items") and len(dflist["items"]) == 1:
        item = dflist["items"][0]
        return [{"group_id": ds_group_id, "dataflow_id": item["dataflow_id"]}]

    if try_refresh_all and isinstance(dflist, dict) and dflist.get("items"):
        return [{"group_id": ds_group_id, "dataflow_id": d["dataflow_id"]} for d in dflist["items"]]

    logger.debug("PBI: nenhum dataflow upstream identificado (Gen1) após fallbacks.")
    return []

# --------- Override por settings -------------
def _normalize_override_items(items, default_group_id: str) -> list[dict]:
    out: list[dict] = []
    if not items:
        return out
    if isinstance(items, (str, dict)):
        items = [items]
    for it in items:
        if isinstance(it, str):
            out.append({"group_id": str(default_group_id).lower(), "dataflow_id": str(it).lower()})
        elif isinstance(it, dict):
            df = it.get("dataflow_id") or it.get("id") or it.get("objectId")
            gid = it.get("group_id") or it.get("workspaceId") or it.get("groupId") or default_group_id
            if df:
                out.append({"group_id": str(gid or default_group_id).lower(), "dataflow_id": str(df).lower()})
    return _dedup(out)

def _load_upstream_override(report_id: str, dataset_id: str, default_group_id: str) -> list[dict]:
    """Override por settings.POWERBI_UPSTREAM_DATAFLOWS_OVERRIDE."""
    conf = getattr(settings, "POWERBI_UPSTREAM_DATAFLOWS_OVERRIDE", None)
    if conf is None:
        return []
    if isinstance(conf, dict) and ("by_report" not in conf and "by_dataset" not in conf and "global" not in conf):
        items = conf.get(dataset_id) or conf.get(report_id) or []
        return _normalize_override_items(items, default_group_id)
    items = []
    if isinstance(conf, dict):
        by_ds = conf.get("by_dataset") or {}
        by_rp = conf.get("by_report") or {}
        glob = conf.get("global") or []
        items = by_ds.get(dataset_id) or by_rp.get(report_id) or glob
    return _normalize_override_items(items, default_group_id)

# --------- APIs públicas de descoberta/acionamento -------------
def find_upstream_dataflows_for_report(report_id: str, report_group_id: str) -> list[dict]:
    """
    UI-only por padrão: retorna SOMENTE os dataflows configurados no BD (tela de edição).
    Caso queira permitir descoberta automática + settings, habilite:
      settings.POWERBI_ENABLE_AUTO_DISCOVERY = True
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("PBI: find_upstream_dataflows – sem_access_token")
        return []
    headers = _auth_headers(access_token)

    ids = _resolve_dataset_ids(report_id, report_group_id, headers)
    if not ids:
        return []
    dataset_id, ds_group_id = ids

    ui_only = not bool(getattr(settings, "POWERBI_ENABLE_AUTO_DISCOVERY", False))
    over_db = _load_upstream_override_db(report_id, dataset_id, ds_group_id)

    if ui_only:
        logger.debug("PBI: UI-only ativo — upstream via BD → %s", [f"{o['group_id']}/{o['dataflow_id']}" for o in over_db] or "[]")
        return _dedup(over_db)

    ups = _discover_upstream_dataflows(dataset_id, ds_group_id, headers, report_id=report_id)
    over_st = _load_upstream_override(report_id, dataset_id, ds_group_id)
    merged = _dedup([*ups, *over_db, *over_st])
    logger.debug("PBI: upstream (discovery+UI+settings) → %s", [f"{u['group_id']}/{u['dataflow_id']}" for u in merged])
    return merged

def trigger_dataflow_refresh(group_id: str, dataflow_id: str) -> tuple[bool, str]:
    """
    Dispara refresh de um dataflow específico.
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return False, "sem_access_token"
    headers = _auth_headers(access_token, {"Content-Type": "application/json"})
    group_id = str(group_id).lower()
    dataflow_id = str(dataflow_id).lower()

    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/dataflows/{dataflow_id}/refreshes"
    logger.log(_api_level(), "PBI: POST refresh dataflow url=%s", url)
    try:
        r = _request("POST", url, json_body={}, headers=headers)
        if r.status_code == 401:
            access_token2 = get_powerbi_access_token()
            if access_token2:
                r = _request("POST", url, json_body={}, headers=_auth_headers(access_token2, {"Content-Type": "application/json"}))
        logger.log(_api_level(), "PBI: refresh dataflow HTTP %s", r.status_code)
        if r.status_code in (200, 202):
            logger.info("PBI: refresh acionado para dataflow %s (group %s)", dataflow_id, group_id)
            return True, "accepted"
        try:
            j = r.json()
        except Exception:
            j = {}
        code, msg = _parse_service_error(j)

        # ➜ Melhorias:
        # - 400 CdsaModelIsAlreadyRefreshing conta como "ok"
        if code == "CdsaModelIsAlreadyRefreshing":
            logger.info("PBI: dataflow %s já estava em refresh — tratando como aceito.", dataflow_id)
            return True, "already_in_progress"
        # - 403 CdsaWorkloadDisabled: detalhe explícito
        if code == "CdsaWorkloadDisabled":
            logger.error("PBI: capacity sem workload de dataflows habilitada.")
            return False, f"http_{r.status_code}:{code} — {msg[:300] if msg else ''}"

        detail = f"http_{r.status_code}"
        if code:
            detail += f":{code}"
        if msg:
            detail += f" — {msg[:300]}"
        logger.error("PBI: refresh dataflow falhou %s — %s", r.status_code, j)
        return False, detail
    except requests.RequestException as exc:
        logger.error("PBI: erro POST refresh dataflow — %s", exc)
        return False, "request_exception"


# --------- Espera por dataflows (polling) -------------
# Estados terminais/progresso (inclui variações vistas na prática)
_DF_TERMINAL = {"Success", "Succeeded", "Completed", "Failed", "Cancelled"}
_DF_PROGRESS = {"InProgress", "Running", "Queued", "NotStarted", ""}

def _canon_df_status(s: str) -> str:
    """
    Normaliza variações de status vindas da API (Gen1/Gen2):
    Success/Succeeded/Completed → Success; Running → InProgress; etc.
    """
    key = (s or "").replace(" ", "").lower()
    mapping = {
        "success": "Success",
        "succeeded": "Success",
        "completed": "Success",
        "failed": "Failed",
        "error": "Failed",
        "cancelled": "Cancelled",
        "canceled": "Cancelled",
        "inprogress": "InProgress",
        "running": "InProgress",
        "queued": "Queued",
        "notstarted": "NotStarted",
    }
    return mapping.get(key, s or "")

def _get_latest_dataflow_tx(group_id: str, dataflow_id: str, headers: dict) -> dict:
    """
    Lê o último transaction do dataflow e retorna {'status','startTime','endTime'} (strings).
    """
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/dataflows/{dataflow_id}/transactions?$top=1"
    try:
        r = _request("GET", url, headers=headers)
        logger.log(_api_level(), "PBI: dataflow tx HTTP %s (%s/%s)", r.status_code, group_id, dataflow_id)
        if not r.ok:
            return {"status": "", "startTime": "", "endTime": ""}
        rows = (r.json() or {}).get("value") or []
        last = rows[0] if rows else {}
        return {
            "status": (last.get("status") or "").strip(),
            "startTime": (last.get("startTime") or "").strip(),
            "endTime": (last.get("endTime") or "").strip(),
        }
    except requests.RequestException as exc:
        logger.debug("PBI: dataflow tx request_exception — %s", exc)
        return {"status": "", "startTime": "", "endTime": ""}

def _to_dt(s: str) -> Optional[timezone.datetime]:
    if not s:
        return None
    d = parse_datetime(s)
    if not d:
        return None
    return d if timezone.is_aware(d) else d.replace(tzinfo=dt.timezone.utc)

def _to_utc_naive_any(d: Optional[timezone.datetime]) -> Optional[dt.datetime]:
    """
    Converte qualquer datetime (aware ou naive) para UTC 'naive'.
    - Se for aware, converte para UTC e zera tzinfo.
    - Se for naive, assume timezone atual do Django (local) antes de converter.
    """
    if not d:
        return None
    if timezone.is_aware(d):
        aware = d
    else:
        try:
            aware = timezone.make_aware(d, timezone.get_current_timezone())
        except Exception:
            # Fallback extremo: trata como UTC
            aware = d.replace(tzinfo=dt.timezone.utc)
    return aware.astimezone(dt.timezone.utc).replace(tzinfo=None)

def _wait_for_dataflows(
    upstream: list[dict],
    headers: dict,
    *,
    timeout_s: int = 1800,
    poll_s: int = 15,
    started_after: Optional[timezone.datetime] = None,
    prev_tx_end: Optional[dict[tuple[str, str], timezone.datetime]] = None,
) -> list[dict]:
    """
    Espera todos os dataflows alcançarem estado terminal. Retorna lista com status final por DF:
    [{'group_id', 'dataflow_id', 'status', 'startTime', 'endTime'}]

    Regras atualizadas (anti-match de execução antiga):
      - Um transaction é considerado "nosso" somente se:
          (start >= started_after - START_GUARD_NEG_S  OU  end >= started_after - START_GUARD_NEG_S)
        E também (quando houver linha de base de execução anterior)
          (start >= prev_end + END_GUARD_POS_S  OU  end >= prev_end + END_GUARD_POS_S).

      - Pequeno atraso inicial para o serviço materializar o transaction:
          settings.POWERBI_DF_CREATE_TX_DELAY_S (default 2s).

    Settings opcionais:
      POWERBI_DF_START_GUARD_NEG_S = 10   # tolera até 10s “antes” do started_after
      POWERBI_DF_END_GUARD_POS_S   = 1    # exige > último end conhecido + 1s
      POWERBI_DF_CREATE_TX_DELAY_S = 2    # aguarda 2s antes do primeiro GET
    """
    start_guard_neg_s = int(getattr(settings, "POWERBI_DF_START_GUARD_NEG_S", 10))
    end_guard_pos_s   = int(getattr(settings, "POWERBI_DF_END_GUARD_POS_S", 1))
    create_delay_s    = int(getattr(settings, "POWERBI_DF_CREATE_TX_DELAY_S", 2))

    # Base started_after normalizada para UTC naive
    started_after_base_utc = None
    if started_after:
        if timezone.is_naive(started_after):
            try:
                started_after = timezone.make_aware(started_after, timezone.get_current_timezone())
            except Exception:
                started_after = started_after.replace(tzinfo=dt.timezone.utc)
        started_after_base_utc = _to_utc_naive_any(started_after - dt.timedelta(seconds=start_guard_neg_s))

    # Mapa de último end conhecido (UTC naive) por DF
    prev_end_map_utc: dict[tuple[str, str], Optional[dt.datetime]] = {}
    for u in upstream:
        k = (u["group_id"], u["dataflow_id"])
        p = (prev_tx_end or {}).get(k)
        prev_end_map_utc[k] = _to_utc_naive_any(p) if p else None

    logger.debug(
        "DF-WAIT: guards start_neg=%ss end_pos=%ss create_delay=%ss | started_after_base_utc=%s",
        start_guard_neg_s, end_guard_pos_s, create_delay_s, started_after_base_utc
    )

    if create_delay_s > 0:
        time.sleep(create_delay_s)

    deadline = time.time() + int(timeout_s)
    status_map: dict[tuple[str, str], dict] = {(u["group_id"], u["dataflow_id"]): {"status": ""} for u in upstream}

    def _qualifies(tx: dict, key: tuple[str, str]) -> bool:
        sdt = _to_dt(tx.get("startTime") or "")
        edt = _to_dt(tx.get("endTime") or "")
        sdt_n = _to_utc_naive_any(sdt)
        edt_n = _to_utc_naive_any(edt)

        cond_started_after = True
        if started_after_base_utc is not None:
            cond_started_after = (sdt_n and sdt_n >= started_after_base_utc) or (edt_n and edt_n >= started_after_base_utc)

        cond_prev = True
        base_prev = prev_end_map_utc.get(key)
        if base_prev:
            edge = base_prev + dt.timedelta(seconds=end_guard_pos_s)
            cond_prev = (sdt_n and sdt_n >= edge) or (edt_n and edt_n >= edge)

        return bool(cond_started_after and cond_prev)

    all_done = False
    while time.time() < deadline:
        all_done = True
        for u in upstream:
            k = (u["group_id"], u["dataflow_id"])
            tx = _get_latest_dataflow_tx(u["group_id"], u["dataflow_id"], headers)
            st = _canon_df_status(tx.get("status") or "")
            s_raw = tx.get("startTime") or ""
            e_raw = tx.get("endTime") or ""

            if not _qualifies(tx, k):
                logger.debug(
                    "DF-WAIT: ignorando tx não qualificado %s/%s status=%s start=%s end=%s "
                    "(started_after_base=%s prev_end=%s +%ss)",
                    u["group_id"], u["dataflow_id"], st, s_raw, e_raw,
                    started_after_base_utc, prev_end_map_utc.get(k), end_guard_pos_s
                )
                all_done = False
                continue

            status_map[k] = {**u, **tx, "status": st}
            logger.debug(
                "DF-WAIT: tx atual %s/%s status=%s start=%s end=%s (qualificado)",
                u["group_id"], u["dataflow_id"], st, s_raw, e_raw
            )

            if st not in _DF_TERMINAL:
                all_done = False

        if all_done:
            logger.info("DF-WAIT: todos os dataflows atingiram estado terminal.")
            break
        time.sleep(int(poll_s))

    if not all_done:
        logger.warning("DF-WAIT: timeout atingido após %ss — seguindo para o dataset mesmo assim.", int(timeout_s))

    # formata saída
    out = []
    for u in upstream:
        k = (u["group_id"], u["dataflow_id"])
        rec = status_map.get(k, {**u, "status": ""})
        if {"status", "startTime", "endTime"} <= rec.keys():
            out.append(rec)
        else:
            out.append({**u, "status": ""})
    return out


def cascade_refresh(
    report_id: str,
    report_group_id: str,
    refresh_type: str = "Full",
    *,
    wait_for_dataflows: bool = False,
    df_timeout_s: int = 1800,
    poll_every_s: int = 15,
    fail_on_dataflow_error: bool = True,
) -> dict:
    """
    Dispara refresh dos dataflows upstream (se houver) e depois do dataset.
    Por padrão NÃO aguarda conclusão (compatibilidade). Se wait_for_dataflows=True, só dispara
    o dataset após todos os dataflows chegarem a estado terminal.

    Retorno:
      {
        "ok": True|False,  # ← reflete o resultado do dataset e, se aguardado, o status dos dataflows
        "dataflows": [{"group_id","dataflow_id","ok","detail"}],
        "dataflows_status": [{"group_id","dataflow_id","status","startTime","endTime"}],  # vazio se não aguardou
        "dataset": {"ok": bool, "detail": str}
      }
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return {"ok": False, "error": "sem_access_token"}
    headers = _auth_headers(access_token)

    ids = _resolve_dataset_ids(report_id, report_group_id, headers)
    if not ids:
        return {"ok": False, "error": "dataset_nao_encontrado"}
    dataset_id, ds_group_id = ids
    logger.debug("PBI: cascade para dataset=%s ds_group=%s (report_group=%s)", dataset_id, ds_group_id, report_group_id)

    override_db = _load_upstream_override_db(report_id, dataset_id, ds_group_id)
    upstream = _dedup(override_db)

    if not upstream:
        logger.debug("PBI: nenhum upstream configurado via UI — somente dataset.")
    else:
        logger.debug("PBI: upstream via UI → %s", [f"{u['group_id']}/{u['dataflow_id']}" for u in upstream])

    # 1) Dispara todos os dataflows
    results = []

    # tolerância mínima para evitar race entre nosso "agora" e o carimbo do serviço
    _start_tol = int(getattr(settings, "POWERBI_DF_START_TOLERANCE_S", 5))
    started_after = timezone.now() - dt.timedelta(seconds=_start_tol)
    if timezone.is_naive(started_after):
        try:
            started_after = timezone.make_aware(started_after, timezone.get_current_timezone())
        except Exception:
            started_after = started_after.replace(tzinfo=dt.timezone.utc)

    # Baseline do último transaction *antes* do POST (anti-match de execuções antigas)
    prev_tx_end: dict[tuple[str, str], timezone.datetime] = {}
    for u in upstream:
        prev_tx = _get_latest_dataflow_tx(u["group_id"], u["dataflow_id"], headers)
        end_dt = _to_dt(prev_tx.get("endTime") or "") or _to_dt(prev_tx.get("startTime") or "")
        if end_dt:
            prev_tx_end[(u["group_id"], u["dataflow_id"])] = end_dt

    for u in upstream:
        ok, detail = trigger_dataflow_refresh(u["group_id"], u["dataflow_id"])
        results.append({"group_id": u["group_id"], "dataflow_id": u["dataflow_id"], "ok": ok, "detail": detail})

    # 2) (Opcional) esperar os dataflows concluírem
    df_status: list[dict] = []
    if wait_for_dataflows and upstream:
        # Atalho: se nenhum DF foi aceito e todos falharam por workload desabilitada, não faz sentido esperar
        any_ok = any(r.get("ok") for r in results)
        all_wd = (not any_ok) and all(
            (isinstance(r.get("detail"), str) and "CdsaWorkloadDisabled" in r["detail"])
            for r in results
        )
        if all_wd:
            logger.warning("PBI: todos dataflows com workload desabilitada — pulando espera e seguindo para dataset.")
        else:
            df_status = _wait_for_dataflows(
                upstream,
                headers,
                timeout_s=df_timeout_s,
                poll_s=poll_every_s,
                started_after=started_after,
                prev_tx_end=prev_tx_end,  # ← linha de base para garantir transaction *novo*
            )
            if fail_on_dataflow_error and any(d.get("status") in {"Failed", "Cancelled"} for d in df_status):
                return {
                    "ok": False,
                    "dataflows": results,
                    "dataflows_status": df_status,
                    "dataset": {"ok": False, "detail": "skipped_due_to_dataflow_error"},
                }

    # 3) Dispara o dataset
    d_ok, d_detail = trigger_dataset_refresh(report_id, report_group_id, refresh_type=refresh_type)

    return {
        "ok": bool(d_ok),  # ← importante p/ o front decidir 202/400 (views)
        "dataflows": results,
        "dataflows_status": df_status,
        "dataset": {"ok": d_ok, "detail": d_detail},
    }


# ════════════════════════════════════════
# 9) Utilitários extras para o endpoint de status unificado
# ════════════════════════════════════════

def get_dataset_refreshes(*, group_id: str, dataset_id: str, after_epoch: Optional[int] = None, top: int = 5) -> list[dict]:
    """
    Retorna os últimos refreshes do DATASET (lista de dicts "value-like").
    Normaliza times em epoch e inclui o label 'refresh_type'.
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return []
    headers = _auth_headers(access_token)
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/datasets/{dataset_id}/refreshes?$top={int(top)}"
    try:
        r = _request("GET", url, headers=headers)
        if not r.ok:
            return []
        vals = (r.json() or {}).get("value") or []
        out: list[dict] = []
        base = int(after_epoch or 0)
        guard_neg = int(getattr(settings, "POWERBI_REFRESH_START_GUARD_NEG_S", 10))
        base_cmp = max(0, base - guard_neg)

        for it in vals:
            st = (it.get("status") or "").strip()
            sdt = _parse_pbi_dt_to_utc(it.get("startTime"))
            edt = _parse_pbi_dt_to_utc(it.get("endTime"))
            se = int(sdt.timestamp()) if sdt else None
            ee = int(edt.timestamp()) if edt else None
            if base:
                if not ((se and se >= base_cmp) or (ee and ee >= base_cmp)):
                    # ignora execuções antigas se after_epoch foi informado
                    continue
            out.append({
                **it,
                "status": st,
                "start_epoch": se,
                "end_epoch": ee,
                "refresh_type": _infer_refresh_type(it),
            })
        return out
    except requests.RequestException:
        return []

def get_dataset_last_update_epoch(*, group_id: str, dataset_id: str) -> Optional[int]:
    """
    Epoch do último refresh *concluído* do dataset.
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return None
    headers = _auth_headers(access_token)
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/datasets/{dataset_id}/refreshes?$top=50"
    try:
        r = _request("GET", url, headers=headers)
        if not r.ok:
            return None
        dt_last = _pick_newest_refresh_dt((r.json() or {}).get("value", []))
        return int(dt_last.timestamp()) if dt_last else None
    except requests.RequestException:
        return None

def get_dataflow_refreshes(*, group_id: str, dataset_id: str, after_epoch: Optional[int] = None, report_id: str = "") -> list[dict]:
    """
    Descobre dataflows *upstream* do dataset e retorna um snapshot dos últimos transactions
    (útil para exibir “in progress (via PowerBI Web)” mesmo antes do dataset).
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return []
    headers = _auth_headers(access_token)

    # Descoberta de upstreams (não depende de report_id; passamos vazio só para hints por nome)
    ups = _discover_upstream_dataflows(dataset_id, group_id, headers, report_id=report_id)
    if not ups:
        return []

    base = int(after_epoch or 0)
    guard_neg = int(getattr(settings, "POWERBI_DF_START_GUARD_NEG_S", 10))
    base_cmp = max(0, base - guard_neg)

    out: list[dict] = []
    for u in ups:
        tx = _get_latest_dataflow_tx(u["group_id"], u["dataflow_id"], headers)
        st = _canon_df_status(tx.get("status") or "")
        sdt = _to_dt(tx.get("startTime") or "")
        edt = _to_dt(tx.get("endTime") or "")
        se = int(sdt.timestamp()) if sdt else None
        ee = int(edt.timestamp()) if edt else None
        if base:
            if not ((se and se >= base_cmp) or (ee and ee >= base_cmp)):
                # ignora execuções antigas se after_epoch foi informado
                pass  # ainda incluiremos para sinalizar “não qualificado”, mas sem filtrar duro
        out.append({
            "kind": "dataflow",
            "group_id": u["group_id"],
            "dataflow_id": u["dataflow_id"],
            "status": st or "",
            "start_epoch": se,
            "end_epoch": ee,
            "refresh_type": "scheduled",  # DF não expõe ViaApi/Scheduled de forma consistente; tratamos como “do serviço”
        })
    return out
