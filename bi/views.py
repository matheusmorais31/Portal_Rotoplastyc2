# bi/views.py – Django views para módulo BI com persistência de estado + LOG de atualização
from __future__ import annotations

import json
import time
import logging
import re
import uuid
from itertools import chain
from typing import Any, Dict

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.db.models import F, Value, CharField, IntegerField, Q
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods, require_GET

from .forms import BIReportForm, BIReportEditForm
from .models import BIReport, BIAccess, BIUserReportState, BISavedView
from .utils import (
    get_embed_params_user_owns_data,
    get_latest_refresh_status,
    get_report_last_refresh_time_rt,
    trigger_dataset_refresh,
    cascade_refresh,
    list_workspace_dataflows,   # <- wrapper público no utils
)

# ─────────────────────────────────────────────────────────────────────────────
# Loggers
# ─────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger("bi")                 # logger “geral” — silenciado abaixo
update_logger = logging.getLogger("bi.update")   # ÚNICO logger ativo (apenas atualização)

# Silencia totalmente o logger "bi" neste módulo
def _noop(*args, **kwargs):
    pass

logger.debug = _noop
logger.info = _noop
logger.warning = _noop
logger.error = _noop
logger.exception = _noop

_GUID = r"[0-9a-fA-F-]{36}"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _meta_from_request(request) -> Dict[str, Any]:
    META = request.META
    return {
        "path": request.path,
        "method": request.method,
        "user": getattr(request.user, "username", None),
        "is_auth": bool(getattr(request.user, "is_authenticated", False)),
        "ip": META.get("REMOTE_ADDR") or META.get("HTTP_X_FORWARDED_FOR"),
        "ua": META.get("HTTP_USER_AGENT"),
        "ct": META.get("CONTENT_TYPE"),
        "cl": META.get("CONTENT_LENGTH"),
        "referer": META.get("HTTP_REFERER"),
        "origin": META.get("HTTP_ORIGIN"),
        "host": META.get("HTTP_HOST"),
    }


def _summarize_state(state: dict) -> Dict[str, Any]:
    if not isinstance(state, dict):
        return {"type": type(state).__name__}
    filters_count = len(state.get("reportFilters", []) or [])
    active_page = state.get("activePage")
    slicers = state.get("slicers") or {}
    slicer_pages = len(slicers) if isinstance(slicers, dict) else 0
    slicer_visuals = sum(len(v) for v in slicers.values() if isinstance(v, dict))
    return {
        "filters_count": filters_count,
        "active_page": active_page,
        "slicer_pages": slicer_pages,
        "slicer_visuals": slicer_visuals,
        "keys": list(state.keys()),
    }


def _perm_check(user, bi_report) -> bool:
    return (
        bi_report.all_users
        or bi_report.allowed_users.filter(id=user.id).exists()
        or Group.objects.filter(
            id__in=bi_report.allowed_groups.values_list("id", flat=True), user=user
        ).exists()
    )


def _extract_group_report_from_embed(embed_code: str) -> tuple[str | None, str | None]:
    """
    Tenta achar .../groups/<gid>/reports/<rid> no embed_code.
    """
    if not embed_code:
        return None, None
    m = re.search(rf"/groups/({_GUID})/reports/({_GUID})", embed_code or "", re.I)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _log_update_event(user, bi_title, report_id, group_id, result: dict, refresh_type: str):
    """
    Log ÚNICO de atualização:
      - DATASET_REFRESH (sempre)
      - DATAFLOW_REFRESH (uma linha por dataflow disparado)
    Campos: ts (hora), user, report_title/id, group_id, dataflow_id (quando houver), ok, detail.
    """
    ts = timezone.now().isoformat()
    username = getattr(user, "username", "anon")

    # Dataset
    d = (result or {}).get("dataset") or {}
    update_logger.info(
        "DATASET_REFRESH | ts=%s | user=%s | report_title=%s | report_id=%s | group_id=%s | type=%s | ok=%s | detail=%s",
        ts, username, bi_title, report_id, group_id, refresh_type, d.get("ok"), (d.get("detail") or ""),
    )

    # Dataflows
    for df in (result or {}).get("dataflows") or []:
        update_logger.info(
            "DATAFLOW_REFRESH | ts=%s | user=%s | report_title=%s | group_id=%s | dataflow_id=%s | ok=%s | detail=%s",
            ts, username, bi_title, df.get("group_id"), df.get("dataflow_id"), df.get("ok"), (df.get("detail") or ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# CRUD / LISTAS
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def create_bi_report(request):
    if request.method == "POST":
        form = BIReportForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Relatório cadastrado com sucesso.")
            return redirect("bi:bi_report_list")
    else:
        form = BIReportForm()
    return render(request, "bi/criar_bi.html", {"form": form})


@login_required
@permission_required("bi.edit_bi", raise_exception=True)
def edit_bi_report(request, pk):
    bi_report = get_object_or_404(BIReport, pk=pk)

    # Tenta extrair group/report do embed apenas se estiverem ausentes
    if (not getattr(bi_report, "group_id", None)) or (not getattr(bi_report, "report_id", None)):
        gid, rid = _extract_group_report_from_embed(bi_report.embed_code or "")
        if gid and not bi_report.group_id:
            bi_report.group_id = gid
        if rid and not bi_report.report_id:
            bi_report.report_id = rid
        try:
            bi_report.save(update_fields=["group_id", "report_id"])
        except Exception:
            pass

    # Compat p/ template (somente para render)
    setattr(bi_report, "pbi_group_id", getattr(bi_report, "group_id", None))
    setattr(bi_report, "pbi_report_id", getattr(bi_report, "report_id", None))

    if request.method == "POST":
        # 1) SEMPRE captura e normaliza os dataflows vindos da UI
        raw = request.POST.get("upstream_dataflows_json") or "[]"
        try:
            selected = json.loads(raw)
        except Exception:
            selected = []

        norm = []
        # fallback seguro para workspace
        effective_gid = getattr(bi_report, "pbi_group_id", None) or bi_report.group_id or ""
        for it in (selected if isinstance(selected, list) else []):
            df = (it.get("dataflow_id") or it.get("id") or "").strip()
            gid = (it.get("group_id") or effective_gid).strip()
            name = (it.get("name") or "").strip()
            if df and gid:
                # 🔽 normalize GUIDs para casar sempre com a lista renderizada
                item = {"group_id": gid.lower(), "dataflow_id": df.lower()}
                if name:
                    item["name"] = name
                norm.append(item)

        # Persiste imediatamente a seleção, mesmo que o form dê inválido
        if norm != (bi_report.upstream_dataflows or []):
            BIReport.objects.filter(pk=bi_report.pk).update(upstream_dataflows=norm)
            # reflete no objeto em memória também
            bi_report.upstream_dataflows = norm

        # 2) Processa o form normalmente (apenas campos realmente editáveis)
        form = BIReportEditForm(request.POST, instance=bi_report)

        if form.is_valid():
            rpt = form.save(commit=False)

            # Mantém campos travados
            rpt.title      = bi_report.title
            rpt.embed_code = bi_report.embed_code
            rpt.report_id  = bi_report.report_id
            rpt.group_id   = bi_report.group_id
            rpt.dataset_id = bi_report.dataset_id

            # Garante que os dataflows (norm) também fiquem no instance salvo agora
            rpt.upstream_dataflows = norm
            rpt.save()

            # Permissões
            if rpt.all_users:
                rpt.allowed_users.clear()
                rpt.allowed_groups.clear()
            else:
                rpt.allowed_users.set(request.POST.getlist("allowed_users"))
                rpt.allowed_groups.set(request.POST.getlist("allowed_groups"))

            messages.success(request, "Relatório atualizado.")
            return redirect("bi:bi_report_list")

        else:
            # Form inválido — a seleção de dataflows já está salva.
            messages.error(request, "Erros no formulário. As seleções de Dataflow foram salvas.")

    else:
        form = BIReportEditForm(instance=bi_report)

    # ATENÇÃO: o template correto aqui é "bi/editar_bi.html"
    # Envia também o JSON serializado para o front usar diretamente (evita parse de repr Python)
    return render(
        request,
        "bi/editar_bi.html",
        {
            "form": form,
            "bi_report": bi_report,
            "upstream_dataflows_json": json.dumps(bi_report.upstream_dataflows or [], ensure_ascii=False),
        },
    )


@login_required
@permission_required("bi.view_bi", raise_exception=True)
def bi_report_list(request):
    bi_reports = BIReport.objects.all().prefetch_related("allowed_users", "allowed_groups")
    return render(request, "bi/listar_bi.html", {"bi_reports": bi_reports})


@login_required
def my_bi_report_list(request):
    user = request.user
    bi_reports = (
        BIReport.objects.filter(
            Q(all_users=True) | Q(allowed_users=user) | Q(allowed_groups__in=user.groups.all())
        )
        .distinct()
        .prefetch_related("allowed_users", "allowed_groups")
    )
    return render(request, "bi/listar_bi.html", {"bi_reports": bi_reports})


# ─────────────────────────────────────────────────────────────────────────────
# DETALHE + ESTADO (com suporte a ?view=<token> para visões salvas)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def bi_report_detail(request, pk):
    trace_id = str(uuid.uuid4())
    bi_report = get_object_or_404(BIReport, pk=pk)
    user = request.user

    if not _perm_check(user, bi_report):
        messages.error(request, "Você não tem permissão para este relatório.")
        return render(request, "bi/403.html")

    BIAccess.objects.create(bi_report=bi_report, user=user)

    embed = get_embed_params_user_owns_data(
        report_id=bi_report.report_id, group_id=bi_report.group_id
    )
    if not embed:
        messages.error(request, "Não foi possível gerar o embed do relatório.")
        return render(
            request, "bi/erro_ao_carregar_relatorio.html", {"trace_id": trace_id}
        )

    # Estado padrão: último estado do usuário
    state_obj = BIUserReportState.objects.filter(user=user, bi_report=bi_report).first()
    last_state = state_obj.state if state_obj else {}
    last_state_updated_at = state_obj.updated_at.isoformat() if state_obj else ""

    # Override por visão compartilhada via token
    token = (request.GET.get("view") or "").strip()
    if token:
        sv = BISavedView.objects.filter(bi_report=bi_report, share_token=token).first()
        if sv and sv.can_view(user):
            last_state = sv.state or {}
            last_state_updated_at = sv.updated_at.isoformat()

    context = {
        "bi_report": bi_report,
        "embed_url": embed["embed_url"],
        "embed_token": embed["embed_token"],
        "initial_state_json": json.dumps(last_state, ensure_ascii=False),
        "initial_state_updated_at": last_state_updated_at,
        "trace_id": trace_id,
    }
    return render(request, "bi/visualizar_bi.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# AJAX – token
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
@login_required
def get_embed_params(request):
    trace_id = str(uuid.uuid4())
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido.", "trace_id": trace_id}, status=400)

    report_id = data.get("report_id")
    group_id = data.get("group_id")

    if not (report_id and group_id):
        return JsonResponse({"error": "Parâmetros ausentes.", "trace_id": trace_id}, status=400)

    bi_report = get_object_or_404(BIReport, report_id=report_id, group_id=group_id)
    if not _perm_check(request.user, bi_report):
        return JsonResponse({"error": "Acesso negado.", "trace_id": trace_id}, status=403)

    embed = get_embed_params_user_owns_data(report_id, group_id)
    if not embed:
        return JsonResponse({"error": "Falha ao gerar token.", "trace_id": trace_id}, status=500)

    embed["trace_id"] = trace_id
    return JsonResponse(embed)


# ─────────────────────────────────────────────────────────────────────────────
# AJAX – salvar estado (tolerante a unload)
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_POST
@login_required
def salvar_estado_relatorio(request):
    trace_id = str(uuid.uuid4())

    try:
        raw = request.body.decode("utf-8") if request.body else "{}"
        data = json.loads(raw)
    except Exception:
        return JsonResponse({"error": "JSON inválido.", "trace_id": trace_id}, status=400)

    report_id = data.get("report_id")
    group_id = data.get("group_id")
    state = data.get("state") or {}

    if not (report_id and group_id and isinstance(state, dict)):
        return JsonResponse(
            {"error": "Parâmetros ausentes/invalidos.", "trace_id": trace_id}, status=400
        )

    bi_report = get_object_or_404(BIReport, report_id=report_id, group_id=group_id)

    if not _perm_check(request.user, bi_report):
        return JsonResponse({"error": "Acesso negado.", "trace_id": trace_id}, status=403)

    try:
        obj, created = BIUserReportState.objects.update_or_create(
            user=request.user, bi_report=bi_report, defaults={"state": state}
        )
        return JsonResponse(
            {"ok": True, "updated_at": obj.updated_at.isoformat(), "trace_id": trace_id}
        )
    except Exception:
        return JsonResponse({"error": "DB error", "trace_id": trace_id}, status=500)


# ─────────────────────────────────────────────────────────────────────────────
# ACESSOS / PERMISSÕES / BUSCA
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@permission_required("bi.view_access", raise_exception=True)
def visualizar_acessos_bi(request, pk):
    bi_report = get_object_or_404(BIReport, pk=pk)
    acessos = (
        BIAccess.objects.filter(bi_report=bi_report)
        .select_related("user")
        .order_by("-accessed_at")
    )
    return render(
        request,
        "bi/visualizar_acessos.html",
        {"bi_report": bi_report, "acessos": acessos, "total_acessos": acessos.count()},
    )


@login_required
def buscar_grupos(request):
    query = request.GET.get("q", "")
    if not query:
        return JsonResponse([], safe=False)
    grupos = Group.objects.filter(name__icontains=query)[:10]
    data = [{"id": g.id, "name": g.name} for g in grupos]
    return JsonResponse(data, safe=False)


def bi_relatorios(request):
    return render(request, "bi/bi_relatorios.html")


@login_required
@permission_required("bi.permission_report", raise_exception=True)
def relatorio_permissoes(request):
    bi_text = (request.GET.get("bi") or "").strip().lower()
    group_text = (request.GET.get("group") or "").strip().lower()
    user_text = (request.GET.get("user") or "").strip().lower()

    direct_qs = (
        BIReport.objects.filter(allowed_users__isnull=False)
        .values(
            bi_id=F("id"),
            bi_title=F("title"),
            user_id=F("allowed_users__id"),
            username=F("allowed_users__username"),
        )
        .annotate(
            via=Value("Acesso individual", output_field=CharField()),
            perm_group_id=Value(None, output_field=IntegerField()),
        )
    )
    group_qs = (
        BIReport.objects.filter(allowed_groups__user__isnull=False)
        .values(
            bi_id=F("id"),
            bi_title=F("title"),
            user_id=F("allowed_groups__user__id"),
            username=F("allowed_groups__user__username"),
            perm_group_id=F("allowed_groups__id"),
            via=F("allowed_groups__name"),
        )
    )
    public_qs = (
        BIReport.objects.filter(all_users=True)
        .values(bi_id=F("id"), bi_title=F("title"))
        .annotate(
            user_id=Value(None, output_field=IntegerField()),
            username=Value("— todos —", output_field=CharField()),
            via=Value("Todos os usuários", output_field=CharField()),
            perm_group_id=Value(None, output_field=IntegerField()),
        )
    )

    permissoes = list(chain(direct_qs, group_qs, public_qs))

    if bi_text:
        permissoes = [p for p in permissoes if bi_text in p["bi_title"].lower()]
    if user_text:
        permissoes = [p for p in permissoes if p["username"] and user_text in p["username"].lower()]
    if group_text:
        permissoes = [p for p in permissoes if group_text in p["via"].lower()]

    permissoes.sort(
        key=lambda p: (p["bi_title"].lower(), (p["username"] or "").lower(), p["via"].lower())
    )

    bi_opts = list(BIReport.objects.order_by("title").values_list("title", flat=True))
    group_opts = list(Group.objects.order_by("name").values_list("name", flat=True))
    User = get_user_model()
    user_opts = list(User.objects.order_by("username").values_list("username", flat=True))

    fmt = request.GET.get("formato", "html").lower()
    if fmt == "json":
        return JsonResponse(permissoes, safe=False)

    if fmt == "csv":
        from csv import writer

        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="permissoes_bi.csv"'
        w = writer(resp)
        w.writerow(["bi", "usuario", "via"])
        for p in permissoes:
            w.writerow([p["bi_title"], p["username"], p["via"]])
        return resp

    qs_csv = request.GET.copy()
    qs_csv["formato"] = "csv"
    export_url = f"{request.path}?{qs_csv.urlencode()}"

    return render(
        request,
        "bi/relatorio_permissoes.html",
        {
            "permissoes": permissoes,
            "bi_opts": bi_opts,
            "group_opts": group_opts,
            "user_opts": user_opts,
            "bi_text": request.GET.get("bi", ""),
            "group_text": request.GET.get("group", ""),
            "user_text": request.GET.get("user", ""),
            "export_url": export_url,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# REAL-TIME: última atualização, refresh e status
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET", "POST"])
@login_required
def get_last_update_rt(request):
    # --- input (aceita GET ou POST JSON/form) ---
    if request.method == "GET":
        report_id = request.GET.get("report_id")
        group_id = request.GET.get("group_id")
    else:
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            payload = {}
        report_id = payload.get("report_id") or request.POST.get("report_id")
        group_id = payload.get("group_id") or request.POST.get("group_id")

    if not report_id or not group_id:
        return HttpResponseBadRequest("missing report_id/group_id")

    # --- busca registro ---
    try:
        bi = BIReport.objects.get(report_id=report_id, group_id=group_id)
    except BIReport.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    # --- helpers ---
    def _aware(dt):
        if not dt:
            return None
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_default_timezone())
        return dt

    def to_epoch(dt):
        dt = _aware(dt)
        return int(dt.timestamp()) if dt else ""

    def to_iso(dt):
        dt = _aware(dt)
        return dt.isoformat() if dt else ""

    # --- timezone name (robusto) ---
    tzname = getattr(django_settings, "TIME_ZONE", None)
    if not tzname:
        try:
            tzname = timezone.get_current_timezone_name()
        except Exception:
            tzname = "UTC"

    # --- cache (evita martelar a API) ---
    ckey = f"pbi:lastupd:{group_id}:{report_id}"
    cached = cache.get(ckey)
    if cached:
        return JsonResponse(cached)

    # --- tempo real via Power BI API ---
    rt_dt = get_report_last_refresh_time_rt(report_id=report_id, report_group_id=group_id)

    # se veio algo da API, persistimos no modelo (sem quebrar se falhar)
    if rt_dt and (bi.last_updated != rt_dt):
        try:
            BIReport.objects.filter(pk=bi.pk).update(last_updated=rt_dt)
            bi.last_updated = rt_dt
        except Exception:
            pass

    # monta resposta priorizando o tempo real (se disponível)
    last_dt = rt_dt or bi.last_updated
    resp = {
        "ok": True,
        "tz": tzname,
        "last_updated_epoch": to_epoch(last_dt),
        "last_updated_iso": to_iso(last_dt),
        "next_update_epoch": to_epoch(bi.next_update),
        "next_update_iso": to_iso(bi.next_update),
    }

    cache.set(ckey, resp, timeout=55)  # 55s para aliviar chamadas repetidas
    return JsonResponse(resp)


def _req_meta(request):
    """Coleta metadados para log (mantendo o padrão dos seus logs)."""
    meta = {
        "path": request.path,
        "method": request.method,
        "user": getattr(request.user, "username", "anon"),
        "is_auth": bool(getattr(request, "user", None) and request.user.is_authenticated),
        "ip": request.META.get("REMOTE_ADDR") or request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip(),
        "ua": request.META.get("HTTP_USER_AGENT", ""),
        "ct": request.META.get("CONTENT_TYPE", ""),
        "cl": request.META.get("CONTENT_LENGTH", ""),
        "referer": request.META.get("HTTP_REFERER"),
        "origin": request.META.get("HTTP_ORIGIN"),
        "host": request.META.get("HTTP_HOST"),
    }
    return meta


def _json_body(request):
    try:
        body = request.body.decode("utf-8") if request.body else ""
        return json.loads(body or "{}"), body
    except Exception:
        return {}, ""


@login_required
@require_POST
def refresh_now(request):
    """
    Dispara refresh:
      - Se payload tiver {"cascade": true}: aciona dataflows upstream (se houver) e depois o dataset.
      - Senão: aciona apenas o dataset.

    Rate-limit por (group_id, report_id) usando cache.
    Sucesso: HTTP 202.
    """
    payload, raw = _json_body(request)

    report_id = (payload.get("report_id") or "").strip()
    group_id = (payload.get("group_id") or "").strip()
    cascade = bool(payload.get("cascade") if "cascade" in payload else True)
    refresh_type = (payload.get("refresh_type") or "Full").strip() or "Full"

    if not report_id or not group_id:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    # opcional: título do relatório para o log
    bi = BIReport.objects.filter(report_id=report_id, group_id=group_id).first()
    bi_title = bi.title if bi else report_id

    # ---- Rate limit por combinação group/report ----
    lock_ttl = int(getattr(django_settings, "POWERBI_REFRESH_LOCK_SECONDS", 60))
    now = int(time.time())
    lock_key = f"pbi:refresh:lock:{group_id}:{report_id}"

    # Valor guardado = epoch de expiração (para calcular retry_seconds)
    expires_at = now + lock_ttl
    acquired = cache.add(lock_key, expires_at, timeout=lock_ttl)

    if not acquired:
        # Já existe lock — calcular quanto falta
        cached_exp = cache.get(lock_key)
        retry_seconds = max(1, int(cached_exp) - now) if isinstance(cached_exp, int) else lock_ttl
        return JsonResponse(
            {"ok": False, "error": "too_many_requests", "retry_seconds": retry_seconds},
            status=429,
        )

    # A partir daqui, se der erro interno, libera o lock para não travar novas tentativas
    try:
        if cascade:
            # Dispara dataflows (se houver) e depois dataset
            result = cascade_refresh(report_id, group_id, refresh_type=refresh_type)
            status = 202 if result.get("ok") else 400
            # 🔴 único log: atualização
            _log_update_event(request.user, bi_title, report_id, group_id, result, refresh_type)
            return JsonResponse(result, status=status)
        else:
            ok, detail = trigger_dataset_refresh(report_id, group_id, refresh_type=refresh_type)
            status = 202 if ok else 400
            # normaliza estrutura para log unificado
            result = {"ok": True, "dataset": {"ok": ok, "detail": detail}, "dataflows": []}
            # 🔴 único log: atualização
            _log_update_event(request.user, bi_title, report_id, group_id, result, refresh_type)
            return JsonResponse({"ok": ok, "detail": detail}, status=status)

    except Exception:
        # Em erro inesperado, removemos o lock para não travar novas tentativas
        cache.delete(lock_key)
        return JsonResponse({"ok": False, "error": "internal_error"}, status=500)


@require_POST
@login_required
def get_refresh_status(request):
    """
    Retorna o status do último refresh do dataset do report.
    Se o último status for Failed/Disabled/Cancelled, já traz o erro parseado.
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        data = {}

    report_id = data.get("report_id")
    group_id = data.get("group_id")
    after_epoch = data.get("after_epoch")  # opcional, apenas informativo no front

    if not report_id or not group_id:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    # valida report e permissão
    try:
        bi = BIReport.objects.get(report_id=report_id, group_id=group_id)
    except BIReport.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    if not _perm_check(request.user, bi):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    status_data = get_latest_refresh_status(report_id, group_id)
    if not status_data.get("ok"):
        return JsonResponse(status_data, status=502)

    status_data["after_epoch"] = after_epoch
    return JsonResponse(status_data)


# ─────────────────────────────────────────────────────────────────────────────
# VISÕES SALVAS (Salvar & Compartilhar)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET"])
def saved_views_list(request):
    report_id = request.GET.get("report_id")
    group_id = request.GET.get("group_id")
    if not report_id or not group_id:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    try:
        bi = BIReport.objects.get(report_id=report_id, group_id=group_id)
    except BIReport.DoesNotExist:
        return JsonResponse({"ok": False, "error": "bi_not_found"}, status=404)

    if not _perm_check(request.user, bi):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    u = request.user
    qs = (
        BISavedView.objects.filter(bi_report=bi)
        .filter(Q(owner=u) | Q(is_public=True) | Q(shared_users=u) | Q(shared_groups__in=u.groups.all()))
        .select_related("owner")
        .prefetch_related("shared_users", "shared_groups")
        .distinct()
        .order_by("owner__username", "name")
    )

    views_payload = []
    for v in qs:
        if v.is_public:
            visibility = "public"
        elif v.shared_users.exists():
            visibility = "users"
        elif v.shared_groups.exists():
            visibility = "groups"
        else:
            visibility = "private"

        views_payload.append({
            "id": v.id,
            "name": v.name,
            "description": v.description or "",
            "visibility": visibility,
            "owner": v.owner.username,
            "owner_name": v.owner.username,
            "owner_id": v.owner_id,
            "is_owner": (v.owner_id == u.id) or u.is_superuser,
            "shared_user_ids": list(v.shared_users.values_list("id", flat=True)),
            "shared_group_ids": list(v.shared_groups.values_list("id", flat=True)),
            "updated_at": v.updated_at.isoformat(),
            "token": v.share_token,
        })

    return JsonResponse({"ok": True, "views": views_payload})


@login_required
@require_http_methods(["POST"])
def saved_views_save(request):
    """
    Cria/atualiza uma visão.
    body: {
      report_id, group_id,
      name, description,
      visibility: "private"|"public"|"users"|"groups",
      shared_user_ids: [ids?],
      shared_group_ids: [ids?],
      is_default: bool,
      state: {...},      # state consolidado (bookmarkState tem prioridade)
      overwrite_id: id?  # opcional: sobrescrever visão do próprio owner
    }
    """
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    report_id = payload.get("report_id")
    group_id = payload.get("group_id")
    if not report_id or not group_id:
        return JsonResponse({"error": "missing_params"}, status=400)

    try:
        bi = BIReport.objects.get(report_id=report_id, group_id=group_id)
    except BIReport.DoesNotExist:
        return JsonResponse({"error": "bi_not_found"}, status=404)

    if not _perm_check(request.user, bi):
        return JsonResponse({"error": "forbidden"}, status=403)

    name = (payload.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "missing_name"}, status=400)

    state = payload.get("state") or {}
    if not isinstance(state, dict):
        return JsonResponse({"error": "bad_state"}, status=400)

    visibility = (payload.get("visibility") or "private").lower()
    shared_user_ids = payload.get("shared_user_ids") or []
    shared_group_ids = payload.get("shared_group_ids") or []
    is_default = bool(payload.get("is_default"))
    overwrite_id = payload.get("overwrite_id")

    # cria/atualiza
    if overwrite_id:
        sv = get_object_or_404(
            BISavedView, pk=overwrite_id, bi_report=bi, owner=request.user
        )
    else:
        # impede nome duplicado do mesmo owner para o mesmo BI
        if BISavedView.objects.filter(
            bi_report=bi, owner=request.user, name=name
        ).exists():
            return JsonResponse({"error": "duplicate_name"}, status=409)
        sv = BISavedView(bi_report=bi, owner=request.user, name=name)

    sv.name = name
    sv.description = (payload.get("description") or "").strip() or None
    sv.state = state

    # Persistimos antes de mexer nos M2M
    sv.save()

    if visibility == "public":
        sv.is_public = True
        sv.shared_users.clear()
        sv.shared_groups.clear()
    elif visibility == "users":
        sv.is_public = False
        sv.shared_groups.clear()
        if shared_user_ids:
            sv.shared_users.set(
                list(get_user_model().objects.filter(id__in=shared_user_ids))
            )
        else:
            sv.shared_users.clear()
    elif visibility == "groups":
        sv.is_public = False
        sv.shared_users.clear()
        if shared_group_ids:
            sv.shared_groups.set(list(Group.objects.filter(id__in=shared_group_ids)))
        else:
            sv.shared_groups.clear()
    else:
        # private
        sv.is_public = False
        sv.shared_users.clear()
        sv.shared_groups.clear()

    sv.is_default = is_default
    sv.save()  # garante share_token e default único

    apply_url = request.build_absolute_uri(
        reverse("bi:bi_report_detail", args=[bi.pk]) + f"?view={sv.share_token}"
    )

    return JsonResponse({"ok": True, "view": sv.as_brief(), "apply_url": apply_url})


@login_required
@require_http_methods(["GET", "POST"])
def saved_views_get(request):
    data = {}
    if request.method == "GET":
        data["id"] = request.GET.get("id")
        data["token"] = request.GET.get("token")
        data["report_id"] = request.GET.get("report_id")
        data["group_id"] = request.GET.get("group_id")
    else:
        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "invalid_json"}, status=400)

    report_id = data.get("report_id")
    group_id = data.get("group_id")
    if not report_id or not group_id:
        return JsonResponse({"error": "missing_params"}, status=400)

    try:
        bi = BIReport.objects.get(report_id=report_id, group_id=group_id)
    except BIReport.DoesNotExist:
        return JsonResponse({"error": "bi_not_found"}, status=404)

    if not _perm_check(request.user, bi):
        return JsonResponse({"error": "forbidden"}, status=403)

    sv = None
    if data.get("id"):
        sv = BISavedView.objects.filter(pk=data["id"], bi_report=bi).first()
    elif data.get("token"):
        sv = BISavedView.objects.filter(share_token=data["token"], bi_report=bi).first()

    if not sv:
        return JsonResponse({"error": "not_found"}, status=404)
    if not sv.can_view(request.user):
        return JsonResponse({"error": "forbidden"}, status=403)

    # monta payload completo p/ edição
    if sv.is_public:
        visibility = "public"
    elif sv.shared_users.exists():
        visibility = "users"
    elif sv.shared_groups.exists():
        visibility = "groups"
    else:
        visibility = "private"

    view_payload = {
        "id": sv.id,
        "name": sv.name,
        "description": sv.description or "",
        "visibility": visibility,
        "owner_id": sv.owner_id,
        "owner_name": sv.owner.username,
        "is_owner": (sv.owner_id == request.user.id) or request.user.is_superuser,
        "shared_user_ids": list(sv.shared_users.values_list("id", flat=True)),
        "shared_users": [
            {"id": u.id, "name": (u.get_full_name() or u.username), "username": u.username}
            for u in sv.shared_users.all()
        ],
        "shared_group_ids": list(sv.shared_groups.values_list("id", flat=True)),
        "updated_at": sv.updated_at.isoformat(),
        "token": sv.share_token,
    }

    return JsonResponse({"ok": True, "state": sv.state, "view": view_payload})


@login_required
@require_http_methods(["POST"])
def saved_views_delete(request):
    """
    Remove visão do owner (ou superuser).
    body: { id }
    """
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    sv = get_object_or_404(BISavedView, pk=payload.get("id"))
    if sv.owner != request.user and not request.user.is_superuser:
        return JsonResponse({"error": "forbidden"}, status=403)

    sv.delete()
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["POST"])
def saved_views_set_default(request):
    """
    Define visão default do owner para o BI.
    body: { id }
    """
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    sv_id = payload.get("id")
    if not sv_id:
        return JsonResponse({"error": "missing_id"}, status=400)

    sv = get_object_or_404(BISavedView, pk=sv_id)
    if sv.owner != request.user:
        return JsonResponse({"error": "forbidden"}, status=403)

    sv.is_default = True
    sv.save()
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["POST"])
def saved_views_update(request):
    """
    Atualiza metadados (e opcionalmente o state) de uma visão existente.
    body: {
      id: int,                       # obrigatório
      name, description,             # opcional
      visibility: "private"|"public"|"users"|"groups",
      shared_user_ids: [ids?],
      shared_group_ids: [ids?],
      is_default: bool,
      state: {...}                   # opcional — se enviado, substitui o state
    }
    """
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    sv_id = payload.get("id")
    if not sv_id:
        return JsonResponse({"error": "missing_id"}, status=400)

    sv = get_object_or_404(BISavedView, pk=sv_id)
    bi = sv.bi_report

    # Permissões: só o dono (ou superuser) pode editar
    if sv.owner != request.user and not request.user.is_superuser:
        return JsonResponse({"error": "forbidden"}, status=403)

    # Também valida que o usuário tem acesso a este BI
    if not _perm_check(request.user, bi):
        return JsonResponse({"error": "forbidden"}, status=403)

    # Campos do payload
    name = (payload.get("name") or sv.name or "").strip()
    description = (payload.get("description") or "").strip() or None
    visibility = (payload.get("visibility") or ("public" if sv.is_public else "private")).lower()
    shared_user_ids = payload.get("shared_user_ids") or []
    shared_group_ids = payload.get("shared_group_ids") or []
    is_default = bool(payload.get("is_default")) if "is_default" in payload else sv.is_default
    state = payload.get("state", None)

    # Impede nome duplicado do mesmo owner para o mesmo BI
    if name and BISavedView.objects.filter(
        bi_report=bi, owner=sv.owner, name=name
    ).exclude(pk=sv.pk).exists():
        return JsonResponse({"error": "duplicate_name"}, status=409)

    # Atualiza campos básicos
    if name:
        sv.name = name
    sv.description = description

    # Atualiza state somente se enviado
    if isinstance(state, dict):
        sv.state = state

    # Visibilidade + M2M
    if visibility == "public":
        sv.is_public = True
        sv.save()  # precisa salvar antes de mexer nos M2M em alguns bancos
        sv.shared_users.clear()
        sv.shared_groups.clear()
    elif visibility == "users":
        sv.is_public = False
        sv.save()
        sv.shared_groups.clear()
        if shared_user_ids:
            users = list(get_user_model().objects.filter(id__in=shared_user_ids))
            sv.shared_users.set(users)
        else:
            sv.shared_users.clear()
    elif visibility == "groups":
        sv.is_public = False
        sv.save()
        sv.shared_users.clear()
        if shared_group_ids:
            groups = list(Group.objects.filter(id__in=shared_group_ids))
            sv.shared_groups.set(groups)
        else:
            sv.shared_groups.clear()
    else:
        # private
        sv.is_public = False
        sv.save()
        sv.shared_users.clear()
        sv.shared_groups.clear()

    sv.is_default = bool(is_default)
    sv.save()  # (no seu modelo já garante share_token e default único)

    apply_url = request.build_absolute_uri(
        reverse("bi:bi_report_detail", args=[bi.pk]) + f"?view={sv.share_token}"
    )

    return JsonResponse({"ok": True, "view": sv.as_brief(), "apply_url": apply_url})


@login_required
@require_http_methods(["GET"])
def buscar_usuarios(request):
    """
    Auto-complete de usuários.
    GET: q
    Retorna [{id, username, name, email}]
    """
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse([], safe=False)

    User = get_user_model()
    # busca por username, nome, sobrenome, ou email
    users = (
        User.objects
        .filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(email__icontains=q)
        )
        .order_by("username")[:10]
    )

    data = [{
        "id": u.id,
        "username": u.username,
        "name": (u.get_full_name() or u.username),
        "email": u.email or "",
    } for u in users]

    return JsonResponse(data, safe=False)


# ─────────────────────────────────────────────────────────────────────────────
# NOVO – Listagem de dataflows do workspace (para a UI de edição)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_GET
def pbi_list_dataflows(request):
    group_id = (request.GET.get("group_id") or "").strip()
    if not group_id:
        return JsonResponse({"ok": False, "error": "missing_group_id"}, status=400)

    res = list_workspace_dataflows(group_id)
    if isinstance(res, dict) and not res.get("ok", False):
        return JsonResponse(res, status=res.get("status", 502))

    items = (res.get("items") if isinstance(res, dict) else res) or []
    data = [{"id": it.get("dataflow_id"), "group_id": it.get("group_id") or group_id, "name": it.get("name") or ""} 
            for it in items]
    return JsonResponse({"ok": True, "items": data})
