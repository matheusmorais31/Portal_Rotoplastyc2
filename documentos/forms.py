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
            'bloqueada': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class DocumentoForm(forms.ModelForm):
    aprovador1 = forms.ModelChoiceField(
        queryset=User.objects.none(),  # Inicialmente vazio, será definido no __init__
        label='Aprovador',
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        empty_label="Selecione um aprovador"
    )

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
            'documento': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': '.doc,.docx,.odt,.xls,.xlsx,.ods'  # Atualiza os tipos de arquivo aceitos
            }),
        }

    def __init__(self, *args, **kwargs):
        super(DocumentoForm, self).__init__(*args, **kwargs)
        self.fields['aprovador1'].queryset = self._set_aprovadores()
        self.fields['aprovador1'].label_from_instance = self.get_aprovador_label

    def _set_aprovadores(self):
        """Define a queryset dos aprovadores com permissão e que estão ativos."""
        content_type = ContentType.objects.get_for_model(Documento)
        try:
            permission = Permission.objects.get(content_type=content_type, codename='can_approve')
            aprovadores = User.objects.filter(
                Q(user_permissions=permission) | Q(groups__permissions=permission),
                is_active=True  # Filtra apenas usuários ativos
            ).distinct()
            return aprovadores
        except Permission.DoesNotExist:
            # Caso a permissão 'can_approve' não exista, define como vazio
            logger.warning("Permissão 'can_approve' não encontrada.")
            return User.objects.none()

    def get_aprovador_label(self, obj):
        """Retorna o nome completo do usuário como label."""
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return f"{full_name} ({obj.username})" if full_name else obj.username

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')

        if not documento:
            raise ValidationError('É necessário anexar o documento.')

        # Validação da extensão do arquivo para determinar o tipo automaticamente
        ext = os.path.splitext(documento.name)[1].lower()
        if ext in ['.doc', '.docx', '.odt']:
            valid_extensions = ['.doc', '.docx', '.odt']
        elif ext in ['.xls', '.xlsx', '.ods']:
            valid_extensions = ['.xls', '.xlsx', '.ods']
        else:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx, .odt, .xls, .xlsx e .ods são permitidos.')

        if ext not in valid_extensions:
            raise ValidationError('Formato de arquivo inválido.')

        return documento

    def clean(self):
        cleaned_data = super().clean()
        nome = cleaned_data.get('nome')

        # Verificar se já existe um documento com o mesmo nome que não foi reprovado
        documentos_existentes = Documento.objects.filter(nome=nome).exclude(status='reprovado')

        if documentos_existentes.exists():
            raise ValidationError('Já existe um documento aprovado ou pendente com este nome. Escolha outro nome.')

        return cleaned_data

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
                'accept': '.doc,.docx,.odt,.xls,.xlsx,.ods'  # Atualiza os tipos de arquivo aceitos
            }),
        }

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')
        if not documento:
            raise ValidationError('É necessário fazer o upload do documento revisado.')

        # Validação da extensão do arquivo para determinar o tipo automaticamente
        ext = os.path.splitext(documento.name)[1].lower()
        if ext in ['.doc', '.docx', '.odt']:
            valid_extensions = ['.doc', '.docx', '.odt']
        elif ext in ['.xls', '.xlsx', '.ods']:
            valid_extensions = ['.xls', '.xlsx', '.ods']
        else:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx, .odt, .xls, .xlsx e .ods são permitidos.')

        if ext not in valid_extensions:
            raise ValidationError('Formato de arquivo inválido.')

        return documento

class NovaRevisaoForm(forms.ModelForm):
    aprovador1 = forms.ModelChoiceField(
        queryset=User.objects.none(),  # Inicialmente vazio, será definido no __init__
        label='Aprovador',
        widget=forms.Select(attrs={'class': 'form-control select2'}),
        empty_label="Selecione um aprovador"
    )

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
            'documento': forms.FileInput(attrs={
                'class': 'form-control-file',
                'accept': '.doc,.docx,.odt,.xls,.xlsx,.ods'  # Atualiza os tipos de arquivo aceitos
            }),
        }

    def __init__(self, *args, **kwargs):
        self.documento_atual = kwargs.pop('documento_atual', None)
        super(NovaRevisaoForm, self).__init__(*args, **kwargs)
        
        # Definir as revisões maiores que a atual
        if self.documento_atual:
            revisao_atual = self.documento_atual.revisao
            proxima_revisao = revisao_atual + 1
            choices = [(proxima_revisao, f"{proxima_revisao:02d}")]
        else:
            choices = [(1, "Revisão 01")]

        self.fields['revisao'].choices = choices

        # Definir o queryset dos aprovadores
        self.fields['aprovador1'].queryset = self._set_aprovadores()
        self.fields['aprovador1'].label_from_instance = self.get_aprovador_label

    def _set_aprovadores(self):
        """Define a queryset dos aprovadores com permissão e que estão ativos."""
        content_type = ContentType.objects.get_for_model(Documento)
        try:
            permission = Permission.objects.get(content_type=content_type, codename='can_approve')
            aprovadores = User.objects.filter(
                Q(user_permissions=permission) | Q(groups__permissions=permission),
                is_active=True
            ).distinct()
            return aprovadores
        except Permission.DoesNotExist:
            # Caso a permissão 'can_approve' não exista, define como vazio
            logger.warning("Permissão 'can_approve' não encontrada.")
            return User.objects.none()

    def get_aprovador_label(self, obj):
        """Retorna o nome completo do usuário como label."""
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return f"{full_name} ({obj.username})" if full_name else obj.username

    def clean_documento(self):
        documento = self.cleaned_data.get('documento')
        if not documento:
            raise ValidationError('É necessário anexar o documento.')

        # Validação da extensão do arquivo para determinar o tipo automaticamente
        ext = os.path.splitext(documento.name)[1].lower()
        if ext in ['.doc', '.docx', '.odt']:
            valid_extensions = ['.doc', '.docx', '.odt']
        elif ext in ['.xls', '.xlsx', '.ods']:
            valid_extensions = ['.xls', '.xlsx', '.ods']
        else:
            raise ValidationError('Formato de arquivo inválido. Apenas arquivos .doc, .docx, .odt, .xls, .xlsx e .ods são permitidos.')

        if ext not in valid_extensions:
            raise ValidationError('Formato de arquivo inválido.')

        return documento

    def clean(self):
        cleaned_data = super().clean()
        revisao = cleaned_data.get('revisao')

        if self.documento_atual and revisao:
            revisao_atual = self.documento_atual.revisao
            if revisao <= revisao_atual:
                raise ValidationError('A revisão deve ser maior que a revisão atual.')
            
            # Verificar se já existe uma revisão aprovada com o mesmo número
            if Documento.objects.filter(
                nome=self.documento_atual.nome,
                revisao=revisao,
                status='aprovado' 
            ).exists():
                raise ValidationError('Já existe uma revisão aprovada com este número para este documento.')

        return cleaned_data
