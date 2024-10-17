# documentos/forms.py

from django import forms
from .models import Categoria, Documento
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q
<<<<<<< HEAD
from django.contrib.contenttypes.models import ContentType
=======
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22

User = get_user_model()

class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome']
        labels = {
            'nome': 'Nome da Categoria',
        }
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        }

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
<<<<<<< HEAD
            'revisao': forms.Select(attrs={'class': 'form-control select2'}),
            'categoria': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador1': forms.Select(attrs={'class': 'form-control select2'}),
            'aprovador2': forms.Select(attrs={'class': 'form-control select2'}),
=======
            'revisao': forms.Select(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'aprovador1': forms.Select(attrs={'class': 'form-control'}),
            'aprovador2': forms.Select(attrs={'class': 'form-control'}),
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
            'documento': forms.FileInput(attrs={'class': 'form-control-file'}),
        }

    def __init__(self, *args, **kwargs):
        super(DocumentoForm, self).__init__(*args, **kwargs)
<<<<<<< HEAD
        content_type = ContentType.objects.get_for_model(Documento)
        permission = Permission.objects.get(content_type=content_type, codename='can_approve')
=======
        # Obter a permissão 'can_approve' do app 'documentos'
        permission = Permission.objects.get(codename='can_approve', content_type__app_label='documentos')
        # Filtrar usuários que possuem a permissão diretamente ou via grupos
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
        aprovadores = User.objects.filter(
            Q(user_permissions=permission) | Q(groups__permissions=permission)
        ).distinct()
        self.fields['aprovador1'].queryset = aprovadores
<<<<<<< HEAD
        self.fields['aprovador2'].queryset = aprovadores

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

        # Campo nome é somente leitura
        self.fields['nome'].initial = documento_atual.nome if documento_atual else ''

        # Filtra as revisões maiores que a atual
        revisao_atual = documento_atual.revisao if documento_atual else 0
        self.fields['revisao'].choices = [(i, f"{i:02d}") for i in range(revisao_atual + 1, 101)]

        # Aprovadores
        content_type = ContentType.objects.get_for_model(Documento)
        permission = Permission.objects.get(content_type=content_type, codename='can_approve')
        aprovadores = User.objects.filter(
            Q(user_permissions=permission) | Q(groups__permissions=permission)
        ).distinct()
        self.fields['aprovador1'].queryset = aprovadores
        self.fields['aprovador2'].queryset = aprovadores
=======
        self.fields['aprovador2'].queryset = aprovadores
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
