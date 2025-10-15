# rh/views.py
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
import json
from datetime import datetime, date
import logging # Importar logging para os logs de erro

logger = logging.getLogger(__name__) # Instanciar o logger

from . import api
from .models import EntregaEPI

# Base para o agrupamento de dados (mantida)

def _prepare_grouped_entregas(queryset):
    raw_grouped_entregas = {}
    for entrega in queryset:
        key_cc = f"{entrega.centro_custo or 'Sem CC'} - {entrega.descricao_centro_custo or 'Sem Descrição'}"
        raw_grouped_entregas.setdefault(key_cc, []).append(entrega)

    final_grouped_entregas = {}
    for key_cc, entregas_list in raw_grouped_entregas.items():
        summed_items = {}
        for entrega in entregas_list:
            # Coalesce defensivo
            data_entrega = entrega.data_entrega  # DateField (não-nulo)
            codigo_estoque = entrega.codigo_estoque or ""   # evita None
            descricao_epi  = entrega.descricao_epi or ""    # evita None

            item_sum_key = (data_entrega, codigo_estoque, descricao_epi)
            if item_sum_key not in summed_items:
                summed_items[item_sum_key] = {
                    'data_entrega': data_entrega,
                    'codigo_estoque': codigo_estoque,
                    'descricao_epi': descricao_epi,
                    'quantidade_total': 0,
                    'detalhes_individuais': [],
                    'ids_originais': []
                }

            summed_items[item_sum_key]['quantidade_total'] += entrega.quantidade_entregue
            summed_items[item_sum_key]['ids_originais'].append(entrega.id)
            summed_items[item_sum_key]['detalhes_individuais'].append({
                'id': entrega.id,
                'unidade': entrega.unidade,
                'contrato': entrega.contrato,
                'colaborador': entrega.colaborador,
                'epi': entrega.epi,
                'lote': entrega.lote,
                'quantidade_entregue': entrega.quantidade_entregue,
                'data_devolucao': entrega.data_devolucao,
                'status': entrega.status,
                'sequencial_baixa_erp': entrega.sequencial_baixa_erp,
                'data_baixa_erp': entrega.data_baixa_erp,
            })

        # Ordena usando valores já coalescidos
        final_grouped_entregas[key_cc] = sorted(
            summed_items.values(),
            key=lambda x: (x['data_entrega'], x['codigo_estoque'] or "")
        )

    return dict(sorted(final_grouped_entregas.items()))


# Mixin para Lógica de Filtro
class EntregaEPIFilterMixin:
    def get_queryset(self):
        queryset = super().get_queryset()

        # 1. Filtro por Status
        status_filter = self.request.GET.get('status')
        if status_filter and status_filter != 'todos':
            queryset = queryset.filter(status=status_filter)

        # 2. Filtro por Contrato
        contrato_filter = self.request.GET.get('contrato')
        if contrato_filter:
            queryset = queryset.filter(contrato=contrato_filter)

        # 3. Filtro por Cód. EPI Tecnicon (usando codigo_estoque)
        epi_tecnicon_filter = self.request.GET.get('epi_tecnicon')
        if epi_tecnicon_filter:
            queryset = queryset.filter(codigo_estoque__icontains=epi_tecnicon_filter)

        # 4. Filtro por Sequencial ERP
        sequencial_erp_filter = self.request.GET.get('sequencial_erp')
        if sequencial_erp_filter:
            # Assumindo que sequencial_baixa_erp é um campo de texto ou que você quer busca parcial
            queryset = queryset.filter(sequencial_baixa_erp__icontains=sequencial_erp_filter)
            # Se for um campo numérico e quiser busca exata, use:
            # try:
            #     seq_int = int(sequencial_erp_filter)
            #     queryset = queryset.filter(sequencial_baixa_erp=seq_int)
            # except ValueError:
            #     logger.warning(f"Sequencial ERP inválido (não numérico): {sequencial_erp_filter}")
            #     queryset = queryset.none() # Garante que nada seja retornado para um valor inválido


        # 5. Filtro por Data de Entrega
        data_inicio_str = self.request.GET.get('data_inicio')
        data_fim_str = self.request.GET.get('data_fim')

        if data_inicio_str:
            try:
                data_inicio = datetime.strptime(data_inicio_str, '%Y-%m-%d').date()
                queryset = queryset.filter(data_entrega__gte=data_inicio)
            except ValueError:
                logger.warning(f"Data de início inválida: {data_inicio_str}")
                pass # Ignora data inválida

        if data_fim_str:
            try:
                data_fim = datetime.strptime(data_fim_str, '%Y-%m-%d').date()
                queryset = queryset.filter(data_entrega__lte=data_fim)
            except ValueError:
                logger.warning(f"Data de fim inválida: {data_fim_str}")
                pass # Ignora data inválida
        
        # 6. Filtro por Colaborador
        colaborador_filter = self.request.GET.get('colaborador')
        if colaborador_filter:
            queryset = queryset.filter(colaborador__icontains=colaborador_filter) 
            

        return queryset.order_by(
            'centro_custo', 'descricao_centro_custo', 'data_entrega', 'codigo_estoque'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_params'] = {
            'status': self.request.GET.get('status', 'todos'),
            'contrato': self.request.GET.get('contrato', ''),
            'colaborador': self.request.GET.get('colaborador', ''),
            'epi_tecnicon': self.request.GET.get('epi_tecnicon', ''),
            'sequencial_erp': self.request.GET.get('sequencial_erp', ''),
            'data_inicio': self.request.GET.get('data_inicio', ''),
            'data_fim': self.request.GET.get('data_fim', ''),
        }
        context['status_choices'] = EntregaEPI.STATUS_CHOICES
        return context


# View para Entregas PENDENTES (página principal)
class EntregasEPIListView(LoginRequiredMixin,
                          PermissionRequiredMixin,
                          EntregaEPIFilterMixin,
                          ListView):
    template_name = "rh/entregas_epi.html"
    permission_required = "rh.delivery_epis"
    paginate_by = None
    model = EntregaEPI

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(status=EntregaEPI.STATUS_PENDENTE)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['grouped_entregas'] = _prepare_grouped_entregas(self.get_queryset())
        context['current_report_type'] = 'pendentes'
        return context

# View para TODAS as Entregas
class TodasEntregasEPIListView(LoginRequiredMixin,
                               PermissionRequiredMixin,
                               EntregaEPIFilterMixin,
                               ListView):
    template_name = "rh/entregas_epi.html"
    permission_required = "rh.delivery_epis"
    paginate_by = None
    model = EntregaEPI

    def get_queryset(self):
        return super().get_queryset()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['grouped_entregas'] = _prepare_grouped_entregas(self.get_queryset())
        context['current_report_type'] = 'todas'
        return context


@require_POST
@login_required
@permission_required('rh.delivery_epis', raise_exception=True)
def baixar_entrega_epi(request):
    try:
        data = json.loads(request.body)
        ids_to_baixar = data.get('ids')
        sequencial_baixa = data.get('sequencial_baixa')

        if not ids_to_baixar or not isinstance(ids_to_baixar, list):
            return JsonResponse({'success': False, 'message': 'IDs de entrega inválidos ou ausentes.'}, status=400)
        
        if not sequencial_baixa:
            return JsonResponse({'success': False, 'message': 'Sequencial da baixa é obrigatório.'}, status=400)
        
        with transaction.atomic():
            entregas_a_baixar = EntregaEPI.objects.filter(id__in=ids_to_baixar)
            
            if not entregas_a_baixar.exists():
                 return JsonResponse({'success': False, 'message': 'Nenhuma entrega encontrada para os IDs fornecidos.'}, status=404)

            for entrega_epi in entregas_a_baixar:
                if entrega_epi.status == EntregaEPI.STATUS_PENDENTE:
                    entrega_epi.marcar_como_baixado(sequencial_baixa)
                else:
                    logger.warning(f"Tentativa de baixar entrega já não pendente (ID: {entrega_epi.id}, Status: {entrega_epi.status})")
        
        return JsonResponse({'success': True, 'message': f'{entregas_a_baixar.count()} entregas processadas para baixa!'})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Requisição inválida. Esperado JSON.'}, status=400)
    except Exception as e:
        logger.exception("Erro ao baixar entregas") # Loga a exceção completa
        return JsonResponse({'success': False, 'message': f'Erro ao baixar entregas: {str(e)}'}, status=500)


@require_POST
@login_required
@permission_required('rh.delivery_epis', raise_exception=True)
def reverter_entrega_epi(request, pk):
    try:
        entrega_epi = get_object_or_404(EntregaEPI, pk=pk)
        
        with transaction.atomic():
            if entrega_epi.status == EntregaEPI.STATUS_BAIXADO:
                entrega_epi.reverter_para_pendente()
            else:
                logger.warning(f"Tentativa de reverter entrega já não baixada (ID: {entrega_epi.id}, Status: {entrega_epi.status})")
        
        return JsonResponse({'success': True, 'message': 'Status revertido para Pendente.'})

    except Exception as e:
        logger.exception("Erro ao reverter status de entrega") # Loga a exceção completa
        return JsonResponse({'success': False, 'message': f'Erro ao reverter status: {str(e)}'}, status=500)