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
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils.text import slugify




logger = logging.getLogger('django')
User = get_user_model()

#Função para listar as categorias
@login_required
@permission_required('documentos.view_categoria', raise_exception=True)
def listar_categorias(request):
    categorias = Categoria.objects.all()
    return render(request, 'documentos/listar_categorias.html', {'categorias': categorias})

#Função para criar categoria
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

#Função para editar categoria
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

#Função para criar documentos
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
                    documento.status = 'aguardando_analise'  # Define o status inicial
                    documento.save()  # O método save do modelo já chama gerar_pdf
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


#Função para analise de documentos
@login_required
@permission_required('documentos.can_analyze', raise_exception=True)
def listar_documentos_para_analise(request):
    documentos = Documento.objects.filter(status='aguardando_analise')
    if request.method == 'POST':
        documento_id = request.POST.get('documento_id')
        action = request.POST.get('action')
        documento = get_object_or_404(Documento, id=documento_id, status='aguardando_analise')

        if action == 'upload':
            # Upload do documento revisado original
            form = AnaliseDocumentoForm(request.POST, request.FILES, instance=documento)
            if form.is_valid():
                try:
                    with transaction.atomic():
                        documento = form.save(commit=False)
                        # Depois do upload do documento revisado, marcamos como analise_concluida
                        # para seguir o fluxo normal
                        documento.status = 'analise_concluida'
                        documento.analista = request.user
                        documento.save()
                        messages.success(request, f'Documento "{documento.nome}" analisado com sucesso!')
                        return redirect('documentos:listar_documentos_para_analise')
                except Exception as e:
                    logger.error(f"Erro ao analisar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao fazer upload do documento revisado.')
            else:
                messages.error(request, 'Erro ao fazer upload do documento revisado.')

        elif action == 'upload_pdf_spreadsheet':
            # Upload manual do PDF para um documento do tipo planilha
            pdf_file = request.FILES.get('pdf_upload')
            logger.debug(f"Upload de PDF manual para planilha, documento ID: {documento_id}")
            if pdf_file:
                ext = os.path.splitext(pdf_file.name)[1].lower()
                if ext == '.pdf':
                    try:
                        with transaction.atomic():
                            # Deleta o PDF antigo se houver
                            if documento.documento_pdf and documento.documento_pdf.storage.exists(documento.documento_pdf.name):
                                documento.documento_pdf.delete(save=False)

                            safe_nome = slugify(documento.nome)
                            desired_pdf_filename = f"{safe_nome}_v{documento.revisao}.pdf"

                            # Salva o novo PDF no mesmo diretório definido em pdf_upload_path
                            documento.documento_pdf.save(desired_pdf_filename, pdf_file)

                            documento.document_type = 'pdf_spreadsheet'
                            # Mantém o documento no status 'aguardando_analise' após o upload do PDF
                            documento.status = 'aguardando_analise'
                            documento.analista = request.user
                            documento.save()
                            messages.success(request, f'PDF da planilha "{documento.nome}" enviado com sucesso! O documento continua aguardando análise.')
                            return redirect('documentos:listar_documentos_para_analise')
                    except Exception as e:
                        logger.error(f"Erro ao fazer upload do PDF da planilha {documento_id}: {e}", exc_info=True)
                        messages.error(request, 'Erro ao fazer upload do PDF da planilha.')
                else:
                    messages.error(request, 'Formato inválido. Envie um arquivo PDF.')
            else:
                messages.error(request, 'Nenhum arquivo PDF enviado.')

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

    return render(request, 'documentos/listar_documentos_para_analise.html', {'documentos': documentos, 'titulo': 'Documentos para Análise'})


@login_required
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

# Função para aprovar documentos
@login_required
def aprovar_documento(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    if documento.status != 'aguardando_analise':
        messages.error(request, "Este documento não está em estado de análise.")
        return redirect('documentos:listar_documentos_para_analise')

    try:
        with transaction.atomic():
            # Bloquear o documento para evitar condições de corrida
            documento = Documento.objects.select_for_update().get(id=documento_id)
            documento.status = 'aguardando_elaborador'  # Altera o status para aguardar aprovação do elaborador
            documento.aprovado_por_aprovador1 = True  # Atualiza o campo de aprovação
            documento.gerar_pdf()  # Gera o PDF ou copia a planilha conforme o tipo
            documento.save()
            messages.success(request, "Documento aprovado e processado com sucesso.")
            # As notificações serão enviadas pelo sinal após salvar o documento
    except Documento.DoesNotExist:
        messages.error(request, "Documento não encontrado.")
    except Exception as e:
        logger.error(f"Erro ao aprovar documento {documento_id}: {e}")
        messages.error(request, "Ocorreu um erro ao aprovar o documento.")
    
    return redirect('documentos:listar_documentos_para_analise')


@login_required
@permission_required('documentos.list_pending_approvals', raise_exception=True)
def listar_aprovacoes_pendentes(request):
    """
    View para listar os documentos pendentes de aprovação pelo elaborador ou pelo aprovador,
    permitindo que eles aprovem ou reprovem os documentos.
    """
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
                # Elaborador aprova o documento e envia para o aprovador
                try:
                    with transaction.atomic():
                        documento.status = 'aguardando_aprovador1'  # Alteração de status para aguardar o aprovador
                        documento.save()
                        messages.success(request, 'Documento aprovado e enviado para o Aprovador.')
                        # Notificações podem ser enviadas aqui, se necessário
                except Exception as e:
                    logger.error(f"Erro ao aprovar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao aprovar o documento.')
            elif documento.status == 'aguardando_aprovador1' and user == documento.aprovador1:
                # Aprovador final aprova o documento
                try:
                    with transaction.atomic():
                        documento.aprovado_por_aprovador1 = True
                        documento.status = 'aprovado'  # Alteração de status para aprovado
                        documento.save()
                        documento.gerar_pdf()  # Chama gerar_pdf após salvar o documento aprovado
                        messages.success(request, 'Documento aprovado com sucesso!')
                        # Notificações podem ser enviadas aqui, se necessário
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
                        documento.status = 'reprovado'  # Alteração de status para reprovado
                        documento.motivo_reprovacao = motivo  # Registro do motivo da reprovação
                        documento.save()
                        messages.success(request, 'Documento reprovado com sucesso!')
                        # Notificações podem ser enviadas aqui, se necessário
                except Exception as e:
                    logger.error(f"Erro ao reprovar documento {documento_id}: {e}", exc_info=True)
                    messages.error(request, 'Erro ao reprovar o documento.')
            else:
                messages.error(request, 'É necessário informar o motivo da reprovação.')
        else:
            messages.error(request, 'Ação inválida.')
    else:
        # Se não for uma requisição POST, renderiza a lista de documentos pendentes
        pass  # Nenhuma ação adicional necessária

    return render(request, 'documentos/listar_aprovacoes_pendentes.html', {
        'documentos': documentos,
        'titulo': 'Aprovações Pendentes'
    })

#Função para listar os documentos aprovados
@login_required
@permission_required('documentos.view_documentos', raise_exception=True)
def listar_documentos_aprovados(request):
    # Ordena os documentos primeiro pela categoria, depois pelo nome e revisão
    documentos = Documento.objects.filter(status='aprovado', is_active=True)\
        .select_related('categoria')\
        .order_by('categoria__nome', 'nome', '-revisao')
    
    # Remove documentos duplicados baseados no nome e categoria, mantendo a ordem
    documentos_unicos = {}
    for doc in documentos:
        chave_unica = (doc.nome, doc.categoria.id)
        if chave_unica not in documentos_unicos:
            documentos_unicos[chave_unica] = doc
    
    # Converte para lista mantendo a ordem
    documentos = list(documentos_unicos.values())
    
    # Reordena a lista de documentos para garantir que estão agrupados por categoria
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



#Função para vizualizar documentos
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

#Função para visualizar acessos
@login_required
@permission_required('documentos.view_acessos_documento', raise_exception=True)
def visualizar_acessos_documento(request, id):
    documento = get_object_or_404(Documento, id=id)
    acessos = Acesso.objects.filter(documento=documento).select_related('usuario').order_by('-data_acesso')
    total_acessos = acessos.count()
    return render(request, 'documentos/visualizar_acessos.html', {'documento': documento, 'acessos': acessos, 'total_acessos': total_acessos})

#Função lista de reprovações
@login_required
@permission_required('documentos.list_reproaches', raise_exception=True)
def listar_documentos_reprovados(request):
    documentos_reprovados = Documento.objects.filter(elaborador=request.user, status='reprovado')
    return render(request, 'documentos/lista_reprovados.html', {'documentos': documentos_reprovados, 'titulo': 'Documentos Reprovados'})

#Função nova revisão
@login_required
@permission_required('documentos.can_add_documento', raise_exception=True)
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
                    nova_revisao.status = 'aguardando_analise'  # Define status para iniciar o fluxo
                    nova_revisao.save()
                    messages.success(request, 'Nova revisão criada com sucesso!')
                    return redirect('documentos:listar_documentos_aprovados')  # Atualizado para a lista de documentos
            except Exception as e:
                logger.error(f'Erro ao criar nova revisão: {e}', exc_info=True)
                messages.error(request, f'Ocorreu um erro ao criar a nova revisão: {e}')
        else:
            messages.error(request, 'Por favor, corrija os erros no formulário.')
    else:
        form = NovaRevisaoForm(documento_atual=documento_atual)
    return render(request, 'documentos/nova_revisao.html', {'form': form, 'documento': documento_atual})


@login_required
def upload_documento_revisado(request, documento_id):
    documento = get_object_or_404(Documento, id=documento_id)
    logger.debug(f"[upload_documento_revisado] Iniciando upload revisado para documento ID: {documento_id}")

    if request.method == 'POST' and request.FILES.get('documento'):
        novo_documento = request.FILES['documento']
        logger.debug(f"[upload_documento_revisado] Arquivo recebido: {novo_documento.name}")

        # Verificar extensão do arquivo
        ext = os.path.splitext(novo_documento.name)[1].lower()
        if ext not in ['.doc', '.docx', '.odt', '.xls', '.xlsx', '.ods']:
            messages.error(request, 'Formato de arquivo inválido. Apenas arquivos .doc, .docx, .odt, .xls, .xlsx e .ods são permitidos.')
            logger.warning(f"[upload_documento_revisado] Formato de arquivo inválido: {novo_documento.name}")
            return redirect('documentos:listar_documentos_para_analise')

        try:
            with transaction.atomic():
                # Remover o documento editável antigo, se existir
                if documento.documento:
                    documento.documento.delete(save=False)
                    logger.debug(f"[upload_documento_revisado] Documento editável antigo removido: {documento.documento.name}")
                
                # Salvar o novo documento revisado
                documento.documento.save(novo_documento.name, novo_documento)
                logger.debug(f"[upload_documento_revisado] Novo documento revisado salvo: {documento.documento.name}")
                
                # Atualizar o status para aguardar nova análise
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


#Função para listar os editaveis
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
        'categorias': categorias,  # Certifique-se de passar as categorias
        'titulo': 'Documentos Editáveis',
    })

#Função lista de revisões
@login_required
@permission_required('documentos.can_view_revisions', raise_exception=True)
def listar_revisoes_documento(request, documento_id):
    """
    Lista todas as revisões aprovadas de um documento específico.
    """
    documento_atual = get_object_or_404(Documento, id=documento_id)
    # Filtrar apenas revisões aprovadas
    revisoes_aprovadas = Documento.objects.filter(
        nome=documento_atual.nome,
        status='aprovado'  # Filtra apenas revisões aprovadas
    ).order_by('-revisao')

    return render(request, 'documentos/listar_revisoes_documento.html', {
        'documento_atual': documento_atual,
        'revisoes': revisoes_aprovadas,
        'titulo': f'Revisões Aprovadas de {documento_atual.nome}',
    })