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

# Definir caminhos de upload para arquivos
def documento_upload_path(instance, filename):
    return os.path.join('documentos', 'editaveis', filename)

def pdf_upload_path(instance, filename):
    return os.path.join('documentos', 'pdf', filename)

# Modelo de Categorias para documentos
class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nome

# Modelo principal de Documento
class Documento(models.Model):
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
    elaborador = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='documentos_criados')
    solicitante = models.ForeignKey(User, on_delete=models.CASCADE, default=38)  # ID do usuário padrão

    def get_dirty_fields(self):
        dirty_fields = {}
        if self.pk is not None:
            old_instance = self.__class__.objects.get(pk=self.pk)
            for field in self._meta.fields:
                field_name = field.name
                if getattr(self, field_name) != getattr(old_instance, field_name):
                    dirty_fields[field_name] = getattr(self, field_name)
        return dirty_fields

    class Meta:
        permissions = [
            ('can_approve', 'Pode aprovar documentos'),
            ('can_reject', 'Pode reprovar documentos'),
        ]

    def __str__(self):
        return f"{self.nome} - Revisão {self.revisao}"

    def gerar_pdf_path(self):
        return os.path.join('documentos', 'pdf', f"{self.nome}_v{self.revisao}.pdf")

    def remover_pdf_antigo(self):
        pdf_path = self.gerar_pdf_path()
        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'documentos', 'pdf'))
        
        if fs.exists(os.path.basename(pdf_path)):
            fs.delete(os.path.basename(pdf_path))
            logger.debug(f"[PDF] Arquivo PDF antigo removido diretamente: {pdf_path}")

    def gerar_pdf(self):
        try:
            documento_path = self.documento.path
            doc = aw.Document(documento_path)
            pdf_path = self.gerar_pdf_path()
            doc.save(pdf_path)
            logger.debug(f"[PDF] PDF gerado e salvo em: {pdf_path}")
            return pdf_path
        except Exception as e:
            logger.error(f"[PDF] Erro ao gerar ou salvar o PDF: {e}")
            raise

# Sinal para gerar o PDF automaticamente após salvar o documento
@receiver(post_save, sender=Documento)
def gerar_pdf_documento(sender, instance, created, **kwargs):
    if not instance.documento:
        return
    if created or 'documento' in instance.get_dirty_fields():
        instance.remover_pdf_antigo()
        pdf_path = instance.gerar_pdf()
        with open(pdf_path, 'rb') as pdf_file:
            instance.documento_pdf.save(os.path.basename(pdf_path), File(pdf_file), save=False)
        Documento.objects.filter(pk=instance.pk).update(documento_pdf=instance.documento_pdf.name)

# Modelo de Acesso aos documentos, para registrar acessos
class Acesso(models.Model):
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    data_acesso = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.usuario.username} - {self.documento.nome}"
