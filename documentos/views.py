from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth import get_user_model
from django.core.files import File
from django.conf import settings
from .models import Documento, Categoria, Acesso, DocumentoDeletado
from .forms import DocumentoForm, CategoriaForm, AnaliseDocumentoForm, NovaRevisaoForm
from django.db import transaction, IntegrityError
import logging
import os
from django.http import HttpResponse, Http404, FileResponse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from django.utils import timezone
import pandas as pd

# Alterado para usar o logger "documentos"
logger = logging.getLogger('documentos')
User = get_user_model()
logging
# Função para listar as categorias
@login_required
@permission_required('documentos.view_categoria', raise_exception=True)
def listar_categorias(request):
    categorias = Categoria.objects.all()
    return render(request, 'documentos/listar_categorias.html', {'categorias': categorias})

# Função para criar categoria
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

# Função para editar categoria
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

# Função para deletar categoria
@login_required
@permission_required('documentos.delete_categoria', raise_exception=True)
def excluir_categoria(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        categoria.delete()
        messages.success(request, 'Categoria excluída com sucesso!')
        return redirect('documentos:listar_categorias')
    return render(request, 'documentos/excluir_categoria.html', {'categoria': categoria})

# Função para criar documentos
@login_required
@permission_required('documentos.can_add_documento', raise_exception=True)
def criar_documento(request):
    if request.method == 'POST':
        form = DocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    documento = form.save(commit=False)
                    documento.elaborador = request.user
                    documento.status = 'aguardando_analise'
                    documento.save()  # O método save do modelo já chama gerar_pdf se necessário
                    messages.success(request, 'Documento criado e enviado para análise.')
                    return redirect('documentos:listar_documentos_aprovados')
            except IntegrityError as e:
                logger.error(f"Erro de integridade ao criar documento: {e}")
                messages.error(request, 'Erro ao criar o documento.')
            except ValidationError as e:
                logger.error(f"Erro de validação ao criar documento: {e}")
                messages.error(request, e.messages)
            except Exception as e:
                logger.error(f"Erro inesperado ao criar documento: {e}", exc_info=True)
                messages.error(request, 'Erro inesperado ao criar o documento.')
    else:
        form = DocumentoForm()
    return render(request, 'documentos/criar_documento.html', {'form': form})

# Função para análise de documentos
@login_required
@permission_required('documentos.can_analyze', raise_exception=True)
def listar_documentos_para_analise(request):
    """
    Lista documentos em status 'aguardando_analise'.
    Permite:
    - Upload de arquivo revisado (action='upload')
    - Aprovar a análise sem upload (action='aprovar_analise') -> muda status p/ 'aguardando_elaborador'
    - Fazer upload manual de PDF para planilhas (action='upload_pdf_spreadsheet')
    - Fazer upload manual de PDF para documentos do tipo PDF (action='upload_pdf_manual')
    - Reprovar o documento (action='reprovar')
    """
    documentos = Documento.objects.filter(status='aguardando_analise')

    if request.method == 'POST':
        documento_id = request.POST.get('documento_id')
        action = request.POST.get('action')
        documento = get_object_or_404(Documento, id=documento_id, status='aguardando_analise')

        # (1) Upload de arquivo revisado (.doc, .docx, .odt, .xls, .xlsx, .ods)
        if action == 'upload':
            form = AnaliseDocumentoForm(request.POST, request.FILES, instance=documento)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        documento = form.save(commit=False)
                        documento.analista = request.user
                        documento.data_analise = timezone.now()
                        documento.save()
                        messages.success(
                            request,
                            f'Documento "{documento.nome}" revisado carregado com sucesso! '
                            'O documento continua aguardando análise.'
                        )
                        return redirect('documentos:listar_documentos_para_analise')
                except Exception as e:
                    logger.error(f"Erro ao fazer upload revisado do documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao fazer upload do documento revisado.')
            else:
                messages.error(request, 'Erro ao fazer upload do documento revisado.')

        # (2) Aprovar a análise sem upload – muda status para 'aguardando_elaborador'
        elif action == 'aprovar_analise':
            try:
                with transaction.atomic():
                    documento.analista = request.user
                    documento.data_analise = timezone.now()
                    documento.status = 'aguardando_elaborador'
                    documento.save()
                    # Chama a conversão para PDF (se não houver PDF manual, conforme o gerar_pdf() modificado)
                    documento.gerar_pdf()
                    messages.success(
                        request,
                        f'Documento "{documento.nome}" aprovado na análise e aguardando aprovação do elaborador.'
                    )
                    return redirect('documentos:listar_documentos_para_analise')
            except Exception as e:
                logger.error(f"Erro ao aprovar análise do documento {documento_id}: {e}", exc_info=True)
                messages.error(request, 'Erro ao aprovar a análise do documento.')

        # (3) Upload manual de PDF para planilhas
        elif action == 'upload_pdf_spreadsheet':
            pdf_file = request.FILES.get('pdf_upload')
            if pdf_file:
                ext = os.path.splitext(pdf_file.name)[1].lower()
                if ext == '.pdf':
                    try:
                        with transaction.atomic():
                            if documento.documento_pdf and documento.documento_pdf.storage.exists(documento.documento_pdf.name):
                                documento.documento_pdf.delete(save=False)
                            safe_nome = slugify(documento.nome)
                            desired_pdf_filename = f"{safe_nome}_v{documento.revisao}.pdf"
                            documento.documento_pdf.save(desired_pdf_filename, pdf_file)
                            documento.document_type = 'pdf_spreadsheet'
                            documento.analista = request.user
                            documento.data_analise = timezone.now()
                            documento.save()
                            messages.success(
                                request,
                                f'PDF da planilha "{documento.nome}" enviado com sucesso! '
                                'O documento continua aguardando análise.'
                            )
                            return redirect('documentos:listar_documentos_para_analise')
                    except Exception as e:
                        logger.error(f"Erro ao fazer upload do PDF da planilha {documento_id}: {e}", exc_info=True)
                        messages.error(request, 'Erro ao fazer upload do PDF da planilha.')
                else:
                    messages.error(request, 'Formato inválido. Envie um arquivo PDF.')
            else:
                messages.error(request, 'Nenhum arquivo PDF enviado.')

        # (4) Upload manual de PDF para documentos do tipo PDF
        elif action == 'upload_pdf_manual':
            pdf_file = request.FILES.get('pdf_upload')
            if pdf_file:
                ext = os.path.splitext(pdf_file.name)[1].lower()
                if ext == '.pdf':
                    try:
                        with transaction.atomic():
                            if documento.documento_pdf and documento.documento_pdf.storage.exists(documento.documento_pdf.name):
                                documento.documento_pdf.delete(save=False)
                            safe_nome = slugify(documento.nome)
                            desired_pdf_filename = f"{safe_nome}_v{documento.revisao}.pdf"
                            documento.documento_pdf.save(desired_pdf_filename, pdf_file)
                            # Caso seja PDF manual, mantenha o tipo "pdf" para evitar geração automática
                            documento.document_type = 'pdf'
                            documento.analista = request.user
                            documento.data_analise = timezone.now()
                            documento.save()
                            messages.success(
                                request,
                                f'PDF manual para "{documento.nome}" enviado com sucesso! Geração automática ignorada.'
                            )
                            return redirect('documentos:listar_documentos_para_analise')
                    except Exception as e:
                        logger.error(f"Erro ao fazer upload manual do PDF do documento {documento_id}: {e}", exc_info=True)
                        messages.error(request, 'Erro ao fazer upload manual do PDF.')
                else:
                    messages.error(request, 'Formato inválido. Envie um arquivo PDF.')
            else:
                messages.error(request, 'Nenhum arquivo PDF enviado.')

        # (5) Reprovar o documento (solicita motivo de reprovação)
        elif action == 'reprovar':
            motivo = request.POST.get('motivo_reprovacao')
            if motivo:
                try:
                    with transaction.atomic():
                        documento.status = 'reprovado'
                        documento.motivo_reprovacao = motivo
                        documento.analista = request.user
                        documento.save()
                        messages.success(request, f'Documento "{documento.nome}" reprovado com sucesso!')
                except Exception as e:
                    logger.error(f"Erro ao reprovar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao reprovar o documento.')
            else:
                messages.error(request, 'É necessário informar o motivo da reprovação.')

    return render(request, 'documentos/listar_documentos_para_analise.html', {
        'documentos': documentos,
        'titulo': 'Documentos para Análise'
    })

# Função para substituir documento
@login_required
def substituir_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if request.method == 'POST' and request.FILES.get('novo_documento'):
        novo_documento = request.FILES['novo_documento']
        if documento.documento:
            if os.path.isfile(documento.documento.path):
                os.remove(documento.documento.path)
        documento.documento = novo_documento
        documento.status = 'aguardando_analise'
        documento.save()
        messages.success(request, 'Documento substituído com sucesso.')
        return redirect('documentos:listar_documentos_para_analise')
    messages.error(request, 'Erro ao substituir o documento.')
    return redirect('documentos:listar_documentos_para_analise')

# Função para atualizar documento
@login_required
def atualizar_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if request.method == 'POST':
        novo_arquivo = request.FILES.get('documento')
        novo_status = request.POST.get('status')
        if novo_arquivo and novo_status == 'analise_concluida':
            documento.documento = novo_arquivo
            documento.status = novo_status
            documento.save()
            messages.success(request, 'Documento atualizado com sucesso e enviado para aprovação do elaborador.')
        else:
            messages.error(request, 'Falha ao atualizar o documento.')
    return redirect('documentos:listar_documentos_para_analise')

# Função para aprovar documento (fluxo único, se necessário)
@login_required
def aprovar_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if documento.status != 'aguardando_analise':
        messages.error(request, "Este documento não está em estado de análise.")
        return redirect('documentos:listar_documentos_para_analise')
    try:
        with transaction.atomic():
            documento = Documento.objects.select_for_update().get(id=documento_id)
            documento.status = 'aguardando_elaborador'
            documento.aprovado_por_aprovador1 = True
            documento.gerar_pdf()
            documento.save()
            messages.success(request, "Documento aprovado e processado com sucesso.")
    except Documento.DoesNotExist:
        messages.error(request, "Documento não encontrado.")
    except Exception as e:
        logger.error(f"Erro ao aprovar documento {documento_id}: {e}")
        messages.error(request, "Ocorreu um erro ao aprovar o documento.")
    return redirect('documentos:listar_documentos_para_analise')

# Função para listar aprovações pendentes
@login_required
@permission_required('documentos.list_pending_approvals', raise_exception=True)
def listar_aprovacoes_pendentes(request):
    user = request.user
    documentos = Documento.objects.none()
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
                        documento.status = 'aguardando_aprovador1'
                        documento.data_aprovado_elaborador = timezone.now()
                        documento.save()
                        messages.success(request, 'Documento aprovado e enviado para o Aprovador.')
                except Exception as e:
                    logger.error(f"Erro ao aprovar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao aprovar o documento.')
            elif documento.status == 'aguardando_aprovador1' and user == documento.aprovador1:
                try:
                    with transaction.atomic():
                        documento.aprovado_por_aprovador1 = True
                        documento.status = 'aprovado'
                        documento.data_aprovado_aprovador = timezone.now()
                        documento.save()
                        documento.gerar_pdf()
                        messages.success(request, 'Documento aprovado com sucesso!')
                except ValidationError as ve:
                    logger.error(f"Erro de validação ao aprovar documento {documento_id}: {ve}", exc_info=True)
                    messages.error(request, f'Erro de validação: {ve.messages}')
                except Exception as e:
                    logger.error(f"Erro ao aprovar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao aprovar o documento.')
            else:
                messages.error(request, 'Você não tem permissão para aprovar este documento.')
        elif action == 'reprovar':
            motivo = request.POST.get('motivo_reprovacao')
            if motivo:
                try:
                    with transaction.atomic():
                        documento.status = 'reprovado'
                        documento.motivo_reprovacao = motivo
                        documento.save()
                        messages.success(request, 'Documento reprovado com sucesso!')
                except Exception as e:
                    logger.error(f"Erro ao reprovar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao reprovar o documento.')
            else:
                messages.error(request, 'É necessário informar o motivo da reprovação.')
        else:
            messages.error(request, 'Ação inválida.')
    return render(request, 'documentos/listar_aprovacoes_pendentes.html', {
        'documentos': documentos,
        'titulo': 'Aprovações Pendentes'
    })

# Função para listar documentos aprovados
@login_required
@permission_required('documentos.view_documentos', raise_exception=True)
def listar_documentos_aprovados(request):
    documentos = Documento.objects.filter(status='aprovado', is_active=True)\
        .select_related('categoria')\
        .order_by('categoria__nome', 'nome', '-revisao')
    documentos_unicos = {}
    for doc in documentos:
        chave_unica = (doc.nome, doc.categoria.id)
        if chave_unica not in documentos_unicos:
            documentos_unicos[chave_unica] = doc
    documentos = list(documentos_unicos.values())
    documentos.sort(key=lambda x: (x.categoria.nome, x.nome))
    return render(request, 'documentos/listar_documentos.html', {
        'documentos': documentos,
        'titulo': 'Documentos Aprovados'
    })

# View para inativar ou ativar um documento
@login_required
@permission_required('documentos.can_active', raise_exception=True)
def toggle_documento_active_status(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if request.method == 'POST':
        documento.is_active = not documento.is_active
        documento.save()
        status = 'ativo' if documento.is_active else 'inativo'
        messages.success(request, f'Documento "{documento.nome}" foi marcado como {status}.')
    else:
        messages.error(request, 'Método de requisição inválido.')
    return redirect('documentos:listar_documentos_aprovados')

# View para listar documentos aprovados e inativos
@login_required
@permission_required('documentos.view_documentos_ina', raise_exception=True)
def listar_documentos_inativos(request):
    documentos_inativos = Documento.objects.filter(status='aprovado', is_active=False).order_by('nome', '-revisao')
    documentos_unicos = {}
    for doc in documentos_inativos:
        if doc.nome not in documentos_unicos:
            documentos_unicos[doc.nome] = doc
    documentos_inativos = list(documentos_unicos.values())
    documentos_inativos.sort(key=lambda x: x.nome)
    return render(request, 'documentos/listar_documentos_inativos.html', {'documentos': documentos_inativos, 'titulo': 'Documentos Inativos'})

# Função para visualizar documento
@login_required
@xframe_options_sameorigin
def visualizar_documento(request, id):
    documento = get_object_or_404(Documento, id=id)
    if request.user.is_authenticated:
        Acesso.objects.create(documento=documento, usuario=request.user)
    if documento.documento_pdf:
        pdf_url = request.build_absolute_uri(reverse('documentos:visualizar_pdf', args=[documento.id]))
    else:
        pdf_url = None
    response = render(request, 'documentos/visualizar_documento.html', {
        'documento': documento,
        'pdf_url': pdf_url
    })
    response['Cross-Origin-Opener-Policy'] = 'same-origin'
    response['Cross-Origin-Embedder-Policy'] = 'require-corp'
    return response

# Função para visualizar PDF
@login_required
def visualizar_pdf(request, id):
    documento = get_object_or_404(Documento, id=id)
    if not documento.documento_pdf:
        raise Http404("Documento PDF não encontrado.")
    try:
        return FileResponse(open(documento.documento_pdf.path, 'rb'), content_type='application/pdf')
    except IOError:
        raise Http404("Erro ao abrir o arquivo PDF.")

# Função para baixar PDF
@login_required
def baixar_pdf(request, id):
    documento = get_object_or_404(Documento, id=id)
    if documento.categoria.bloqueada:
        messages.error(request, "Você não tem permissão para baixar este documento.")
        return redirect('documentos:visualizar_documento', id=id)
    if not documento.documento_pdf:
        raise Http404("Documento PDF não encontrado.")
    file_path = documento.documento_pdf.path
    response = FileResponse(open(file_path, 'rb'), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(os.path.basename(file_path))
    return response

# Função para visualizar acessos
@login_required
@permission_required('documentos.view_acessos_documento', raise_exception=True)
def visualizar_acessos_documento(request, id):
    documento = get_object_or_404(Documento, id=id)
    acessos = Acesso.objects.filter(documento=documento).select_related('usuario').order_by('-data_acesso')
    total_acessos = acessos.count()
    return render(request, 'documentos/visualizar_acessos.html', {'documento': documento, 'acessos': acessos, 'total_acessos': total_acessos})

# Função para listar documentos reprovados
@login_required
@permission_required('documentos.list_reproaches', raise_exception=True)
def listar_documentos_reprovados(request):
    documentos_reprovados = Documento.objects.filter(elaborador=request.user, status='reprovado')
    return render(request, 'documentos/lista_reprovados.html', {'documentos': documentos_reprovados, 'titulo': 'Documentos Reprovados'})

# Função para nova revisão
@login_required
@permission_required('documentos.can_add_documento', raise_exception=True)
def nova_revisao(request, documento_id):
    documento_atual = get_object_or_404(Documento, id=documento_id)
    revisoes_pendentes = Documento.objects.filter(
        nome=documento_atual.nome,
        status__in=['aguardando_analise', 'analise_concluida', 'aguardando_aprovador1', 'aguardando_elaborador']
    ).exclude(id=documento_atual.id)
    if revisoes_pendentes.exists():
        revisao_pendente = revisoes_pendentes.first()
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
                    nova_revisao.nome = documento_atual.nome
                    nova_revisao.categoria = documento_atual.categoria
                    nova_revisao.elaborador = request.user
                    nova_revisao.status = 'aguardando_analise'
                    nova_revisao.save()
                    messages.success(request, 'Nova revisão criada com sucesso!')
                    return redirect('documentos:listar_documentos_aprovados')
            except Exception as e:
                logger.error(f'Erro ao criar nova revisão: {e}', exc_info=True)
                messages.error(request, f'Ocorreu um erro ao criar a nova revisão: {e}')
        else:
            messages.error(request, 'Por favor, corrija os erros no formulário.')
    else:
        form = NovaRevisaoForm(documento_atual=documento_atual)
    return render(request, 'documentos/nova_revisao.html', {'form': form, 'documento': documento_atual})

# Função para upload de documento revisado
@login_required
def upload_documento_revisado(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    logger.debug(f"[upload_documento_revisado] Iniciando upload revisado para documento ID: {documento_id}")
    if request.method == 'POST' and request.FILES.get('documento'):
        novo_documento = request.FILES['documento']
        logger.debug(f"[upload_documento_revisado] Arquivo recebido: {novo_documento.name}")
        ext = os.path.splitext(novo_documento.name)[1].lower()
        if ext not in ['.doc', '.docx', '.odt', '.xls', '.xlsx', '.ods']:
            messages.error(request, 'Formato de arquivo inválido. Apenas arquivos .doc, .docx, .odt, .xls, .xlsx e .ods são permitidos.')
            logger.warning(f"[upload_documento_revisado] Formato de arquivo inválido: {novo_documento.name}")
            return redirect('documentos:listar_documentos_para_analise')
        try:
            with transaction.atomic():
                if documento.documento:
                    documento.documento.delete(save=False)
                    logger.debug(f"[upload_documento_revisado] Documento editável antigo removido: {documento.documento.name}")
                documento.documento.save(novo_documento.name, novo_documento)
                logger.debug(f"[upload_documento_revisado] Novo documento revisado salvo: {documento.documento.name}")
                documento.status = 'aguardando_analise'
                documento.save()
                logger.debug(f"[upload_documento_revisado] Status atualizado para: {documento.status}")
                messages.success(request, 'Documento revisado carregado com sucesso. Ele será analisado antes de ser aprovado.')
        except Exception as e:
            logger.error(f'[upload_documento_revisado] Erro ao carregar o documento revisado: {e}', exc_info=True)
            messages.error(request, f'Ocorreu um erro ao carregar o documento revisado: {e}')
    else:
        messages.error(request, 'Nenhum arquivo foi enviado para substituição.')
        logger.warning(f"[upload_documento_revisado] Nenhum arquivo enviado para documento ID: {documento_id}")
    return redirect('documentos:listar_documentos_para_analise')

# Função para listar documentos editáveis
@login_required
@permission_required('documentos.can_view_editables', raise_exception=True)
def listar_documentos_editaveis(request):
    categorias = Categoria.objects.all()
    documentos_por_categoria = {}
    for categoria in categorias:
        documentos = Documento.objects.filter(
            categoria=categoria,
            status='aprovado',
            is_active=True
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
        'categorias': categorias,
        'titulo': 'Documentos Editáveis',
    })

# Função para listar revisões do documento
@login_required
@permission_required('documentos.can_view_revisions', raise_exception=True)
def listar_revisoes_documento(request, documento_id):
    documento_atual = get_object_or_404(Documento, id=documento_id)
    revisoes_aprovadas = Documento.objects.filter(
        nome=documento_atual.nome,
        status='aprovado'
    ).order_by('-revisao')
    return render(request, 'documentos/listar_revisoes_documento.html', {
        'documento_atual': documento_atual,
        'revisoes': revisoes_aprovadas,
        'titulo': f'Revisões Aprovadas de {documento_atual.nome}',
    })

# Função para monitorar documentos pendentes de aprovação
@login_required
@permission_required('documentos.monitor_documents', raise_exception=True)
def monitorar_documentos_pendentes(request):
    filter_status = request.GET.get('status', 'pendentes')
    
    if filter_status == 'aprovado':
        documentos = Documento.objects.filter(status='aprovado').select_related(
            'categoria', 'elaborador', 'aprovador1', 'analista'
        )
        pendentes_por_status = {'Aprovado': documentos}
        total = documentos.count()
    elif filter_status in ['aguardando_analise', 'analise_concluida', 'aguardando_elaborador', 'aguardando_aprovador1']:
        documentos = Documento.objects.filter(status=filter_status).select_related(
            'categoria', 'elaborador', 'aprovador1', 'analista'
        )
        pendentes_por_status = {filter_status.replace('_', ' ').title(): documentos}
        total = documentos.count()
    else:
        documentos = Documento.objects.filter(
            status__in=[
                'aguardando_analise',
                'analise_concluida',
                'aguardando_elaborador',
                'aguardando_aprovador1'
            ]
        ).select_related('categoria', 'elaborador', 'aprovador1', 'analista')
        pendentes_por_status = {
            'Aguardando Análise SGQ': documentos.filter(status='aguardando_analise'),
            'Análise Concluída': documentos.filter(status='analise_concluida'),
            'Aguardando Aprovação do Elaborador': documentos.filter(status='aguardando_elaborador'),
            'Aguardando Aprovação do Aprovador': documentos.filter(status='aguardando_aprovador1'),
        }
        total = documentos.count()

    contexto = {
        'pendentes_por_status': pendentes_por_status,
        'total_pendentes': total,
        'titulo': 'Monitoramento de Documentos Pendentes'
    }
    return render(request, 'documentos/monitorar_pendentes.html', contexto)

@login_required
@permission_required('documentos.delete_documento', raise_exception=True)
def deletar_documento(request, documento_id):
    """
    Deleta o documento (revisão atual) e registra a deleção no banco.
    """
    documento = get_object_or_404(Documento, id=documento_id)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                DocumentoDeletado.objects.create(
                    usuario=request.user,
                    documento_nome=documento.nome,
                    revisao=documento.revisao,
                    data_hora=timezone.now()
                )

                if documento.documento and os.path.isfile(documento.documento.path):
                    os.remove(documento.documento.path)
                if documento.documento_pdf and os.path.isfile(documento.documento_pdf.path):
                    os.remove(documento.documento_pdf.path)

                documento.delete()
                messages.success(request, "Revisão atual deletada com sucesso!")
        except Exception as e:
            logger.error(f"Erro ao deletar o documento ID {documento_id}: {e}", exc_info=True)
            messages.error(request, f"Erro ao deletar o documento: {e}")
        return redirect('documentos:listar_documentos_aprovados')

    messages.error(request, "A deleção deve ser feita via POST.")
    return redirect('documentos:listar_documentos_aprovados')

@login_required
def visualizar_documento_pdfjs(request, id):
    documento = get_object_or_404(Documento, id=id)

    # Registra o acesso, semelhante ao que acontece em visualizar_documento
    if request.user.is_authenticated:
        Acesso.objects.create(documento=documento, usuario=request.user)
        logger.debug(f"Acesso registrado via PDF.js para o usuário {request.user.username} no documento {documento.nome}")

    if documento.categoria.bloqueada:
        messages.info(request, "Este documento é bloqueado para download e impressão, mas pode ser visualizado.")

    pdfjs_viewer_url = request.build_absolute_uri('/static/pdfjs/web/viewer.html')
    pdf_file_url = request.build_absolute_uri(reverse('documentos:visualizar_pdf', args=[documento.id]))

    return render(request, 'documentos/visualizar_documento_pdfjs.html', {
        'documento': documento,
        'pdfjs_viewer_url': pdfjs_viewer_url,
        'pdf_file_url': pdf_file_url
    })



@login_required
@permission_required('documentos.replace_document', raise_exception=True)
def substituir_pdf(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if request.method == 'POST' and request.FILES.get('novo_pdf'):
        novo_pdf = request.FILES['novo_pdf']
        ext = os.path.splitext(novo_pdf.name)[1].lower()
        if ext != '.pdf':
            messages.error(request, 'Formato inválido. Envie um arquivo PDF.')
            return redirect('documentos:substituir_pdf', documento_id=documento_id)

        try:
            with transaction.atomic():
                # Se já houver um PDF, exclua-o
                if documento.documento_pdf and documento.documento_pdf.storage.exists(documento.documento_pdf.name):
                    os.remove(documento.documento_pdf.path)
                    documento.documento_pdf.delete(save=False)
                safe_nome = slugify(documento.nome)
                desired_pdf_filename = f"{safe_nome}_v{documento.revisao}.pdf"
                documento.documento_pdf.save(desired_pdf_filename, novo_pdf)
                
                # Se o documento não estiver aprovado, pode ajustar o status, 
                # mas se já estiver 'aprovado' podemos manter o status.
                if documento.status != 'aprovado':
                    documento.status = 'aguardando_analise'
                
                documento.save()
                messages.success(request, 'PDF substituído com sucesso.')
        except Exception as e:
            logger.error(f"Erro ao substituir PDF do documento {documento_id}: {e}", exc_info=True)
            messages.error(request, 'Erro ao substituir o PDF.')
        return redirect('documentos:listar_documentos_aprovados')
    
    return render(request, 'documentos/substituir_pdf.html', {'documento': documento})