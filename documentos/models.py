from django.db import models
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver
import os
from django.core.files import File
from django.core.files.storage import FileSystemStorage
import aspose.words as aw
from django.conf import settings
import logging

logger = logging.getLogger('django')

User = get_user_model()

def documento_upload_path(instance, filename):
    """
    Função para definir o caminho de upload dos documentos editáveis.
    """
    return os.path.join('documentos', 'editaveis', filename)

def pdf_upload_path(instance, filename):
    """
    Função para definir o caminho de upload dos documentos PDF gerados.
    """
    return os.path.join('documentos', 'pdf', filename)

class Categoria(models.Model):
    """
    Modelo para definir a categoria de um documento.
    """
    nome = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nome

class Documento(models.Model):
    """
    Modelo para representar os documentos do sistema.
    """
    nome = models.CharField(max_length=200)
    revisao = models.IntegerField(choices=[(i, f"{i:02d}") for i in range(0, 101)])
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    aprovador1 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='aprovador1_documentos')
    aprovador2 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='aprovador2_documentos')
    documento = models.FileField(upload_to=documento_upload_path)
    documento_pdf = models.FileField(upload_to=pdf_upload_path, editable=False, null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    aprovado_por_aprovador1 = models.BooleanField(default=False)
    aprovado_por_aprovador2 = models.BooleanField(default=False)
    reprovado = models.BooleanField(default=False)
    motivo_reprovacao = models.TextField(null=True, blank=True)

    class Meta:
        permissions = [
            ('can_approve', 'Pode aprovar documentos'),
            ('can_reject', 'Pode reprovar documentos'),
        ]

    def __str__(self):
        return f"{self.nome} - Revisão {self.revisao}"

    def gerar_pdf_path(self):
        """
        Função para definir o caminho do PDF baseado no nome e revisão do documento.
        """
        return os.path.join('documentos', 'pdf', f"{self.nome}_v{self.revisao}.pdf")

    def remover_pdf_antigo(self):
        """
        Função para remover o arquivo PDF antigo, caso já exista no sistema de arquivos.
        """
        pdf_path = self.gerar_pdf_path()
        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'documentos', 'pdf'))
        
        # Verifica se o arquivo PDF existe e o remove
        if fs.exists(os.path.basename(pdf_path)):
            fs.delete(os.path.basename(pdf_path))
            logger.debug(f"[PDF] Arquivo PDF antigo removido diretamente: {pdf_path}")

    def gerar_pdf(self):
        """
        Gera o PDF a partir do documento original (Word ou outro formato).
        """
        try:
            documento_path = self.documento.path
            doc = aw.Document(documento_path)

            # Definir o caminho do PDF
            pdf_path = self.gerar_pdf_path()

            # Gera e salva o PDF no caminho definido
            doc.save(pdf_path)
            logger.debug(f"[PDF] PDF gerado e salvo em: {pdf_path}")

            return pdf_path
        except Exception as e:
            logger.error(f"[PDF] Erro ao gerar ou salvar o PDF: {e}")
            raise

# Sinal para gerar o PDF após a criação ou modificação de um documento
@receiver(post_save, sender=Documento)
def gerar_pdf_documento(sender, instance, created, **kwargs):
    logger.debug(f"[PDF] Entrou no sinal post_save para Documento: {instance.nome}, Criado: {created}")

    # Verificar se o arquivo de documento original existe
    if not instance.documento:
        logger.warning(f"[PDF] Documento {instance.nome} - Revisão {instance.revisao} não possui arquivo original anexado.")
        return

    logger.debug(f"[PDF] Documento: {instance.nome} - Revisão: {instance.revisao}, Caminho do documento: {instance.documento.path}")

    # Gera o PDF apenas se o documento foi criado ou se o arquivo foi modificado
    if created or 'documento' in instance.get_dirty_fields():
        logger.debug(f"[PDF] Gerando PDF para o documento: {instance.nome} - Revisão {instance.revisao}")

        try:
            # Remove o PDF antigo, se existir
            instance.remover_pdf_antigo()

            # Gera o novo PDF
            pdf_path = instance.gerar_pdf()

            # Salvar o campo documento_pdf sem chamar save() novamente
            with open(pdf_path, 'rb') as pdf_file:
                instance.documento_pdf.save(os.path.basename(pdf_path), File(pdf_file), save=False)
                logger.debug(f"[PDF] Campo documento_pdf atualizado no objeto em memória: {instance.documento_pdf.name}")

            # Atualizar o campo documento_pdf diretamente no banco de dados
            Documento.objects.filter(pk=instance.pk).update(documento_pdf=instance.documento_pdf.name)
            logger.debug(f"[PDF] Campo documento_pdf persistido no banco: {instance.documento_pdf.name}")

        except Exception as e:
            logger.error(f"[PDF] Erro ao gerar ou salvar o PDF: {e}")

    else:
        logger.debug(f"[PDF] Nenhuma alteração no campo 'documento', PDF não gerado.")
