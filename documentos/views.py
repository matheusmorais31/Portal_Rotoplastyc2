# documentos/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth import get_user_model
from django.core.files import File
from django.conf import settings
from .models import Documento, Categoria, Acesso
from .forms import DocumentoForm, CategoriaForm, AnaliseDocumentoForm, NovaRevisaoForm
from django.db import transaction, IntegrityError
import logging
import os
from django.http import HttpResponse, Http404
from django.http import FileResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_http_methods


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
    if request.method == 'POST':
        form = DocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    documento = form.save(commit=False)
                    documento.elaborador = request.user
                    documento.status = 'aguardando_analise'  # **Alteração para definir status inicial**
                    documento.save()
                    messages.success(request, 'Documento criado e enviado para análise.')
                    return redirect('documentos:listar_documentos_aprovados')
            except IntegrityError as e:
                logger.error(f"Erro de integridade ao criar documento: {e}")
                messages.error(request, 'Erro ao criar o documento.')
            except Exception as e:
                logger.error(f"Erro inesperado ao criar documento: {e}", exc_info=True)
                messages.error(request, 'Erro inesperado ao criar o documento.')
    else:
        form = DocumentoForm()
    return render(request, 'documentos/criar_documento.html', {'form': form})

@login_required
@permission_required('documentos.can_analyze', raise_exception=True)
def listar_documentos_para_analise(request):
    documentos = Documento.objects.filter(status='aguardando_analise')  # **Filtra documentos aguardando análise**
    if request.method == 'POST':
        documento_id = request.POST.get('documento_id')
        action = request.POST.get('action')
        documento = get_object_or_404(Documento, id=documento_id, status='aguardando_analise')
        
        if action == 'upload':
            form = AnaliseDocumentoForm(request.POST, request.FILES, instance=documento)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        documento = form.save(commit=False)
                        documento.status = 'analise_concluida'  # **Alteração de status após análise**
                        documento.analista = request.user  # **Registro do analista**
                        documento.save()
                        messages.success(request, f'Documento "{documento.nome}" analisado com sucesso!')
                        # As notificações serão enviadas pelo sinal após salvar o documento
                        return redirect('documentos:listar_documentos_para_analise')
                except Exception as e:
                    logger.error(f"Erro ao analisar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao fazer upload do documento revisado.')
            else:
                messages.error(request, 'Erro ao fazer upload do documento revisado.')
        
        elif action == 'reprovar':
            motivo = request.POST.get('motivo_reprovacao')
            if motivo:
                try:
                    with transaction.atomic():
                        documento.status = 'reprovado'  # **Alteração de status para reprovado**
                        documento.motivo_reprovacao = motivo  # **Registro do motivo da reprovação**
                        documento.analista = request.user  # **Registro do analista**
                        documento.save()
                        messages.success(request, f'Documento "{documento.nome}" reprovado com sucesso!')
                        # As notificações serão enviadas pelo sinal após salvar o documento
                except Exception as e:
                    logger.error(f"Erro ao reprovar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao reprovar o documento.')
            else:
                messages.error(request, 'É necessário informar o motivo da reprovação.')
    return render(request, 'documentos/listar_documentos_para_analise.html', {'documentos': documentos, 'titulo': 'Documentos para Análise'})

@login_required
@permission_required('documentos.change_documento', raise_exception=True)
def substituir_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)

    if request.method == 'POST' and request.FILES.get('novo_documento'):
        novo_documento = request.FILES['novo_documento']

        # Remove o documento antigo se existir
        if documento.documento:
            if os.path.isfile(documento.documento.path):
                os.remove(documento.documento.path)

        # Substitui pelo novo documento
        documento.documento = novo_documento
        documento.status = 'aguardando_analise'  # **Redefine status para aguardar nova análise**
        documento.save()

        messages.success(request, 'Documento substituído com sucesso.')
        return redirect('documentos:listar_documentos_para_analise')

    messages.error(request, 'Erro ao substituir o documento.')
    return redirect('documentos:listar_documentos_para_analise')

@login_required
@permission_required('documentos.change_documento', raise_exception=True)
def atualizar_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if request.method == 'POST':
        novo_arquivo = request.FILES.get('documento')
        novo_status = request.POST.get('status')

        if novo_arquivo and novo_status == 'analise_concluida':
            documento.documento = novo_arquivo
            documento.status = novo_status  # **Alteração de status para análise concluída**
            documento.save()
            messages.success(request, 'Documento atualizado com sucesso e enviado para aprovação do elaborador.')
        else:
            messages.error(request, 'Falha ao atualizar o documento.')
    return redirect('documentos:listar_documentos_para_analise')

@login_required
@permission_required('documentos.can_approve', raise_exception=True)
def aprovar_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if documento.status != 'aguardando_analise':
        messages.error(request, "Este documento não está em estado de análise.")
        return redirect('documentos:listar_documentos_para_analise')

    try:
        with transaction.atomic():
            # Bloquear o documento para evitar condições de corrida
            documento = Documento.objects.select_for_update().get(id=documento_id)
            documento.status = 'aguardando_elaborador'  # **Alteração de status para aguardar aprovação do elaborador**
            documento.aprovado_por_aprovador1 = True  # **Atualização do campo de aprovação**
            documento.gerar_pdf()
            documento.save()
            messages.success(request, "Documento aprovado e PDF gerado com sucesso.")
            # As notificações serão enviadas pelo sinal após salvar o documento
    except Documento.DoesNotExist:
        messages.error(request, "Documento não encontrado.")
    except Exception as e:
        logger.error(f"Erro ao aprovar documento {documento_id}: {e}")
        messages.error(request, "Ocorreu um erro ao aprovar o documento.")
    
    return redirect('documentos:listar_documentos_para_analise')

@login_required
def listar_aprovacoes_pendentes(request):
    user = request.user
    documentos = Documento.objects.none()

    # Verifica se o usuário é elaborador ou aprovador e lista os documentos apropriados
    if Documento.objects.filter(elaborador=user, status__in=['analise_concluida', 'aguardando_elaborador']).exists():
        documentos = Documento.objects.filter(elaborador=user, status__in=['analise_concluida', 'aguardando_elaborador'])
    elif Documento.objects.filter(aprovador1=user, status='aguardando_aprovador1').exists():
        documentos = Documento.objects.filter(aprovador1=user, status='aguardando_aprovador1')

    if request.method == 'POST':
        documento_id = request.POST.get('documento_id')
        action = request.POST.get('action')
        documento = get_object_or_404(Documento, id=documento_id)

        if action == 'aprovar':
            if documento.status in ['analise_concluida', 'aguardando_elaborador'] and user == documento.elaborador:
                try:
                    with transaction.atomic():
                        documento.status = 'aguardando_aprovador1'  # **Alteração de status para aguardar aprovador1**
                        documento.save()
                        messages.success(request, 'Documento aprovado e enviado para o Aprovador.')
                        # As notificações serão enviadas pelo sinal após salvar o documento
                except Exception as e:
                    logger.error(f"Erro ao aprovar documento {documento_id}: {e}")
                    messages.error(request, 'Erro ao aprovar o documento.')
            elif documento.status == 'aguardando_aprovador1' and user == documento.aprovador1:
                try:
                    with transaction.atomic():
                        documento.aprovado_por_aprovador1 = True
                        documento.status = 'aprovado'  # **Alteração de status para aprovado**
                        documento.gerar_pdf()
                        documento.save()
                        messages.success(request, 'Documento aprovado com sucesso!')
                        # As notificações serão enviadas pelo sinal após salvar o documento
                except Exception as e:
                    logger.error(f"Erro ao aprovar documento {documento_id}: {e}")
                    messages.error(request, 'Erro ao aprovar o documento.')
            else:
                messages.error(request, 'Você não tem permissão para aprovar este documento.')
        elif action == 'reprovar':
            motivo = request.POST.get('motivo_reprovacao')
            if motivo:
                try:
                    with transaction.atomic():
                        documento.status = 'reprovado'  # **Alteração de status para reprovado**
                        documento.motivo_reprovacao = motivo  # **Registro do motivo da reprovação**
                        documento.save()
                        messages.success(request, 'Documento reprovado com sucesso!')
                        # As notificações serão enviadas pelo sinal após salvar o documento
                except Exception as e:
                    logger.error(f"Erro ao reprovar documento {documento_id}: {e}")
                    messages.error(request, 'Erro ao reprovar o documento.')
            else:
                messages.error(request, 'É necessário informar o motivo da reprovação.')
    return render(request, 'documentos/listar_aprovacoes_pendentes.html', {'documentos': documentos, 'titulo': 'Aprovações Pendentes'})

@login_required
def listar_documentos_aprovados(request):
    documentos = Documento.objects.filter(status='aprovado').order_by('nome', '-revisao')
    documentos_unicos = {}
    for doc in documentos:
        if doc.nome not in documentos_unicos:
            documentos_unicos[doc.nome] = doc
    documentos = list(documentos_unicos.values())
    documentos.sort(key=lambda x: x.nome)
    return render(request, 'documentos/listar_documentos.html', {'documentos': documentos, 'titulo': 'Documentos Aprovados'})

# documentos/views.py
from django.urls import reverse

# views.py
from django.urls import reverse

@login_required
@xframe_options_sameorigin
def visualizar_documento(request, id):
    documento = get_object_or_404(Documento, id=id)

    # Registrar o acesso
    if request.user.is_authenticated:
        Acesso.objects.create(documento=documento, usuario=request.user)

    # Construir a URL absoluta do PDF usando a view 'visualizar_pdf'
    if documento.documento_pdf:
        pdf_url = request.build_absolute_uri(reverse('documentos:visualizar_pdf', args=[documento.id]))
    else:
        pdf_url = None

    response = render(request, 'documentos/visualizar_documento.html', {
        'documento': documento,
        'pdf_url': pdf_url
    })

    # Adicionar cabeçalhos de segurança
    response['Cross-Origin-Opener-Policy'] = 'same-origin'
    response['Cross-Origin-Embedder-Policy'] = 'require-corp'

    return response




@login_required
def visualizar_pdf(request, id):
    documento = get_object_or_404(Documento, id=id)

    if not documento.documento_pdf:
        raise Http404("Documento PDF não encontrado.")

    try:
        return FileResponse(open(documento.documento_pdf.path, 'rb'), content_type='application/pdf')
    except IOError:
        raise Http404("Erro ao abrir o arquivo PDF.")


@login_required
def baixar_pdf(request, id):
    documento = get_object_or_404(Documento, id=id)

    # Impede o download se a categoria for bloqueada
    if documento.categoria.bloqueada:
        messages.error(request, "Você não tem permissão para baixar este documento.")
        return redirect('documentos:visualizar_documento', id=id)

    # Verifique se o documento existe
    if not documento.documento_pdf:
        raise Http404("Documento PDF não encontrado.")

    # Servir o arquivo como download
    file_path = documento.documento_pdf.path
    response = FileResponse(open(file_path, 'rb'), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(os.path.basename(file_path))
    return response


@login_required
def visualizar_acessos_documento(request, id):
    documento = get_object_or_404(Documento, id=id)
    acessos = Acesso.objects.filter(documento=documento)
    return render(request, 'documentos/visualizar_acessos.html', {'documento': documento, 'acessos': acessos})

@login_required
def listar_documentos_reprovados(request):
    documentos_reprovados = Documento.objects.filter(elaborador=request.user, status='reprovado')
    return render(request, 'documentos/lista_reprovados.html', {'documentos': documentos_reprovados, 'titulo': 'Documentos Reprovados'})

@login_required
@permission_required('documentos.add_documento', raise_exception=True)
def nova_revisao(request, documento_id):
    documento_atual = get_object_or_404(Documento, id=documento_id)
    
    # Verificar se há revisões pendentes para o mesmo documento
    revisoes_pendentes = Documento.objects.filter(
        nome=documento_atual.nome,
        status__in=['aguardando_analise', 'analise_concluida', 'aguardando_aprovador1', 'aguardando_elaborador']
    ).exclude(id=documento_atual.id)

    if revisoes_pendentes.exists():
        # Pega a revisão pendente
        revisao_pendente = revisoes_pendentes.first()
        # Cria mensagem com o status
        mensagem = f"Não é possível criar uma nova revisão enquanto houver revisões pendentes de aprovação. Status da revisão pendente: {revisao_pendente.get_status_display()}."
        return render(request, 'documentos/nova_revisao.html', {
            'documento': documento_atual,
            'mensagem': mensagem,
            'revisao_pendente': revisao_pendente
        })

    if request.method == 'POST':
        form = NovaRevisaoForm(request.POST, request.FILES, documento_atual=documento_atual)
        if form.is_valid():
            try:
                with transaction.atomic():
                    nova_revisao = form.save(commit=False)
                    nova_revisao.nome = documento_atual.nome  # Mantém o mesmo nome
                    nova_revisao.categoria = documento_atual.categoria
                    nova_revisao.elaborador = request.user
                    nova_revisao.status = 'aguardando_analise'  # **Define status para iniciar o fluxo**
                    nova_revisao.save()
                    messages.success(request, 'Nova revisão criada com sucesso!')
                    return redirect('documentos:listar_aprovacoes_pendentes')
            except Exception as e:
                logger.error(f'Erro ao criar nova revisão: {e}', exc_info=True)
                messages.error(request, f'Ocorreu um erro ao criar a nova revisão: {e}')
        else:
            messages.error(request, 'Por favor, corrija os erros no formulário.')
    else:
        form = NovaRevisaoForm(documento_atual=documento_atual)
    return render(request, 'documentos/nova_revisao.html', {'form': form, 'documento': documento_atual})

@login_required
@permission_required('documentos.change_documento', raise_exception=True)
def upload_documento_revisado(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)

    if request.method == 'POST' and request.FILES.get('documento'):
        novo_documento = request.FILES['documento']
        
        # Verificar extensão do arquivo
        if not novo_documento.name.lower().endswith(('.doc', '.docx', '.odt')):
            messages.error(request, 'Formato de arquivo inválido. Apenas arquivos .doc, .docx e .odt são permitidos.')
            return redirect('documentos:listar_documentos_para_analise')

        try:
            with transaction.atomic():
                # Remover o documento antigo, se existir
                if documento.documento:
                    documento.remover_pdf_antigo()  # Remover o PDF antigo associado
                    documento.documento.delete()    # Deletar o documento editável antigo
                
                # Salvar o novo documento revisado
                documento.documento.save(novo_documento.name, novo_documento)
                
                documento.status = 'aguardando_analise'  # **Redefine status para aguardar nova análise**
                documento.save(update_fields=['documento', 'status'])
                
                messages.success(request, 'Documento revisado carregado com sucesso. Ele será analisado antes de ser aprovado.')
        except Exception as e:
            messages.error(request, f'Ocorreu um erro ao carregar o documento revisado: {e}')

    return redirect('documentos:listar_documentos_para_analise')

@login_required
@permission_required('documentos.can_view_editables', raise_exception=True)
def listar_documentos_editaveis(request):
    categorias = Categoria.objects.all()
    documentos_por_categoria = {}

    for categoria in categorias:
        documentos = Documento.objects.filter(
            categoria=categoria,
            status='aprovado'
        ).order_by('nome', '-revisao')

        documentos_unicos = {}
        for doc in documentos:
            if doc.nome not in documentos_unicos:
                documentos_unicos[doc.nome] = doc
        documentos = list(documentos_unicos.values())
        documentos.sort(key=lambda x: x.nome)

        if documentos:
            documentos_por_categoria[categoria] = documentos

    return render(request, 'documentos/listar_documentos_editaveis.html', {
        'documentos_por_categoria': documentos_por_categoria,
        'titulo': 'Documentos Editáveis',
    })
