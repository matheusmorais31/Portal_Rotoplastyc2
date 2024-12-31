# models.py

from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from pathlib import Path
from django.conf import settings
import logging
import subprocess
import tempfile
import os
import shutil

logger = logging.getLogger('django')

User = get_user_model()

# Classe de Armazenamento Personalizada para Sobrescrever Arquivos Existentes
class OverwriteStorage(FileSystemStorage):
    """
    Classe de armazenamento personalizada que sobrescreve arquivos existentes com o mesmo nome.
    """
    def get_available_name(self, name, max_length=None):
        """
        Retorna um nome de arquivo disponível para novo conteúdo, excluindo o arquivo existente, se necessário.
        """
        if self.exists(name):
            try:
                self.delete(name)
                logger.debug(f"[OverwriteStorage] Arquivo existente removido: {name}")
            except Exception as e:
                logger.error(f"[OverwriteStorage] Falha ao remover o arquivo existente {name}: {e}")
        return name

# Definir um armazenamento protegido que salva em media/
protected_storage = FileSystemStorage(
    location=os.path.join(settings.MEDIA_ROOT),  # Ajustado para salvar em media/
    base_url=None  # Define base_url como None para impedir acesso direto via URL
)

# Funções de Caminho de Upload Utilizando pathlib.Path
def documento_upload_path(instance, filename):
    """
    Define o caminho de upload para documentos editáveis.
    """
    return Path('documentos') / 'editaveis' / filename

def pdf_upload_path(instance, filename):
    """
    Define o caminho de upload para PDFs.
    """
    return Path('documentos') / 'pdf' / filename

def spreadsheet_upload_path(instance, filename):
    """
    Define o caminho de upload para planilhas.
    """
    return Path('documentos') / 'spreadsheet' / filename

# Modelo Categoria
class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    bloqueada = models.BooleanField(
        default=False,
        help_text='Marque se esta categoria deve bloquear download e impressão dos documentos.'
    )

    def __str__(self):
        return self.nome

# Modelo Documento
class Documento(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('pdf', 'PDF'),
        ('spreadsheet', 'Planilha'),
        ('pdf_spreadsheet', 'PDF da Planilha' )
    ]

    STATUS_CHOICES = [
        ('aguardando_analise', 'Aguardando Análise'),
        ('analise_concluida', 'Análise Concluída'),
        ('aguardando_elaborador', 'Aguardando Aprovação do Elaborador'),
        ('aguardando_aprovador1', 'Aguardando Aprovação do Aprovador'),
        ('aprovado', 'Aprovado'),
        ('reprovado', 'Reprovado'),
    ]

    nome = models.CharField(max_length=200)
    revisao = models.IntegerField(choices=[(i, f"{i:02d}") for i in range(0, 101)])
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    aprovador1 = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='aprovador1_documentos'
    )
    documento = models.FileField(upload_to=documento_upload_path)
    documento_pdf = models.FileField(
        upload_to=pdf_upload_path,  # Será atualizado dinamicamente no método gerar_pdf
        storage=protected_storage,  # Usa armazenamento protegido em media/
        editable=False,
        null=True,
        blank=True
    )
    data_criacao = models.DateTimeField(auto_now_add=True)
    aprovado_por_aprovador1 = models.BooleanField(default=False)
    reprovado = models.BooleanField(default=False)
    motivo_reprovacao = models.TextField(null=True, blank=True)
    elaborador = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='documentos_criados'
    )
    solicitante = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        default=38
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='aguardando_analise')
    analista = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='documentos_analisados'
    )
    documento_original = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='revisoes'
    )
    is_active = models.BooleanField(default=True, help_text='Indica se o documento está ativo.')
    document_type = models.CharField(
        max_length=20,
        choices=DOCUMENT_TYPE_CHOICES,
        default='pdf',
        help_text='Tipo do documento: PDF ou Planilha.'
    )

    class Meta:
        default_permissions = ()  # Desativa as permissões padrão
        permissions = [
            ('view_documentos', 'Listar Documentos'),
            ('can_add_documento', 'Adicionar Documento'),
            ('can_active', 'Pode ativar/inativar documentos'),
            ('view_acessos_documento', 'Visualizar Acessos Documentos'),
            ('can_view_revisions', 'Visualizar revisões de Documentos'),
            ('view_documentos_ina', 'Listar Documentos Inativos'),
            ('list_pending_approvals', 'Aprovações Pendentes'),
            ('list_reproaches', 'Lista Reprovações'),
            ('can_approve', 'Pode aprovar documentos'),
            ('can_analyze', 'Pode analisar documentos'),
            ('can_view_editables', 'Lista Editáveis'),
            ('view_categoria', 'Lista Categorias'),
            ('add_categoria', 'Adicionar Categoria'),
            ('change_categoria', 'Editar Categoria'),
            ('delete_categoria', 'Deletar Categoria'),
        ]

    def __str__(self):
        status = 'Ativo' if self.is_active else 'Inativo'
        return f"{self.nome} - Revisão {self.revisao:02d} - Status: {self.get_status_display()} - {status}"

    def save(self, *args, **kwargs):
        logger.debug(f"[save] Salvando documento '{self.nome}' (ID: {self.id}) com status '{self.status}'.")

        if self.documento:
            ext = os.path.splitext(self.documento.name)[1].lower()
            logger.debug(f"[save] Extensão do documento: {ext}")
            
            # Só atualizar o document_type se não for 'pdf_spreadsheet'
            if self.document_type != 'pdf_spreadsheet':
                if ext in ['.doc', '.docx', '.odt']:
                    self.document_type = 'pdf'
                elif ext in ['.xls', '.xlsx', '.ods']:
                    self.document_type = 'spreadsheet'
                else:
                    logger.error(f"[save] Tipo de arquivo inválido: {ext}")
                    raise ValidationError('Tipo de arquivo inválido.')

        super(Documento, self).save(*args, **kwargs)
        logger.debug(f"[save] Documento '{self.nome}' (ID: {self.id}) salvo com sucesso.")

    def gerar_pdf(self):
        """
        Gera um PDF a partir do documento editável utilizando LibreOffice e atualiza o campo documento_pdf.
        Para planilhas, apenas copia o arquivo original para documento_pdf sem conversão.
        Para pdf_spreadsheet, o PDF já está anexado manualmente.
        """
        logger.debug(f"[gerar_pdf] Iniciando processo para o documento '{self.nome}' (ID: {self.id}) com tipo '{self.document_type}'.")

        try:
            if self.document_type == 'pdf_spreadsheet':
                # Se já é 'pdf_spreadsheet', o PDF já foi anexado manualmente.
                # Basta verificar se o arquivo existe.
                if self.documento_pdf and os.path.exists(self.documento_pdf.path):
                    logger.info(f"[gerar_pdf] Documento PDF já disponível em: {self.documento_pdf.path}")
                    return self.documento_pdf.path
                else:
                    logger.error("[gerar_pdf] Tipo 'pdf_spreadsheet' definido, mas documento_pdf não encontrado.")
                    raise FileNotFoundError("Documento PDF não encontrado para pdf_spreadsheet.")

            elif self.document_type == 'spreadsheet':
                # Para planilhas, copiar o arquivo original para documento_pdf
                documento_path = self.documento.path
                logger.debug(f"[gerar_pdf] Caminho do documento editável: {documento_path}")
                safe_nome = slugify(self.nome)
                desired_spreadsheet_filename = f"{safe_nome}_v{self.revisao}{Path(documento_path).suffix}"
                desired_spreadsheet_path = Path('documentos') / 'spreadsheet' / desired_spreadsheet_filename
                full_desired_spreadsheet_path = os.path.join(settings.MEDIA_ROOT, desired_spreadsheet_path)
                logger.debug(f"[gerar_pdf] Caminho desejado para a planilha: {full_desired_spreadsheet_path}")

                if self.documento_pdf and self.documento_pdf.storage.exists(self.documento_pdf.name):
                    old_spreadsheet_path = self.documento_pdf.path
                    logger.debug(f"[gerar_pdf] Deletando arquivo antigo documento_pdf: {old_spreadsheet_path}")
                    self.documento_pdf.delete(save=False)
                    logger.debug("[gerar_pdf] Arquivo antigo documento_pdf deletado.")

                os.makedirs(os.path.dirname(full_desired_spreadsheet_path), exist_ok=True)
                logger.debug(f"[gerar_pdf] Diretório criado ou já existente: {os.path.dirname(full_desired_spreadsheet_path)}")

                shutil.copy(documento_path, full_desired_spreadsheet_path)
                logger.debug(f"[gerar_pdf] Planilha copiada para: {full_desired_spreadsheet_path}")

                self.documento_pdf.name = desired_spreadsheet_path.as_posix()
                logger.debug(f"[gerar_pdf] Caminho salvo no campo documento_pdf: {self.documento_pdf.name}")

                self.save(update_fields=['documento_pdf'])
                logger.info(f"[gerar_pdf] Planilha atualizada e salva no campo documento_pdf: {self.documento_pdf.path}")
                return self.documento_pdf.path

            elif self.document_type == 'pdf':
                # Lógica para conversão para PDF
                logger.debug("[gerar_pdf] Tipo de documento é PDF. Iniciando conversão para PDF.")
                documento_path = self.documento.path
                logger.debug(f"[gerar_pdf] Caminho do documento editável: {documento_path}")

                if not os.path.exists(documento_path):
                    logger.error(f"[gerar_pdf] Arquivo de documento não encontrado: {documento_path}")
                    raise FileNotFoundError(f"Arquivo de documento não encontrado: {documento_path}")

                soffice_path = settings.LIBREOFFICE_PATH
                logger.debug(f"[gerar_pdf] Caminho do LibreOffice: {soffice_path}")

                if not shutil.which(soffice_path):
                    logger.error(f"[gerar_pdf] Executável do LibreOffice não encontrado: {soffice_path}")
                    raise FileNotFoundError(f"Executável do LibreOffice não encontrado: {soffice_path}")

                env = os.environ.copy()
                env["PATH"] = "/usr/bin:/bin:" + env.get("PATH", "")
                logger.debug(f"[gerar_pdf] PATH para subprocesso: {env['PATH']}")

                with tempfile.TemporaryDirectory() as tmpdirname:
                    comando = [
                        soffice_path,
                        '--headless',
                        '--convert-to', 'pdf',
                        '--outdir', tmpdirname,
                        documento_path
                    ]

                    logger.debug(f"[gerar_pdf] Executando comando: {' '.join(comando)}")
                    resultado = subprocess.run(
                        comando,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        env=env
                    )

                    logger.debug(f"[gerar_pdf] Retorno do subprocess: {resultado.returncode}")
                    logger.debug(f"[gerar_pdf] STDOUT: {resultado.stdout}")
                    logger.debug(f"[gerar_pdf] STDERR: {resultado.stderr}")

                    if resultado.returncode != 0:
                        logger.error(f"[gerar_pdf] Erro na conversão para PDF: {resultado.stderr}")
                        raise RuntimeError(f"Erro na conversão para PDF: {resultado.stderr}")

                    input_filename = os.path.basename(documento_path)
                    base_name, _ = os.path.splitext(input_filename)
                    generated_pdf_filename = f"{base_name}.pdf"
                    generated_pdf_path = Path(tmpdirname) / generated_pdf_filename

                    if not generated_pdf_path.exists():
                        logger.error(f"[gerar_pdf] Arquivo PDF não encontrado após a conversão: {generated_pdf_path}")
                        raise FileNotFoundError(f"Arquivo PDF não encontrado após a conversão: {generated_pdf_path}")

                    logger.debug("[gerar_pdf] PDF gerado com sucesso.")

                    if self.documento_pdf and self.documento_pdf.storage.exists(self.documento_pdf.name):
                        old_pdf_path = self.documento_pdf.path
                        logger.debug(f"[gerar_pdf] Deletando arquivo antigo documento_pdf: {old_pdf_path}")
                        self.documento_pdf.delete(save=False)
                        logger.debug("[gerar_pdf] Arquivo antigo documento_pdf deletado.")

                    safe_nome = slugify(self.nome)
                    desired_pdf_filename = f"{safe_nome}_v{self.revisao}.pdf"
                    desired_pdf_path = Path('documentos') / 'pdf' / desired_pdf_filename
                    full_desired_pdf_path = os.path.join(settings.MEDIA_ROOT, desired_pdf_path)
                    logger.debug(f"[gerar_pdf] Caminho desejado para o PDF: {full_desired_pdf_path}")

                    os.makedirs(os.path.dirname(full_desired_pdf_path), exist_ok=True)
                    logger.debug(f"[gerar_pdf] Diretório criado ou já existente: {os.path.dirname(full_desired_pdf_path)}")

                    shutil.move(str(generated_pdf_path), full_desired_pdf_path)
                    logger.debug(f"[gerar_pdf] PDF movido para: {full_desired_pdf_path}")

                    self.documento_pdf.name = desired_pdf_path.as_posix()
                    logger.debug(f"[gerar_pdf] Caminho salvo no campo documento_pdf: {self.documento_pdf.name}")

                    self.save(update_fields=['documento_pdf'])
                    logger.info(f"[gerar_pdf] PDF atualizado e salvo no campo documento_pdf: {self.documento_pdf.path}")
                    return self.documento_pdf.path

            else:
                logger.error("[gerar_pdf] Tipo de documento inválido.")
                raise ValueError("Tipo de documento inválido.")

        except ValidationError as ve:
            logger.error(f"[gerar_pdf] Validação de erro: {ve}")
            raise ve
        except Exception as e:
            logger.error(f"[gerar_pdf] Erro ao gerar ou salvar o documento_pdf: {e}", exc_info=True)
            raise

# Modelo Acesso
class Acesso(models.Model):
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data_acesso = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario.username} - {self.documento.nome}"
