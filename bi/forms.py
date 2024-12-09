from django import forms
from .models import BIReport

class BIReportForm(forms.ModelForm):
    class Meta:
        model = BIReport
        fields = ['title', 'embed_code', 'report_id', 'group_id', 'allowed_users']
        labels = {
            'title': 'Título',
            'embed_code': 'Código Embed',
            'report_id': 'ID do Relatório',
            'group_id': 'ID do Grupo',
            'allowed_users': 'Usuários Permitidos',
        }
        widgets = {
            'allowed_users': forms.CheckboxSelectMultiple(),
            'embed_code': forms.Textarea(attrs={'rows': 4}),
        }

class BIReportEditForm(forms.ModelForm):
    class Meta:
        model = BIReport
        fields = ['title', 'embed_code', 'allowed_users']
        labels = {
            'title': 'Título',
            'embed_code': 'Código Embed',
            'allowed_users': 'Usuários Permitidos',
        }
        widgets = {
            'allowed_users': forms.CheckboxSelectMultiple(),
            'embed_code': forms.Textarea(attrs={'rows': 4}),

        }