# documentos/models.py

from django.db import models
from django.contrib.auth import get_user_model
<<<<<<< HEAD
import os
from django.core.files import File
import aspose.words as aw
from django.conf import settings  # Importar settings
=======
from django.utils import timezone
import os
from django.conf import settings
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22

User = get_user_model()

def documento_upload_path(instance, filename):
<<<<<<< HEAD
    # Salva em media/documentos/editaveis/nome_do_arquivo
    return os.path.join('documentos', 'editaveis', filename)

def pdf_upload_path(instance, filename):
    # Salva em media/documentos/pdf/nome_do_arquivo
=======
    # Caminho para salvar o documento original (Word)
    return os.path.join('documentos', 'editaveis', filename)

def pdf_upload_path(instance, filename):
    # Caminho para salvar o documento em PDF
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
    return os.path.join('documentos', 'pdf', filename)

class Categoria(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nome

class Documento(models.Model):
    nome = models.CharField(max_length=200)
<<<<<<< HEAD
    revisao = models.IntegerField(choices=[(i, f"{i:02d}") for i in range(0, 101)])
=======
    revisao = models.IntegerField(choices=[(i, f"{i:02d}") for i in range(1, 101)])
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    aprovador1 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='aprovador1_documentos')
    aprovador2 = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='aprovador2_documentos')
    documento = models.FileField(upload_to=documento_upload_path)
    documento_pdf = models.FileField(upload_to=pdf_upload_path, editable=False, null=True, blank=True)
    data_criacao = models.DateTimeField(auto_now_add=True)
    aprovado_por_aprovador1 = models.BooleanField(default=False)
    aprovado_por_aprovador2 = models.BooleanField(default=False)
<<<<<<< HEAD
    reprovado = models.BooleanField(default=False)
    motivo_reprovacao = models.TextField(null=True, blank=True)
=======
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22

    class Meta:
        permissions = [
            ('can_approve', 'Pode aprovar documentos'),
<<<<<<< HEAD
            ('can_reject', 'Pode reprovar documentos'),
        ]

    def __str__(self):
        return f"{self.nome} - Revisão {self.revisao}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.documento:
            documento_path = self.documento.path
            doc = aw.Document(documento_path)

            # Definir o nome do arquivo PDF
            pdf_filename = f"{self.nome}_v{self.revisao}.pdf"
            # Caminho para salvar o PDF dentro do MEDIA_ROOT
            pdf_directory = os.path.join(settings.MEDIA_ROOT, 'documentos', 'pdf')
            # Criar o diretório se não existir
            os.makedirs(pdf_directory, exist_ok=True)
            pdf_path = os.path.join(pdf_directory, pdf_filename)
            # Salvar o PDF
            doc.save(pdf_path)

            # Salvar o campo documento_pdf com o caminho relativo
            with open(pdf_path, 'rb') as pdf_file:
                self.documento_pdf.save(pdf_filename, File(pdf_file), save=False)

            super().save(update_fields=['documento_pdf'])
=======
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
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
