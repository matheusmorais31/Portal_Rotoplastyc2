# documentos/views.py

from django.shortcuts import render, redirect, get_object_or_404
from .models import Categoria, Documento
from .forms import CategoriaForm, DocumentoForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth import get_user_model

User = get_user_model()

# View para listar categorias
@login_required
def listar_categorias(request):
    categorias = Categoria.objects.all()
    return render(request, 'documentos/listar_categorias.html', {'categorias': categorias})

# View para criar nova categoria
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

# View para editar categoria
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

# View para excluir categoria
@login_required
@permission_required('documentos.delete_categoria', raise_exception=True)
def excluir_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        categoria.delete()
        messages.success(request, 'Categoria excluída com sucesso!')
        return redirect('documentos:listar_categorias')
    return render(request, 'documentos/excluir_categoria.html', {'categoria': categoria})

# Função auxiliar para verificar se o usuário tem permissão para aprovar documentos
def has_approval_permission(user):
    return user.has_perm('documentos.can_approve')

# View para criar novo documento
@login_required
@permission_required('documentos.add_documento', raise_exception=True)
def criar_documento(request):
    if request.method == 'POST':
        form = DocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            documento = form.save()
            messages.success(request, 'Documento criado com sucesso!')
            return redirect('documentos:listar_documentos')
    else:
        form = DocumentoForm()
    return render(request, 'documentos/criar_documento.html', {'form': form})

# View para listar documentos
@login_required
def listar_documentos(request):
    documentos = Documento.objects.all()
    return render(request, 'documentos/listar_documentos.html', {'documentos': documentos})

# View para aprovar documento
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

    return redirect('documentos:listar_documentos')
