from django.shortcuts import render, redirect, get_object_or_404
from .models import Categoria, Documento, Acesso
from .forms import CategoriaForm, DocumentoForm, NovaRevisaoForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import PermissionDenied
from django.db.models import F, Subquery, OuterRef
from django.db import transaction
import logging, json

logger = logging.getLogger('django')

User = get_user_model()

@login_required
def listar_categorias(request):
    categorias = Categoria.objects.all()
    return render(request, 'documentos/listar_categorias.html', {'categorias': categorias})

@login_required
@permission_required('documentos.add_categoria', raise_exception=True)
def criar_categoria(request):
    if request.method == 'POST':
        form = CategoriaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoria criada com sucesso!')
            return redirect('documentos:listar_categorias')
    else:
        form = CategoriaForm()
    return render(request, 'documentos/criar_categoria.html', {'form': form})

@login_required
@permission_required('documentos.change_categoria', raise_exception=True)
def editar_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        form = CategoriaForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            messages.success(request, 'Categoria atualizada com sucesso!')
            return redirect('documentos:listar_categorias')
    else:
        form = CategoriaForm(instance=categoria)
    return render(request, 'documentos/editar_categoria.html', {'form': form})

@login_required
@permission_required('documentos.delete_categoria', raise_exception=True)
def excluir_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        categoria.delete()
        messages.success(request, 'Categoria excluída com sucesso!')
        return redirect('documentos:listar_categorias')
    return render(request, 'documentos/excluir_categoria.html', {'categoria': categoria})

@login_required
@permission_required('documentos.add_documento', raise_exception=True)
def criar_documento(request):
    logger.debug(f"[criar_documento] Iniciando processo de criação de documento para o usuário: {request.user.username}")
    
    if request.method == 'POST':
        logger.debug("[criar_documento] Recebendo dados do formulário POST")
        form = DocumentoForm(request.POST, request.FILES)
        
        if form.is_valid():
            logger.debug("[criar_documento] Formulário válido. Tentando salvar o documento.")
            try:
                with transaction.atomic():
                    documento = form.save(commit=False)  # Não salvar imediatamente
                    documento.elaborador = request.user  # Atribuir o elaborador manualmente
                    documento.save()  # Agora salva o documento com o elaborador atribuído
                    logger.info(f"[criar_documento] Documento criado com sucesso: {documento.nome} - Revisão {documento.revisao}")
                    messages.success(request, 'Documento criado com sucesso!')
                    return redirect('documentos:listar_documentos_aprovados')
            except Exception as e:
                logger.error(f"[criar_documento] Erro ao salvar documento: {e}", exc_info=True)
                messages.error(request, f'Ocorreu um erro ao criar o documento: {e}')
        else:
            logger.warning(f"[criar_documento] Formulário inválido. Erros: {form.errors}")
    else:
        logger.debug("[criar_documento] Requisição GET recebida. Renderizando formulário vazio.")
        form = DocumentoForm()

    return render(request, 'documentos/criar_documento.html', {'form': form})


@login_required
def listar_documentos_aprovados(request):
    subquery = Documento.objects.filter(
        nome=OuterRef('nome'),
        aprovado_por_aprovador1=True,
        aprovado_por_aprovador2=True
    ).order_by('-revisao').values('revisao')[:1]

    documentos = Documento.objects.filter(
        aprovado_por_aprovador1=True,
        aprovado_por_aprovador2=True
    ).annotate(
        ultima_revisao=Subquery(subquery)
    ).filter(
        revisao=F('ultima_revisao')
    ).order_by('nome')

    return render(request, 'documentos/listar_documentos.html', {
        'documentos': documentos,
        'titulo': 'Documentos Aprovados'
    })

@login_required
def listar_aprovacoes_pendentes(request):
    user = request.user
    # Filtrar apenas os documentos que não foram reprovados e que estão pendentes de aprovação
    documentos_pendentes_aprovador1 = Documento.objects.filter(aprovador1=user, aprovado_por_aprovador1=False, reprovado=False)
    documentos_pendentes_aprovador2 = Documento.objects.filter(aprovador2=user, aprovado_por_aprovador1=True, aprovado_por_aprovador2=False, reprovado=False)
    
    # Combina os documentos pendentes de ambos os aprovadores
    documentos_pendentes = documentos_pendentes_aprovador1.union(documentos_pendentes_aprovador2)

    return render(request, 'documentos/listar_aprovacoes_pendentes.html', {
        'documentos': documentos_pendentes,
        'titulo': 'Aprovações Pendentes'
    })

@login_required
@csrf_exempt
def reprovar_documento(request, documento_id):
    if request.method == 'POST':
        documento = get_object_or_404(Documento, id=documento_id)
        user = request.user

        if not user.has_perm('documentos.can_reject'):
            return JsonResponse({'status': 'error', 'message': 'Você não tem permissão para reprovar este documento.'})

        if user == documento.aprovador1 or user == documento.aprovador2:
            try:
                data = json.loads(request.body)
                motivo = data.get('motivo', '')

                if not motivo:
                    return JsonResponse({'status': 'error', 'message': 'Motivo de reprovação não pode estar vazio.'})

                # Marcar o documento como reprovado
                documento.reprovado = True
                documento.motivo_reprovacao = motivo
                documento.save()

                return JsonResponse({'status': 'success', 'message': 'Documento reprovado com sucesso.'})
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': 'Erro ao processar o JSON enviado.'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Você não pode reprovar este documento.'})
    
    return JsonResponse({'status': 'error', 'message': 'Método não permitido.'})

@login_required
@user_passes_test(lambda user: user.has_perm('documentos.can_approve'))
def aprovar_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    user = request.user
    logger.debug(f"Tentando aprovar o documento: {documento.nome} por {user.get_full_name()}")

    if user == documento.aprovador1 and not documento.aprovado_por_aprovador1:
        Documento.objects.filter(pk=documento.pk).update(aprovado_por_aprovador1=True)
        logger.debug(f"Documento {documento.nome} aprovado por Aprovador 1.")
        messages.success(request, 'Documento aprovado por Aprovador 1.')
    elif user == documento.aprovador2 and documento.aprovado_por_aprovador1 and not documento.aprovado_por_aprovador2:
        Documento.objects.filter(pk=documento.pk).update(aprovado_por_aprovador2=True)
        logger.debug(f"Documento {documento.nome} aprovado por Aprovador 2.")
        messages.success(request, 'Documento aprovado por Aprovador 2.')
    else:
        logger.debug(f"Erro ao tentar aprovar o documento {documento.nome} pelo usuário {user.get_full_name()}")
        messages.error(request, 'Você não tem permissão para aprovar este documento no momento.')

    return redirect('documentos:listar_aprovacoes_pendentes')

@login_required
@permission_required('documentos.add_documento', raise_exception=True)
def nova_revisao(request, documento_id):
    documento_atual = get_object_or_404(Documento, id=documento_id)
    
    revisoes_pendentes = Documento.objects.filter(
        nome=documento_atual.nome,
        aprovado_por_aprovador1=False,
        aprovado_por_aprovador2=False
    ).exclude(id=documento_atual.id)

    # Verificar se há revisões pendentes
    if revisoes_pendentes.exists():
        # Renderiza o template com uma mensagem de erro ao invés de redirecionar
        messages.error(request, 'Não é possível criar uma nova revisão enquanto houver revisões pendentes de aprovação.')
        return render(request, 'documentos/nova_revisao.html', {
            'form': None,
            'documento': documento_atual,
            'erro_revisao_pendente': True,
        })

    if request.method == 'POST':
        form = NovaRevisaoForm(request.POST, request.FILES, documento_atual=documento_atual)
        if form.is_valid():
            nova_revisao = form.save(commit=False)
            nova_revisao.categoria = documento_atual.categoria
            nova_revisao.elaborador = request.user
            nova_revisao.save()
            messages.success(request, 'Nova revisão criada com sucesso!')
            return redirect('documentos:listar_aprovacoes_pendentes')
    else:
        form = NovaRevisaoForm(documento_atual=documento_atual)

    return render(request, 'documentos/nova_revisao.html', {'form': form, 'documento': documento_atual})

@login_required
def visualizar_documento(request, id):
    documento = get_object_or_404(Documento, id=id)
    # Registrar o acesso
    if request.user.is_authenticated:
        Acesso.objects.create(documento=documento, usuario=request.user)
    # Renderizar a visualização do documento
    return render(request, 'documentos/visualizar_documento.html', {'documento': documento})

@login_required
def visualizar_acessos_documento(request, id):
    documento = get_object_or_404(Documento, id=id)
    acessos = Acesso.objects.filter(documento=documento)
    return render(request, 'documentos/visualizar_acessos.html', {'documento': documento, 'acessos': acessos})

@login_required
def listar_documentos_reprovados(request):
    # Filtrar apenas documentos reprovados onde o usuário logado é o elaborador
    documentos_reprovados = Documento.objects.filter(elaborador=request.user, reprovado=True)

    return render(request, 'documentos/lista_reprovados.html', {
        'documentos': documentos_reprovados,
        'titulo': 'Documentos Reprovados'
    })
