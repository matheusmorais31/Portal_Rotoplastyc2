# documentos/models.py

from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import os
from django.conf import settings

User = get_user_model()

def documento_upload_path(instance, filename):
    # Caminho para salvar o documento original (Word)
    return os.path.join('documentos', 'editaveis', filename)

def pdf_upload_path(instance, filename):
    # Caminho para salvar o documento em PDF
    return os.path.join('documentos', 'pdf', filename)

class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nome

class Documento(models.Model):
    nome = models.CharField(max_length=200)
    revisao = models.IntegerField(choices=[(i, f"{i:02d}") for i in range(1, 101)])
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    aprovador1 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='aprovador1_documentos')
    aprovador2 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='aprovador2_documentos')
    documento = models.FileField(upload_to=documento_upload_path)
    documento_pdf = models.FileField(upload_to=pdf_upload_path, editable=False, null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    aprovado_por_aprovador1 = models.BooleanField(default=False)
    aprovado_por_aprovador2 = models.BooleanField(default=False)

    class Meta:
        permissions = [
            ('can_approve', 'Pode aprovar documentos'),
        ]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Converter o documento para PDF após salvar
        if self.documento:
            from docx2pdf import convert
            import tempfile

            # Caminho completo do arquivo Word
            documento_path = self.documento.path

            # Criar um arquivo temporário para o PDF
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
                # Converter o documento para PDF
                convert(documento_path, tmp_pdf.name)
                # Salvar o PDF no campo documento_pdf
                self.documento_pdf.name = pdf_upload_path(self, os.path.basename(tmp_pdf.name))
                with open(tmp_pdf.name, 'rb') as pdf_file:
                    self.documento_pdf.save(os.path.basename(tmp_pdf.name), pdf_file, save=False)
                os.unlink(tmp_pdf.name)
                super().save(update_fields=['documento_pdf'])
