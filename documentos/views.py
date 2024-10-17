# documentos/views.py

from django.shortcuts import render, redirect, get_object_or_404
from .models import Categoria, Documento
<<<<<<< HEAD
from .forms import CategoriaForm, DocumentoForm, NovaRevisaoForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import PermissionDenied
from django.db.models import Max, F, Subquery, OuterRef
=======
from .forms import CategoriaForm, DocumentoForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth import get_user_model
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22

User = get_user_model()

# View para listar categorias
@login_required
def listar_categorias(request):
    categorias = Categoria.objects.all()
    return render(request, 'documentos/listar_categorias.html', {'categorias': categorias})

<<<<<<< HEAD
=======
# View para criar nova categoria
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
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

<<<<<<< HEAD
=======
# View para editar categoria
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
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

<<<<<<< HEAD
=======
# View para excluir categoria
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
@login_required
@permission_required('documentos.delete_categoria', raise_exception=True)
def excluir_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        categoria.delete()
        messages.success(request, 'Categoria excluída com sucesso!')
        return redirect('documentos:listar_categorias')
    return render(request, 'documentos/excluir_categoria.html', {'categoria': categoria})

<<<<<<< HEAD
def has_approval_permission(user):
    return user.has_perm('documentos.can_approve')

=======
# Função auxiliar para verificar se o usuário tem permissão para aprovar documentos
def has_approval_permission(user):
    return user.has_perm('documentos.can_approve')

# View para criar novo documento
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
@login_required
@permission_required('documentos.add_documento', raise_exception=True)
def criar_documento(request):
    if request.method == 'POST':
        form = DocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            documento = form.save()
            messages.success(request, 'Documento criado com sucesso!')
<<<<<<< HEAD
            return redirect('documentos:listar_documentos_aprovados')
=======
            return redirect('documentos:listar_documentos')
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
    else:
        form = DocumentoForm()
    return render(request, 'documentos/criar_documento.html', {'form': form})

<<<<<<< HEAD
@login_required
def listar_documentos_aprovados(request):
    """Exibe apenas a última revisão aprovada de cada documento."""
    # Subconsulta para obter a última revisão aprovada de cada documento
    subquery = Documento.objects.filter(
        nome=OuterRef('nome'),
        aprovado_por_aprovador1=True,
        aprovado_por_aprovador2=True
    ).order_by('-revisao').values('revisao')[:1]

    # Filtra os documentos que correspondem à última revisão aprovada
    documentos = Documento.objects.filter(
        aprovado_por_aprovador1=True,
        aprovado_por_aprovador2=True
    ).annotate(
        ultima_revisao=Subquery(subquery)
    ).filter(
        revisao=F('ultima_revisao')
    ).order_by('nome')

    return render(request, 'documentos/listar_documentos.html', {'documentos': documentos, 'titulo': 'Documentos Aprovados'})

@login_required
def listar_aprovacoes_pendentes(request):
    """Exibe os documentos que o usuário logado precisa aprovar."""
    user = request.user

    # Pendentes para o aprovador 1
    documentos_pendentes_aprovador1 = Documento.objects.filter(aprovador1=user, aprovado_por_aprovador1=False)

    # Pendentes para o aprovador 2 (somente se já foi aprovado por Aprovador 1)
    documentos_pendentes_aprovador2 = Documento.objects.filter(aprovador2=user, aprovado_por_aprovador1=True, aprovado_por_aprovador2=False)

    # Combina os dois conjuntos de documentos
    documentos_pendentes = documentos_pendentes_aprovador1.union(documentos_pendentes_aprovador2)

    return render(request, 'documentos/listar_aprovacoes_pendentes.html', {'documentos': documentos_pendentes, 'titulo': 'Aprovações Pendentes'})

@login_required
@csrf_exempt  # Desativa a verificação CSRF para ser chamada via AJAX
def reprovar_documento(request, documento_id):
    """Processa a reprovação de um documento."""
    if request.method == 'POST':
        documento = get_object_or_404(Documento, id=documento_id)
        user = request.user

        # Checa permissões
        if not user.has_perm('documentos.can_reject'):
            raise PermissionDenied("Você não tem permissão para reprovar este documento.")

        # Verifica se o usuário é um dos aprovadores
        if user == documento.aprovador1 or user == documento.aprovador2:
            motivo = request.POST.get('motivo')

            # Atualiza o documento com o motivo da reprovação
            documento.reprovado = True
            documento.motivo_reprovacao = motivo
            documento.save()

            return JsonResponse({'status': 'success'})
        else:
            return JsonResponse({'status': 'error', 'message': 'Você não pode reprovar este documento.'})
    
    return JsonResponse({'status': 'error', 'message': 'Método não permitido.'})

=======
# View para listar documentos
@login_required
def listar_documentos(request):
    documentos = Documento.objects.all()
    return render(request, 'documentos/listar_documentos.html', {'documentos': documentos})

# View para aprovar documento
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
@login_required
@user_passes_test(has_approval_permission)
def aprovar_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    user = request.user

    if user == documento.aprovador1 and not documento.aprovado_por_aprovador1:
        documento.aprovado_por_aprovador1 = True
        documento.save()
        messages.success(request, 'Documento aprovado por Aprovador 1.')
    elif user == documento.aprovador2 and documento.aprovado_por_aprovador1 and not documento.aprovado_por_aprovador2:
        documento.aprovado_por_aprovador2 = True
        documento.save()
        messages.success(request, 'Documento aprovado por Aprovador 2.')
    else:
        messages.error(request, 'Você não tem permissão para aprovar este documento no momento.')

<<<<<<< HEAD
    return redirect('documentos:listar_aprovacoes_pendentes')

def visualizar_documento(request, id):
    documento = get_object_or_404(Documento, id=id)
    return render(request, 'documentos/visualizar_documento.html', {'documento': documento})

@login_required
@permission_required('documentos.add_documento', raise_exception=True)
def nova_revisao(request, documento_id):
    documento_atual = get_object_or_404(Documento, id=documento_id)

    # Verifica se há alguma revisão pendente de aprovação para este documento
    revisoes_pendentes = Documento.objects.filter(
        nome=documento_atual.nome,
        aprovado_por_aprovador1=False,
        aprovado_por_aprovador2=False
    ).exclude(id=documento_atual.id)

    if revisoes_pendentes.exists():
        messages.error(request, 'Não é possível criar uma nova revisão enquanto houver revisões pendentes de aprovação.')
        return redirect('documentos:listar_documentos_aprovados')

    if request.method == 'POST':
        form = NovaRevisaoForm(request.POST, request.FILES, documento_atual=documento_atual)
        if form.is_valid():
            nova_revisao = form.save(commit=False)
            nova_revisao.categoria = documento_atual.categoria  # Mantém a mesma categoria
            nova_revisao.save()
            messages.success(request, 'Nova revisão criada com sucesso!')
            return redirect('documentos:listar_aprovacoes_pendentes')
    else:
        form = NovaRevisaoForm(documento_atual=documento_atual)
    return render(request, 'documentos/nova_revisao.html', {'form': form, 'documento': documento_atual})
=======
    return redirect('documentos:listar_documentos')
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
