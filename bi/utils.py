# bi/utils.py
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Dict, Optional

import datetime as dt

import msal
import requests
from django.conf import settings
from django.core.cache import cache  # aponte para Redis em settings.py
from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

# ════════════════════════════════════════
# 1) AUTH – access_token via Service Principal (client_credentials)
# ════════════════════════════════════════
_token_cache: Dict[str, Any] = {}
_EXP: Optional[float] = None  # expiração do access_token (epoch seg)


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
    Requer:
      - POWERBI_TENANT_ID
      - POWERBI_CLIENT_ID
      - POWERBI_CLIENT_SECRET
      - POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
    """
    logger.info("PBI-Auth: client_credentials (service principal).")
    app = msal.ConfidentialClientApplication(
        client_id=settings.POWERBI_CLIENT_ID,
        client_credential=settings.POWERBI_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.POWERBI_TENANT_ID}",
    )
    res = app.acquire_token_for_client(scopes=[settings.POWERBI_SCOPE])
    if "access_token" in res:
        _save_tokens(res)
        return res
    logger.error(
        "PBI-Auth: falha client_credentials – %s | %s",
        res.get("error"),
        res.get("error_description"),
    )
    return None


def get_powerbi_access_token() -> Optional[str]:
    """
    Retorna um access_token válido para chamar as APIs do Power BI.
    Somente client_credentials (sem ROPC/refresh_token).
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


# ------------ util para TTL (token com 2+ segmentos) ---------------
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

    meta = info.json()
    embed_url = meta.get("embedUrl")
    report_name = meta.get("name", report_id)
    dataset_id = meta.get("datasetId")

    # 1.1  log de flags do dataset (útil para debugar RLS/identities)
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

    # 2️⃣  GenerateToken (somente View; adicione identities aqui se usar RLS)
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
        "embed_url": embed_url,
        "embed_token": embed_token,
        "report_name": report_name,
    }


# ------------ API pública usada pelas views -----------------------
def get_embed_params_user_owns_data(report_id: str, group_id: str) -> Optional[dict]:
    """
    Retorna {embed_url, embed_token, report_name} para um report.
    Usa cache (Django cache) e renova o token se ele estiver a <5 min de expirar.
    """
    cache_key = f"{_CACHE_PREFIX}{group_id}:{report_id}"
    cached: Optional[dict] = cache.get(cache_key)  # type: ignore[assignment]

    if cached and _is_token_still_safe(cached["embed_token"]):
        logger.debug(
            "PBI: [%s] embed_token vindo do cache → %s",
            cached.get("report_name", report_id),
            cache_key,
        )
        return cached
    elif cached:
        logger.info(
            "PBI: [%s] token a <5min de expirar – descartando cache.",
            cached.get("report_name", report_id),
        )

    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("PBI: falha ao obter access_token – não foi possível gerar embed_token.")
        return None

    embed = _generate_embed_token(report_id, group_id, access_token)
    if embed:
        cache.set(cache_key, embed, timeout=_EMBED_TTL)
        logger.info(
            "PBI: [%s] embed_token gerado e salvo em cache (%s s) → %s",
            embed["report_name"],
            _EMBED_TTL,
            cache_key,
        )
    return embed


# ════════════════════════════════════════
# 3) REAL-TIME – última atualização do dataset do relatório
# ════════════════════════════════════════
def _parse_pbi_dt_to_utc(dt_str: str | None) -> Optional[timezone.datetime]:
    """
    Converte string ISO do Power BI para datetime aware em UTC.
    Aceita '...Z' (UTC), offset '+/-HH:MM' ou naive (assumimos UTC).
    """
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
    """
    Pega somente o último refresh CONCLUÍDO.
    """
    VALID = {"Completed"}  # <- antes tinha {"Completed", "Unknown"}
    newest: Optional[timezone.datetime] = None
    for r in refreshes or []:
        status = (r.get("status") or "").strip()
        if status not in VALID:
            continue
        for cand in (_parse_pbi_dt_to_utc(r.get("endTime")), _parse_pbi_dt_to_utc(r.get("startTime"))):
            if cand and (newest is None or cand > newest):
                newest = cand
    return newest



def get_report_last_refresh_time_rt(report_id: str, report_group_id: str) -> Optional[timezone.datetime]:
    """
    Busca em tempo real a última atualização do dataset do relatório.
    Resolve datasetWorkspaceId se for diferente do workspace do relatório.
    Retorna datetime aware (UTC) se USE_TZ=True; caso contrário, naive local.
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        logger.error("RT: sem access_token.")
        return None

    headers = {"Authorization": f"Bearer {access_token}"}

    # 1) Resolver datasetId + datasetWorkspaceId a partir do relatório
    try:
        list_url = f"https://api.powerbi.com/v1.0/myorg/groups/{report_group_id}/reports"
        lr = requests.get(list_url, headers=headers, timeout=15)
        lr.raise_for_status()
        items = lr.json().get("value", []) or []
        item = next((i for i in items if i.get("id") == report_id), None)
        if not item:
            logger.warning("RT: report %s não encontrado no group %s.", report_id, report_group_id)
            return None
        dataset_id = item.get("datasetId")
        ds_group_id = item.get("datasetWorkspaceId") or report_group_id
        if not dataset_id:
            logger.info("RT: report %s sem datasetId.", report_id)
            return None
    except Exception as e:
        logger.error("RT: erro listando reports para resolver datasetWorkspaceId – %s", e, exc_info=True)
        return None

    # 2) Buscar refreshes do dataset e pegar o mais recente
    try:
        ref_url = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/refreshes?$top=50"
        rr = requests.get(ref_url, headers=headers, timeout=15)
        rr.raise_for_status()
        newest = _pick_newest_refresh_dt((rr.json() or {}).get("value", []))
        if not newest:
            return None

        if not settings.USE_TZ:
            try:
                local_tz = timezone.get_current_timezone()
                return timezone.localtime(newest, local_tz).replace(tzinfo=None)
            except Exception:
                return None
        return newest
    except Exception as e:
        logger.error("RT: erro buscando refreshes – %s", e, exc_info=True)
        return None


# ════════════════════════════════════════
# 4) RESOLUÇÃO DE DATASET (report → dataset)
# ════════════════════════════════════════
def _resolve_dataset_ids(report_id: str, report_group_id: str, headers: dict) -> tuple[str, str] | None:
    """
    Retorna (dataset_id, dataset_workspace_id) a partir de um report.
    """
    try:
        list_url = f"https://api.powerbi.com/v1.0/myorg/groups/{report_group_id}/reports"
        lr = requests.get(list_url, headers=headers, timeout=15)
        lr.raise_for_status()
        items = (lr.json() or {}).get("value", []) or []
        item = next((i for i in items if i.get("id") == report_id), None)
        if not item:
            logger.warning("PBI: report %s não encontrado em group %s", report_id, report_group_id)
            return None
        dataset_id = item.get("datasetId")
        ds_group_id = item.get("datasetWorkspaceId") or report_group_id
        if not dataset_id:
            logger.warning("PBI: report %s sem datasetId", report_id)
            return None
        return dataset_id, ds_group_id
    except requests.RequestException as exc:
        logger.error("PBI: erro resolvendo datasetId/datasetWorkspaceId — %s", exc)
        return None


# ════════════════════════════════════════
# 5) REFRESH – acionar e reportar erros de forma legível
# ════════════════════════════════════════
def trigger_dataset_refresh(report_id: str, report_group_id: str, refresh_type: str = "Full") -> tuple[bool, str]:
    """
    Dispara o refresh do dataset do report.
    Requer permissões adequadas para o Service Principal no workspace/dataset.
    Retorna (ok, detalhe).
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return False, "sem_access_token"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    ids = _resolve_dataset_ids(report_id, report_group_id, headers)
    if not ids:
        return False, "dataset_nao_encontrado"
    dataset_id, ds_group_id = ids

    url = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/refreshes"
    payload = {"type": refresh_type, "notifyOption": "NoNotification"}

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code in (200, 202):
            logger.info("PBI: refresh acionado para dataset %s (group %s) [%s]", dataset_id, ds_group_id, refresh_type)
            return True, "accepted"
        else:
            try:
                j = r.json()
            except Exception:
                j = {}

            # detalhe mais legível (opcional melhorado)
            code, msg = _parse_service_error(j)
            detail = f"http_{r.status_code}"
            if code:
                detail += f":{code}"
            if msg:
                detail += f" — {msg[:300]}"  # limita tamanho

            logger.error("PBI: refresh falhou %s — %s", r.status_code, j)
            return False, detail
    except requests.RequestException as exc:
        logger.error("PBI: erro POST refresh — %s", exc)
        return False, "request_exception"


# ════════════════════════════════════════
# 6) ERROS DO SERVIÇO – parsing (opcional)
# ════════════════════════════════════════
def _parse_service_error(raw: dict) -> tuple[str, str]:
    """
    Extrai (error_code, error_message) de payloads do Power BI.
    Procura em serviceExceptionJson, error.pbi.error.details, etc.
    """
    code = ""
    msg_parts: list[str] = []

    def add(s):
        if isinstance(s, str):
            s = s.strip()
            if s and s not in msg_parts:
                msg_parts.append(s)

    # 1) formatos "normais"
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

                    # pedaços mais úteis costumam vir aqui:
                    if dcode.endswith("UnderlyingErrorMessage"):  # mensagem “de verdade”
                        add(dval)
                    elif dcode.endswith("Message"):               # outras mensagens
                        add(dval)
                    elif "Microsoft.Data.Mashup.ValueError.Detail" in dcode:  # caminho/arquivo
                        add(str(dval))
                    elif isinstance(dval, str) and dval:
                        add(dval)

    # 2) às vezes vem string JSON em serviceExceptionJson
    sj = raw.get("serviceExceptionJson")
    if isinstance(sj, str) and sj.strip():
        try:
            j = json.loads(sj)
            c2, m2 = _parse_service_error(j)  # reaproveita o parser
            code = c2 or code
            add(m2)
        except Exception:
            add(sj)

    # 3) fallbacks de código
    code = (raw.get("errorCode") or raw.get("code") or code or "").strip()

    # 4) dica amigável se ainda não achou mensagem
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


# ════════════════════════════════════════
# 7) STATUS DO REFRESH – checagem do último job (opcional)
# ════════════════════════════════════════
def get_latest_refresh_status(report_id: str, report_group_id: str) -> dict:
    """
    Lê o último refresh do dataset do report e retorna um resumo:
      {
        "ok": True,
        "status": "Completed|InProgress|Failed|Disabled|Cancelled|Unknown",
        "start_epoch":  ... (int) | None,
        "end_epoch":    ... (int) | None,
        "error_code":   "...",
        "error_message":"..."
      }
    Em falha de comunicação, retorna {"ok": False, "error": "..."}.
    """
    access_token = get_powerbi_access_token()
    if not access_token:
        return {"ok": False, "error": "sem_access_token"}

    headers = {"Authorization": f"Bearer {access_token}"}

    ids = _resolve_dataset_ids(report_id, report_group_id, headers)
    if not ids:
        return {"ok": False, "error": "dataset_nao_encontrado"}

    dataset_id, ds_group_id = ids
    url = f"https://api.powerbi.com/v1.0/myorg/groups/{ds_group_id}/datasets/{dataset_id}/refreshes?$top=1"

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json() or {}
        rows = data.get("value") or []
        last = rows[0] if rows else {}

        status = (last.get("status") or "Unknown").strip()
        start_dt = _parse_pbi_dt_to_utc(last.get("startTime"))
        end_dt = _parse_pbi_dt_to_utc(last.get("endTime"))

        error_code, error_message = _parse_service_error(last)

        # Retorno padronizado
        return {
            "ok": True,
            "status": status,
            "start_epoch": int(start_dt.timestamp()) if start_dt else None,
            "end_epoch": int(end_dt.timestamp()) if end_dt else None,
            "error_code": error_code,
            "error_message": error_message,
        }
    except requests.RequestException as exc:
        logger.error("PBI: erro lendo refreshes — %s", exc)
        return {"ok": False, "error": "request_exception"}
    except Exception:
        logger.exception("PBI: exceção inesperada lendo refreshes")
        return {"ok": False, "error": "internal_error"}
