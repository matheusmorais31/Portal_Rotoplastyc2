"""
views.py – Django views para módulo BI usando padrão User‑Owns‑Data
(autenticação automática com a conta Pro ti@rotoplastyc.com.br)
"""

import json
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group, User
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from itertools import chain
from django.db.models import F, Value, CharField, IntegerField


from .forms import BIReportForm, BIReportEditForm
from .models import BIReport, BIAccess
from .utils import get_embed_params_user_owns_data

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CRUD / LISTAGEM DE RELATÓRIOS
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def create_bi_report(request):
    """Cadastro manual de um relatório (admin)."""
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
    """Edição das permissões de acesso (não altera IDs nem embed)."""
    bi_report = get_object_or_404(BIReport, pk=pk)
    if request.method == "POST":
        form = BIReportEditForm(request.POST, instance=bi_report)
        if form.is_valid():
            rpt = form.save(commit=False)
            # Protege campos de identificação
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
    """Lista completa (admin)."""
    bi_reports = BIReport.objects.all().prefetch_related("allowed_users", "allowed_groups")
    return render(request, "bi/listar_bi.html", {"bi_reports": bi_reports})


@login_required
def my_bi_report_list(request):
    """Lista filtrada pelo usuário."""
    user = request.user
    bi_reports = (
        BIReport.objects.filter(
            Q(all_users=True)
            | Q(allowed_users=user)
            | Q(allowed_groups__in=user.groups.all())
        )
        .distinct()
        .prefetch_related("allowed_users", "allowed_groups")
    )
    return render(request, "bi/listar_bi.html", {"bi_reports": bi_reports})


# ─────────────────────────────────────────────────────────────────────────────
# VISUALIZAÇÃO DE RELATÓRIO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def bi_report_detail(request, pk):
    """Renderiza o template com iframe do Power BI."""
    bi_report = get_object_or_404(BIReport, pk=pk)
    user = request.user

    has_perm = (
        bi_report.all_users
        or bi_report.allowed_users.filter(id=user.id).exists()
        or Group.objects.filter(
            id__in=bi_report.allowed_groups.values_list("id", flat=True), user=user
        ).exists()
    )

    if not has_perm:
        logger.warning("BI: acesso negado – %s → %s", user.username, bi_report.title)
        messages.error(request, "Você não tem permissão para este relatório.")
        return render(request, "bi/403.html")

    # Log de acesso
    BIAccess.objects.create(bi_report=bi_report, user=user)

    embed = get_embed_params_user_owns_data(
        report_id=bi_report.report_id, group_id=bi_report.group_id
    )
    if not embed:
        messages.error(request, "Não foi possível gerar o embed do relatório.")
        return render(request, "bi/erro_ao_carregar_relatorio.html")

    context = {
        "bi_report": bi_report,
        "embed_url": embed["embed_url"],
        "embed_token": embed["embed_token"],
    }
    return render(request, "bi/visualizar_bi.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# AJAX – token sob demanda (opcional)
# ─────────────────────────────────────────────────────────────────────────────

@require_POST
@login_required
def get_embed_params(request):
    """Retorna embed_url + token via JSON (client‑side refresh)."""
    try:
        data = json.loads(request.body)
        report_id = data.get("report_id")
        group_id = data.get("group_id")
        if not (report_id and group_id):
            return JsonResponse({"error": "Parâmetros ausentes."}, status=400)

        bi_report = get_object_or_404(BIReport, report_id=report_id, group_id=group_id)
        user = request.user
        has_perm = (
            bi_report.all_users
            or bi_report.allowed_users.filter(id=user.id).exists()
            or Group.objects.filter(
                id__in=bi_report.allowed_groups.values_list("id", flat=True), user=user
            ).exists()
        )
        if not has_perm:
            return JsonResponse({"error": "Acesso negado."}, status=403)

        embed = get_embed_params_user_owns_data(report_id, group_id)
        if not embed:
            return JsonResponse({"error": "Falha ao gerar token."}, status=500)
        return JsonResponse(embed)
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON inválido."}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# RELATÓRIO DE ACESSOS + BUSCA DE GRUPOS
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
    """
    Relatório de permissões de BI.

    Filtros texto (pelo NOME, não id):
        bi=<parte do nome do BI>
        group=<parte do nome do grupo>
        user=<parte do username>

    Exportação:
        formato=csv | json
    """

    # 1. Filtros recebidos
    bi_text    = (request.GET.get("bi")    or "").strip().lower()
    group_text = (request.GET.get("group") or "").strip().lower()
    user_text  = (request.GET.get("user")  or "").strip().lower()

    # 2. Permissões
    # 2.1 Individuais
    direct_qs = (
        BIReport.objects.filter(allowed_users__isnull=False)
        .values(
            bi_id    = F("id"),
            bi_title = F("title"),
            user_id  = F("allowed_users__id"),
            username = F("allowed_users__username"),
        )
        .annotate(
            via           = Value("Acesso individual", output_field=CharField()),
            perm_group_id = Value(None, output_field=IntegerField()),
        )
    )

    # 2.2 Via grupo
    group_qs = (
        BIReport.objects.filter(allowed_groups__user__isnull=False)
        .values(
            bi_id         = F("id"),
            bi_title      = F("title"),
            user_id       = F("allowed_groups__user__id"),
            username      = F("allowed_groups__user__username"),
            perm_group_id = F("allowed_groups__id"),
            via           = F("allowed_groups__name"),
        )
    )

    # 2.3 Públicos
    public_qs = (
        BIReport.objects.filter(all_users=True)
        .values(
            bi_id    = F("id"),
            bi_title = F("title"),
        )
        .annotate(
            user_id       = Value(None,                output_field=IntegerField()),
            username      = Value("— todos —",         output_field=CharField()),
            via           = Value("Todos os usuários", output_field=CharField()),
            perm_group_id = Value(None,                output_field=IntegerField()),
        )
    )

    permissoes = list(chain(direct_qs, group_qs, public_qs))

    # 3. Aplica filtros
    if bi_text:
        permissoes = [p for p in permissoes if bi_text in p["bi_title"].lower()]
    if user_text:
        permissoes = [
            p for p in permissoes
            if p["username"] and user_text in p["username"].lower()
        ]
    if group_text:
        permissoes = [p for p in permissoes if group_text in p["via"].lower()]

    # 4. Ordena
    permissoes.sort(key=lambda p: (
        p["bi_title"].lower(),
        (p["username"] or "").lower(),
        p["via"].lower(),
    ))

    # 5. Opções para datalist
    bi_opts = list(BIReport.objects.order_by("title")
                   .values_list("title", flat=True))
    group_opts = list(Group.objects.order_by("name")
                      .values_list("name", flat=True))
    User = get_user_model()
    user_opts = list(User.objects.order_by("username")
                     .values_list("username", flat=True))

    # 6. Exportações
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

    # 6½. URL para o botão Exportar CSV (com filtros)
    qs_csv = request.GET.copy()
    qs_csv["formato"] = "csv"
    export_url = f"{request.path}?{qs_csv.urlencode()}"

    # 7. Renderiza
    return render(
        request,
        "bi/relatorio_permissoes.html",
        {
            "permissoes": permissoes,

            "bi_opts":    bi_opts,
            "group_opts": group_opts,
            "user_opts":  user_opts,

            "bi_text":    request.GET.get("bi", ""),
            "group_text": request.GET.get("group", ""),
            "user_text":  request.GET.get("user", ""),

            "export_url": export_url,
        },
    )