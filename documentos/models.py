# documentos/models.py

from django.db import models
from django.contrib.auth import get_user_model
from django.core.files import File
import aspose.words as aw
from pathlib import Path
from django.conf import settings
import logging
from django.utils.text import slugify
from django.core.files.storage import FileSystemStorage
from io import BytesIO
import gc
import os

logger = logging.getLogger('django')

User = get_user_model()

# Classe de Armazenamento Personalizada para Sobrescrever Arquivos Existentes
class OverwriteStorage(FileSystemStorage):
    """
    Custom storage class that overwrites existing files with the same name.
    """
    def get_available_name(self, name, max_length=None):
        """
        Returns a filename that's available for new content, deleting the existing file if necessary.
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
        upload_to=pdf_upload_path,
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

    def gerar_pdf_path(self):
        """
        Gera o caminho para o PDF utilizando slugify para nomes seguros.
        Retorna um caminho com barras normais ('/') para consistência.
        """
        safe_nome = slugify(self.nome)
        filename = f"{safe_nome}_v{self.revisao}.pdf"
        path = Path('documentos') / 'pdf' / filename
        logger.debug(f"[gerar_pdf_path] Gerado caminho para o PDF: {path.as_posix()}")
        return path.as_posix()  # Garante que o separador é '/'

    def remover_pdf_antigo(self):
        """
        Remove PDFs antigos com o mesmo nome base para evitar duplicações.
        """
        pdf_directory = Path(settings.MEDIA_ROOT) / 'documentos' / 'pdf'
        pdf_base_name = slugify(self.nome)
        # Construir o padrão de busca para PDFs com o mesmo nome base
        search_pattern = f"{pdf_base_name}_v*.pdf"

        # Remover todos os PDFs que correspondem ao padrão
        for file_path in pdf_directory.glob(search_pattern):
            if file_path.is_file():
                try:
                    file_path.unlink()
                    logger.debug(f"[remover_pdf_antigo] PDF duplicado removido: {file_path}")
                except Exception as e:
                    logger.error(f"[remover_pdf_antigo] Falha ao remover {file_path}: {e}")

    def gerar_pdf(self):
        """
        Gera um PDF a partir do documento editável e atualiza o campo documento_pdf.
        """
        try:
            logger.debug("[gerar_pdf] Iniciando geração do PDF.")
            documento_path = self.documento.path
            doc = aw.Document(documento_path)

            # Gerar o PDF em memória para evitar manter o arquivo aberto no disco
            pdf_io = BytesIO()
            doc.save(pdf_io, aw.SaveFormat.PDF)
            pdf_io.seek(0)
            logger.debug("[gerar_pdf] PDF gerado em memória.")

            # Remover PDFs antigos antes de salvar o novo
            self.remover_pdf_antigo()

            # Deletar explicitamente o arquivo antigo no campo documento_pdf, se existir
            if self.documento_pdf:
                self.documento_pdf.delete(save=False)
                logger.debug("[gerar_pdf] Arquivo antigo documento_pdf deletado.")

            # Forçar a liberação do objeto `doc`
            del doc
            gc.collect()

            # Salvar o PDF no campo `documento_pdf`
            safe_nome = slugify(self.nome)
            filename = f"{safe_nome}_v{self.revisao}.pdf"
            self.documento_pdf.save(filename, File(pdf_io), save=False)  # Passar apenas o nome do arquivo

            self.save(update_fields=['documento_pdf'])

            logger.info(f"[gerar_pdf] PDF atualizado e salvo no campo `documento_pdf`: {self.documento_pdf.path}")
            return self.documento_pdf.path
        except Exception as e:
            logger.error(f"[gerar_pdf] Erro ao gerar ou salvar o PDF: {e}")
            raise

    def __str__(self):
        return f"{self.nome} - Revisão {self.revisao} - Status: {self.get_status_display()}"

    class Meta:
        permissions = [
            ('can_approve', 'Pode aprovar documentos'),
            ('can_reject', 'Pode reprovar documentos'),
            ('can_analyze', 'Pode analisar documentos'),
            ('can_view_editables', 'Pode visualizar documentos editáveis'),
        ]

# Modelo Acesso
class Acesso(models.Model):
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data_acesso = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario.username} - {self.documento.nome}"
