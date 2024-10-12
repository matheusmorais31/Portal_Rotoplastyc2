# documentos/forms.py

from django import forms
from .models import Categoria, Documento
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db.models import Q

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
            'revisao': forms.Select(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-control'}),
            'aprovador1': forms.Select(attrs={'class': 'form-control'}),
            'aprovador2': forms.Select(attrs={'class': 'form-control'}),
            'documento': forms.FileInput(attrs={'class': 'form-control-file'}),
        }

    def __init__(self, *args, **kwargs):
        super(DocumentoForm, self).__init__(*args, **kwargs)
        # Obter a permissão 'can_approve' do app 'documentos'
        permission = Permission.objects.get(codename='can_approve', content_type__app_label='documentos')
        # Filtrar usuários que possuem a permissão diretamente ou via grupos
        aprovadores = User.objects.filter(
            Q(user_permissions=permission) | Q(groups__permissions=permission)
        ).distinct()
        self.fields['aprovador1'].queryset = aprovadores
        self.fields['aprovador2'].queryset = aprovadores