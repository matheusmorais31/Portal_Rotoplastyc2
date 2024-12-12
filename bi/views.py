
import json
import logging
from django.db.models import Q
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .utils import get_powerbi_embed_params
from django.contrib import messages
from .forms import BIReportForm, BIReportEditForm
from .models import BIReport, BIAccess
from django.contrib.auth.models import Group

# Configuração do logger
logger = logging.getLogger(__name__)


@login_required
def create_bi_report(request):
    """
    View para criar um novo relatório BI.
    """
    if request.method == 'POST':
        form = BIReportForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('bi:bi_report_list')
    else:
        form = BIReportForm()
    return render(request, 'usuarios/403.html', {'form': form})

# Função Editar BI
@login_required
@permission_required('bi.edit_bi', raise_exception=True)
def edit_bi_report(request, pk):
    bi_report = get_object_or_404(BIReport, pk=pk)
    
    if request.method == 'POST':
        form = BIReportEditForm(request.POST, instance=bi_report)
        if form.is_valid():
            bi_report = form.save(commit=False)
            bi_report.save()
            
            # Atualiza allowed_users e allowed_groups manualmente
            allowed_users_ids = request.POST.getlist('allowed_users')
            allowed_groups_ids = request.POST.getlist('allowed_groups')
            bi_report.allowed_users.set(allowed_users_ids)
            bi_report.allowed_groups.set(allowed_groups_ids)
            
            logger.info(f"Relatório '{bi_report.title}' editado com sucesso por {request.user.username}.")
            messages.success(request, "Relatório BI atualizado com sucesso.")
            return redirect('bi:bi_report_list') 
    else:
        form = BIReportEditForm(instance=bi_report)

    return render(request, 'bi/editar_bi.html', {
        'form': form,
        'bi_report': bi_report
    })

# Lista BI
@login_required
@permission_required('bi.view_bi', raise_exception=True)
def bi_report_list(request):
    """
    View para listar todos os relatórios BI.
    """
    bi_reports = BIReport.objects.all().prefetch_related('allowed_users')  # Otimização opcional
    return render(request, 'bi/listar_bi.html', {'bi_reports': bi_reports})

@login_required
def my_bi_report_list(request):
    """
    View para listar os relatórios BI que o usuário atual pode acessar,
    seja diretamente ou através de um grupo.
    """
    user = request.user
    user_groups = user.groups.all()
    
    bi_reports = BIReport.objects.filter(
        Q(allowed_users=user) |
        Q(allowed_groups__in=user_groups)
    ).distinct().prefetch_related('allowed_users', 'allowed_groups')
    
    return render(request, 'bi/listar_bi.html', {'bi_reports': bi_reports})


# Função Visualizar BI
@login_required
def bi_report_detail(request, pk):
    bi_report = get_object_or_404(BIReport, pk=pk)
    
    # Verifica se o usuário está nos allowed_users ou pertence a algum allowed_group
    user = request.user
    allowed_users = bi_report.allowed_users.all()
    allowed_groups = bi_report.allowed_groups.all()
    
    # Verificar se o usuário está diretamente na lista de usuários permitidos
    has_user_permission = allowed_users.filter(id=user.id).exists()
    
    # Verificar se o usuário pertence a algum grupo permitido
    has_group_permission = Group.objects.filter(id__in=allowed_groups.values_list('id', flat=True), user=user).exists()
    
    if has_user_permission or has_group_permission:
        # Registrando acesso do usuário a este relatório
        BIAccess.objects.create(bi_report=bi_report, user=user)
        
        # Obtendo informações do usuário
        user_id = user.id
        username = user.username
        roles = []
    
        # Verifica dataset_id
        if not bi_report.dataset_id:
            logger.error(f"Relatório '{bi_report.title}' não possui dataset_id.")
            messages.error(request, "Relatório mal configurado. Por favor, contate o administrador.")
            return render(request, 'bi/erro_ao_carregar_relatorio.html', {
                'mensagem': 'Relatório mal configurado. Por favor, contate o administrador.'
            })
    
        embed_params = get_powerbi_embed_params(
            report_id=bi_report.report_id,
            group_id=bi_report.group_id,
            dataset_id=bi_report.dataset_id,
            user_id=user_id,
            username=username,
            roles=roles
        )
    
        if embed_params:
            context = {
                'bi_report': bi_report,
                'report_id': bi_report.report_id,
                'embed_url': embed_params['embed_url'],
                'embed_token': embed_params['embed_token'],
            }
            logger.info(f"Passando parâmetros para o template: {context}")
            return render(request, 'bi/visualizar_bi.html', context)
        else:
            logger.error("Não foi possível obter os parâmetros de embed.")
            messages.error(request, "Não foi possível carregar o relatório. Por favor, tente novamente mais tarde.")
            return render(request, 'bi/erro_ao_carregar_relatorio.html', {
                'mensagem': 'Não foi possível carregar o relatório. Por favor, tente novamente mais tarde.'
            })
    else:
        logger.warning(f"Usuário {user.username} tentou acessar um relatório sem permissão.")
        messages.error(request, "Você não tem permissão para acessar este relatório.")
        return render(request, 'bi/acesso_negado.html')

    
@require_POST
@login_required
def get_embed_params(request):
    """
    Endpoint para obter os parâmetros de embed do Power BI via requisição AJAX.
    """
    try:
        data = json.loads(request.body)
        report_id = data.get('report_id')
        group_id = data.get('group_id')

        # Verificar se o usuário tem permissão para acessar o relatório
        bi_report = get_object_or_404(BIReport, report_id=report_id, group_id=group_id)
        user = request.user
        allowed_users = bi_report.allowed_users.all()
        allowed_groups = bi_report.allowed_groups.all()

        # Verificar permissões
        has_user_permission = allowed_users.filter(id=user.id).exists()
        has_group_permission = Group.objects.filter(id__in=allowed_groups.values_list('id', flat=True), user=user).exists()

        if not (has_user_permission or has_group_permission):
            return JsonResponse({'error': 'Acesso negado.'}, status=403)

        embed_params = get_powerbi_embed_params(report_id, group_id)
        if embed_params:
            return JsonResponse(embed_params)
        else:
            return JsonResponse({'error': 'Não foi possível obter os parâmetros de embed.'}, status=500)
    except Exception as e:
        logger.exception("Erro ao processar get_embed_params")
        return JsonResponse({'error': 'Erro interno do servidor.'}, status=500)

    
@login_required
@permission_required('bi.view_access', raise_exception=True)
def visualizar_acessos_bi(request, pk):
    bi_report = get_object_or_404(BIReport, pk=pk)
    acessos = BIAccess.objects.filter(bi_report=bi_report).select_related('user')
    return render(request, 'bi/visualizar_acessos.html', {'bi_report': bi_report, 'acessos': acessos})


@login_required
def buscar_grupos(request):
    query = request.GET.get('q', '')
    grupos = []
    if query:
        grupos_qs = Group.objects.filter(name__icontains=query)[:10]  # Limita a 10 resultados
        grupos = [{'id': grupo.id, 'name': grupo.name} for grupo in grupos_qs]
    return JsonResponse(grupos, safe=False)


