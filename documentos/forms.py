from django import forms
from .models import Categoria, Documento
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
import logging

# Definir o logger
logger = logging.getLogger('django')

User = get_user_model()

# Formulário para a categoria
class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome']
        labels = {'nome': 'Nome da Categoria'}
        widgets = {'nome': forms.TextInput(attrs={'class': 'form-control'})}

# Formulário para o documento
class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['nome', 'revisao', 'categoria', 'aprovador1', 'aprovador2', 'documento']
        labels = {
            'nome': 'Nome do Documento',
            'revisao': 'Revisão',
            'categoria': 'Categoria',
            'aprovador1': 'Aprovador 1',
            'aprovador2': 'Aprovador 2',
            'documento': 'Anexar Documento',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'revisao': forms.Select(attrs={'class': 'form-control select2'}),
            'categoria': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador1': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador2': forms.Select(attrs={'class': 'form-control select2'}),
            'documento': forms.FileInput(attrs={'class': 'form-control-file'}),
        }

    def __init__(self, *args, **kwargs):
        super(DocumentoForm, self).__init__(*args, **kwargs)
        self._set_aprovadores()

    def _set_aprovadores(self):
        """Define a queryset dos aprovadores baseada nas permissões de aprovação."""
        content_type = ContentType.objects.get_for_model(Documento)
        permission = Permission.objects.get(content_type=content_type, codename='can_approve')
        aprovadores = User.objects.filter(
            Q(user_permissions=permission) | Q(groups__permissions=permission)
        ).distinct()
        self.fields['aprovador1'].queryset = aprovadores
        self.fields['aprovador2'].queryset = aprovadores

    def save(self, commit=True):
        logger.debug(f"[DocumentoForm] Tentando salvar o documento {self.instance.nome}. Campos: {self.cleaned_data}")
        return super().save(commit=commit)

# Formulário para criar uma nova revisão de documento
class NovaRevisaoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['nome', 'revisao', 'aprovador1', 'aprovador2', 'documento']
        labels = {
            'nome': 'Nome do Documento',
            'revisao': 'Nova Revisão',
            'aprovador1': 'Aprovador 1',
            'aprovador2': 'Aprovador 2',
            'documento': 'Anexar Novo Documento',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
            'revisao': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador1': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador2': forms.Select(attrs={'class': 'form-control select2'}),
            'documento': forms.FileInput(attrs={'class': 'form-control-file'}),
        }

    def __init__(self, *args, **kwargs):
        documento_atual = kwargs.pop('documento_atual', None)
        super(NovaRevisaoForm, self).__init__(*args, **kwargs)

        if documento_atual:
            # Define o campo 'nome' como somente leitura e inicializa as revisões
            self.fields['nome'].initial = documento_atual.nome
            self._set_revisoes_disponiveis(documento_atual.revisao)

        self._set_aprovadores()

    def _set_revisoes_disponiveis(self, revisao_atual):
        """Define as revisões disponíveis no formulário com base na revisão atual."""
        self.fields['revisao'].choices = [(i, f"{i:02d}") for i in range(revisao_atual + 1, 101)]

    def _set_aprovadores(self):
        """Define a queryset dos aprovadores baseada nas permissões de aprovação."""
        content_type = ContentType.objects.get_for_model(Documento)
        permission = Permission.objects.get(content_type=content_type, codename='can_approve')
        aprovadores = User.objects.filter(
            Q(user_permissions=permission) | Q(groups__permissions=permission)
        ).distinct()
        self.fields['aprovador1'].queryset = aprovadores
        self.fields['aprovador2'].queryset = aprovadores
