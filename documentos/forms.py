# documentos/forms.py

from django import forms
from .models import Categoria, Documento
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
import logging
import os

# Definir o logger
logger = logging.getLogger('django')

User = get_user_model()

# Formulário para a categoria
class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome', 'bloqueada']
        labels = {
            'nome': 'Nome da Categoria',
            'bloqueada': 'Bloquear Downloads e Impressões',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'bloqueada': forms.CheckboxInput(),
        }

# Formulário para o documento
class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['nome', 'revisao', 'categoria', 'aprovador1', 'documento']
        labels = {
            'nome': 'Nome do Documento',
            'revisao': 'Revisão',
            'categoria': 'Categoria',
            'aprovador1': 'Aprovador',
            'documento': 'Anexar Documento',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'revisao': forms.Select(attrs={'class': 'form-control select2'}),
            'categoria': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador1': forms.Select(attrs={'class': 'form-control select2'}),
            'documento': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': '.doc,.docx,.odt'  # Restringe os tipos de arquivo no cliente
            }),
        }

    def __init__(self, *args, **kwargs):
        super(DocumentoForm, self).__init__(*args, **kwargs)
        self._set_aprovadores()

    def _set_aprovadores(self):
        """Define a queryset dos aprovadores com permissão e que estão ativos."""
        content_type = ContentType.objects.get_for_model(Documento)
        permission = Permission.objects.get(content_type=content_type, codename='can_approve')
        aprovadores = User.objects.filter(
            Q(user_permissions=permission) | Q(groups__permissions=permission),
            is_active=True  # Filtra apenas usuários ativos
        ).distinct()
        self.fields['aprovador1'].queryset = aprovadores

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')
        if not documento:
            raise ValidationError('É necessário anexar o documento.')

        # Validação da extensão do arquivo
        ext = os.path.splitext(documento.name)[1]  # Obtém a extensão
        valid_extensions = ['.doc', '.docx', '.odt']
        if not ext.lower() in valid_extensions:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx e .odt são permitidos.')

        return documento

    def clean(self):
        cleaned_data = super().clean()
        nome = cleaned_data.get('nome')
        
        # Verificar se já existe um documento com o mesmo nome que não foi reprovado
        documentos_existentes = Documento.objects.filter(nome=nome).exclude(status='reprovado')
        
        if documentos_existentes.exists():
            raise ValidationError('Já existe um documento aprovado ou pendente com este nome. Escolha outro nome.')

        return cleaned_data

# Formulário para o analista
class AnaliseDocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['documento']
        labels = {
            'documento': 'Upload do Documento Revisado',
        }
        widgets = {
            'documento': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': '.doc,.docx,.odt'  # Restringe os tipos de arquivo no cliente
            }),
        }

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')
        if not documento:
            raise ValidationError('É necessário fazer o upload do documento revisado.')

        # Validação da extensão do arquivo
        ext = os.path.splitext(documento.name)[1]
        valid_extensions = ['.doc', '.docx', '.odt']
        if not ext.lower() in valid_extensions:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx e .odt são permitidos.')

        return documento

class NovaRevisaoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['revisao', 'aprovador1', 'documento']
        labels = {
            'revisao': 'Revisão',
            'aprovador1': 'Aprovador',
            'documento': 'Anexar Documento',
        }
        widgets = {
            'revisao': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador1': forms.Select(attrs={'class': 'form-control select2'}),
            'documento': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': '.doc,.docx,.odt'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.documento_atual = kwargs.pop('documento_atual', None)
        super().__init__(*args, **kwargs)
        
        # Definir as revisões maiores que a atual
        if self.documento_atual:
            revisao_atual = self.documento_atual.revisao
            proxima_revisao = str(revisao_atual + 1).zfill(2)
            choices = [(proxima_revisao, f"{proxima_revisao}")]
        else:
            choices = [("01", "Revisão 01")]

        self.fields['revisao'].choices = choices
        
        # Definir o queryset dos aprovadores
        content_type = ContentType.objects.get_for_model(Documento)
        permission = Permission.objects.get(content_type=content_type, codename='can_approve')
        aprovadores = User.objects.filter(
            Q(user_permissions=permission) | Q(groups__permissions=permission),
            is_active=True
        ).distinct()
        self.fields['aprovador1'].queryset = aprovadores

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')
        if not documento:
            raise ValidationError('É necessário anexar o documento.')

        # Validação da extensão do arquivo
        ext = os.path.splitext(documento.name)[1]
        valid_extensions = ['.doc', '.docx', '.odt']
        if not ext.lower() in valid_extensions:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx e .odt são permitidos.')

        return documento

    def clean(self):
        cleaned_data = super().clean()
        revisao = cleaned_data.get('revisao')

        if self.documento_atual and revisao:
            revisao_atual = self.documento_atual.revisao
            if int(revisao) <= int(revisao_atual):
                raise ValidationError('A revisão deve ser maior que a revisão atual.')
            
            # Verificar se já existe uma revisão aprovada com o mesmo número
            if Documento.objects.filter(
                nome=self.documento_atual.nome,
                revisao=revisao,
                status='aprovado' 
            ).exists():
                raise ValidationError('Já existe uma revisão aprovada com este número para este documento.')

        return cleaned_data
