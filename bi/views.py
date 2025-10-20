# bi/views.py – Django views para módulo BI com persistência de estado + LOG detalhado
from __future__ import annotations

import json
import logging
import uuid
from itertools import chain
from typing import Any, Dict
from .utils import get_latest_refresh_status

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.db.models import F, Value, CharField, IntegerField, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings as django_settings
from .utils import get_report_last_refresh_time_rt, trigger_dataset_refresh

from .forms import BIReportForm, BIReportEditForm
from .models import BIReport, BIAccess, BIUserReportState
from .utils import get_embed_params_user_owns_data
from django.core.cache import cache
from django.views.decorators.http import require_http_methods
from .utils import get_report_last_refresh_time_rt

logger = logging.getLogger("bi")


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
    if request.method == "POST":
        form = BIReportEditForm(request.POST, instance=bi_report)
        if form.is_valid():
            rpt = form.save(commit=False)
            rpt.title = bi_report.title
            rpt.embed_code = bi_report.embed_code
            rpt.report_id = bi_report.report_id
            rpt.group_id = bi_report.group_id
            rpt.dataset_id = bi_report.dataset_id
            rpt.save()

            if rpt.all_users:
                rpt.allowed_users.clear()
                rpt.allowed_groups.clear()
            else:
                rpt.allowed_users.set(request.POST.getlist("allowed_users"))
                rpt.allowed_groups.set(request.POST.getlist("allowed_groups"))

            messages.success(request, "Relatório atualizado.")
            return redirect("bi:bi_report_list")
    else:
        form = BIReportEditForm(instance=bi_report)
    return render(request, "bi/editar_bi.html", {"form": form, "bi_report": bi_report})


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
# DETALHE + ESTADO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def bi_report_detail(request, pk):
    trace_id = str(uuid.uuid4())
    bi_report = get_object_or_404(BIReport, pk=pk)
    user = request.user

    logger.info("BI[detail][%s] open → %s by %s | meta=%s",
                trace_id, bi_report.title, user.username, _meta_from_request(request))

    if not _perm_check(user, bi_report):
        logger.warning("BI[detail][%s] deny → %s by %s", trace_id, bi_report.title, user.username)
        messages.error(request, "Você não tem permissão para este relatório.")
        return render(request, "bi/403.html")

    BIAccess.objects.create(bi_report=bi_report, user=user)

    embed = get_embed_params_user_owns_data(report_id=bi_report.report_id, group_id=bi_report.group_id)
    if not embed:
        logger.error("BI[detail][%s] embed generation failed", trace_id)
        messages.error(request, "Não foi possível gerar o embed do relatório.")
        return render(request, "bi/erro_ao_carregar_relatorio.html", {"trace_id": trace_id})

    state_obj = BIUserReportState.objects.filter(user=user, bi_report=bi_report).first()
    last_state = state_obj.state if state_obj else {}
    last_state_updated_at = state_obj.updated_at.isoformat() if state_obj else ""

    logger.info("BI[detail][%s] last_state=%s | updated_at=%s",
                trace_id, _summarize_state(last_state), last_state_updated_at)

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
    meta = _meta_from_request(request)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        logger.warning("BI[get_embed][%s] JSON inválido | meta=%s", trace_id, meta)
        return JsonResponse({"error": "JSON inválido.", "trace_id": trace_id}, status=400)

    report_id = data.get("report_id")
    group_id = data.get("group_id")
    logger.info("BI[get_embed][%s] req report_id=%s group_id=%s | meta=%s",
                trace_id, report_id, group_id, meta)

    if not (report_id and group_id):
        return JsonResponse({"error": "Parâmetros ausentes.", "trace_id": trace_id}, status=400)

    bi_report = get_object_or_404(BIReport, report_id=report_id, group_id=group_id)
    if not _perm_check(request.user, bi_report):
        logger.warning("BI[get_embed][%s] deny user=%s", trace_id, request.user.username)
        return JsonResponse({"error": "Acesso negado.", "trace_id": trace_id}, status=403)

    embed = get_embed_params_user_owns_data(report_id, group_id)
    if not embed:
        logger.error("BI[get_embed][%s] embed generation failed", trace_id)
        return JsonResponse({"error": "Falha ao gerar token.", "trace_id": trace_id}, status=500)

    logger.info("BI[get_embed][%s] ok", trace_id)
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
    meta = _meta_from_request(request)

    raw_len = len(request.body or b"")
    logger.info("BI[save_state][%s] inbound bytes=%s | meta=%s", trace_id, raw_len, meta)

    try:
        raw = request.body.decode("utf-8") if request.body else "{}"
        data = json.loads(raw)
    except Exception as e:
        logger.warning("BI[save_state][%s] JSON parse fail: %s | raw_prefix=%s",
                       trace_id, e, (request.body[:200] if request.body else b""))
        return JsonResponse({"error": "JSON inválido.", "trace_id": trace_id}, status=400)

    report_id = data.get("report_id")
    group_id = data.get("group_id")
    state = data.get("state") or {}

    logger.info("BI[save_state][%s] payload report_id=%s group_id=%s summary=%s",
                trace_id, report_id, group_id, _summarize_state(state))

    if not (report_id and group_id and isinstance(state, dict)):
        logger.warning("BI[save_state][%s] bad params", trace_id)
        return JsonResponse({"error": "Parâmetros ausentes/invalidos.", "trace_id": trace_id}, status=400)

    bi_report = get_object_or_404(BIReport, report_id=report_id, group_id=group_id)

    if not _perm_check(request.user, bi_report):
        logger.warning("BI[save_state][%s] deny user=%s report=%s", trace_id, request.user.username, bi_report.title)
        return JsonResponse({"error": "Acesso negado.", "trace_id": trace_id}, status=403)

    try:
        obj, created = BIUserReportState.objects.update_or_create(
            user=request.user, bi_report=bi_report, defaults={"state": state}
        )
        logger.info("BI[save_state][%s] ok %s | updated_at=%s | state_bytes=%s",
                    trace_id, "created" if created else "updated",
                    obj.updated_at.isoformat(),
                    len((json.dumps(state) or "").encode("utf-8")))
        return JsonResponse({"ok": True, "updated_at": obj.updated_at.isoformat(), "trace_id": trace_id})
    except Exception as e:
        logger.exception("BI[save_state][%s] DB error: %s", trace_id, e)
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
    return render(request, 'bi/bi_relatorios.html')


@login_required
@permission_required("bi.permission_report", raise_exception=True)
def relatorio_permissoes(request):
    bi_text    = (request.GET.get("bi")    or "").strip().lower()
    group_text = (request.GET.get("group") or "").strip().lower()
    user_text  = (request.GET.get("user")  or "").strip().lower()

    direct_qs = (
        BIReport.objects.filter(allowed_users__isnull=False)
        .values(bi_id=F("id"), bi_title=F("title"), user_id=F("allowed_users__id"), username=F("allowed_users__username"))
        .annotate(via=Value("Acesso individual", output_field=CharField()), perm_group_id=Value(None, output_field=IntegerField()))
    )
    group_qs = (
        BIReport.objects.filter(allowed_groups__user__isnull=False)
        .values(
            bi_id=F("id"), bi_title=F("title"), user_id=F("allowed_groups__user__id"),
            username=F("allowed_groups__user__username"), perm_group_id=F("allowed_groups__id"), via=F("allowed_groups__name"),
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

    permissoes.sort(key=lambda p: (p["bi_title"].lower(), (p["username"] or "").lower(), p["via"].lower()))

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


@require_http_methods(["GET", "POST"])
@login_required
def get_last_update_rt(request):
    # --- input (aceita GET ou POST JSON/form) ---
    if request.method == "GET":
        report_id = request.GET.get('report_id')
        group_id  = request.GET.get('group_id')
    else:
        try:
            payload = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            payload = {}
        report_id = payload.get('report_id') or request.POST.get('report_id')
        group_id  = payload.get('group_id')  or request.POST.get('group_id')

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
            # não falha a resposta por causa de persistência
            pass

    # monta resposta priorizando o tempo real (se disponível)
    last_dt = rt_dt or bi.last_updated
    resp = {
        "ok": True,
        "tz": tzname,
        "last_updated_epoch": to_epoch(last_dt),
        "last_updated_iso":   to_iso(last_dt),
        "next_update_epoch":  to_epoch(bi.next_update),
        "next_update_iso":    to_iso(bi.next_update),
    }

    cache.set(ckey, resp, timeout=55)  # 55s para aliviar chamadas repetidas
    return JsonResponse(resp)



@require_POST
@login_required
def refresh_now(request):
    """
    Dispara refresh do dataset do report e retorna JSON.
    Faz um lock curto para evitar spam (ex.: 60s).
    """
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        data = {}

    report_id = data.get("report_id")
    group_id  = data.get("group_id")
    if not report_id or not group_id:
        return JsonResponse({"ok": False, "error": "missing_params"}, status=400)

    # valida report e permissão
    try:
        bi = BIReport.objects.get(report_id=report_id, group_id=group_id)
    except BIReport.DoesNotExist:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)

    if not _perm_check(request.user, bi):
        return JsonResponse({"ok": False, "error": "forbidden"}, status=403)

    # throttle simples via cache
    lock_key = f"pbi:refreshlock:{group_id}:{report_id}"
    if not cache.add(lock_key, "1", timeout=60):
        return JsonResponse({"ok": False, "error": "locked", "retry_seconds": 60}, status=429)

    ok, detail = trigger_dataset_refresh(report_id, group_id, refresh_type="Full")
    if not ok:
        return JsonResponse({"ok": False, "error": detail}, status=502)

    # opcional: devolve timestamp atual para polling de mudança
    last_rt = get_report_last_refresh_time_rt(report_id, group_id)
    last_epoch = int(last_rt.timestamp()) if last_rt else None

    return JsonResponse({"ok": True, "status": detail, "last_epoch": last_epoch})


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
    group_id  = data.get("group_id")
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