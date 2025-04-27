from django import forms
from django.contrib.auth import get_user_model # Para buscar usuários

User = get_user_model()

class ApiUsageFilterForm(forms.Form): # Renomeado para refletir melhor o propósito
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Data Inicial"
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}),
        label="Data Final"
    )
    # Filtro por Usuário (será preenchido na view se for staff)
    user = forms.ModelChoiceField(
        queryset=User.objects.all().order_by('username'),
        required=False,
        label="Usuário",
        empty_label="-- Todos os Usuários --" # Rótulo para a opção vazia/todos
    )
    # Filtro por Modelo (choices serão preenchidos na view)
    model_name = forms.ChoiceField(
        required=False,
        label="Modelo API",
        choices=[('', '-- Todos os Modelos --')] # Default com opção "Todos"
    )