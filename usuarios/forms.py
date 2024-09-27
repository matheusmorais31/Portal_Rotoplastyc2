from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UserChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Usuario

# Formulário de Cadastro de Usuário
class UsuarioCadastroForm(UserCreationForm):
    class Meta:
        model = Usuario  # Use o modelo personalizado de usuário
        fields = ['first_name', 'last_name', 'username', 'email', 'password1', 'password2']  # Campos do formulário

# Formulário de Login de Usuário
class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Nome de Usuário'
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Senha'
    }), label="Senha")

# Formulário para editar o usuário
class UsuarioChangeForm(UserChangeForm):
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nova Senha'
        }),
        label="Nova Senha",
        required=False
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirme a Nova Senha'
        }),
        label="Confirme a Nova Senha",
        required=False
    )

    class Meta:
        model = Usuario  # Use o modelo personalizado de usuário
        fields = ['first_name', 'last_name', 'username', 'email', 'password1', 'password2', 'ativo']  # Campos que podem ser editados

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')

        if password1:
            try:
                # Valida a senha usando as validações padrões do Django
                validate_password(password1)
            except ValidationError as e:
                # Adiciona os erros de validação ao campo `password1`
                self.add_error('password1', e)

        return password1

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        # Se ambos os campos de senha foram preenchidos, verifica se são iguais
        if password1 or password2:
            if password1 != password2:
                self.add_error('password2', "As senhas não correspondem.")  # Adiciona erro específico para o campo 'password2'
        
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password1')
        
        # Se o campo de senha foi preenchido, atualiza a senha do usuário
        if password:
            user.set_password(password)  # Atualiza a senha apenas se uma nova senha foi fornecida
        
        if commit:
            user.save()
        
        return user
