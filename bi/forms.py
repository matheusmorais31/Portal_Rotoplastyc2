from django import forms
from .models import BIReport
from django.contrib.auth.models import Group

class BIReportForm(forms.ModelForm):
    class Meta:
        model = BIReport
        fields = [
            'title',
            'embed_code',
            'report_id',
            'group_id',
            'allowed_users',
            'allowed_groups',
            'all_users',  # Novo campo adicionado
        ]
        labels = {
            'title': 'Título',
            'embed_code': 'Código Embed',
            'report_id': 'ID do Relatório',
            'group_id': 'ID do Grupo',
            'allowed_users': 'Usuários Permitidos',
            'allowed_groups': 'Grupos Permitidos',
            'all_users': 'Permitir a todos os usuários',  # Novo label
        }
        widgets = {
            'allowed_users': forms.CheckboxSelectMultiple(),
            'allowed_groups': forms.CheckboxSelectMultiple(),
            'embed_code': forms.Textarea(attrs={'rows': 4}),
            'all_users': forms.CheckboxInput(),
        }

class BIReportEditForm(forms.ModelForm):
    class Meta:
        model = BIReport
        fields = [
            'title',
            'embed_code',
            'allowed_users',
            'allowed_groups',
            'all_users',  # Novo campo adicionado
        ]
        labels = {
            'title': 'Título',
            'embed_code': 'Código Embed',
            'allowed_users': 'Usuários Permitidos',
            'allowed_groups': 'Grupos Permitidos',
            'all_users': 'Permitir a todos os usuários',  # Novo label
        }
        widgets = {
            'allowed_users': forms.CheckboxSelectMultiple(),
            'allowed_groups': forms.CheckboxSelectMultiple(),
            'embed_code': forms.Textarea(attrs={'rows': 4}),
            'all_users': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super(BIReportEditForm, self).__init__(*args, **kwargs)
        # Tornar os campos 'title' e 'embed_code' desabilitados
        self.fields['title'].disabled = True
        self.fields['embed_code'].disabled = True
