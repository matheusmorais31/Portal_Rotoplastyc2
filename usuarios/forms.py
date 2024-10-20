# usuarios/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UserChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Usuario, Grupo
from django.contrib.auth.models import Permission

# Formulário de Cadastro de Usuário
class UsuarioCadastroForm(UserCreationForm):
    gerente = forms.BooleanField(
        required=False,
        label="Gerente"
    )

    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'username', 'email', 'password1', 'password2', 'gerente']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_ad_user = False  # Define que o usuário é local
        user.gerente = self.cleaned_data.get('gerente')  # Atribui o valor do checkbox ao modelo
        user.backend = 'usuarios.auth_backends.ActiveDirectoryBackend'  # Define o backend para o usuário

        if commit:
            user.save()  # Salva o usuário no banco de dados
        return user

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
    gerente = forms.BooleanField(
        required=False,
        label="Gerente"
    )

    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'username', 'email', 'ativo', 'gerente']

    def __init__(self, *args, **kwargs):
        super(UsuarioChangeForm, self).__init__(*args, **kwargs)
        user = self.instance
        self.fields.pop('password', None)
        if user.is_ad_user:
            self.fields.pop('password1', None)
            self.fields.pop('password2', None)

    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        if password1:
            try:
                validate_password(password1)
            except ValidationError as e:
                self.add_error('password1', e)
        return password1

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password1 != password2:
            self.add_error('password2', "As senhas não correspondem.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)
        user.gerente = self.cleaned_data.get('gerente')
        if commit:
            user.save()
        return user

# Formulário para gerenciar permissões de usuário
class UsuarioPermissaoForm(forms.ModelForm):
    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Permissões"
    )

    class Meta:
        model = Usuario
        fields = ['user_permissions']

# Formulário de Grupo
class GrupoForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Permissões"
    )

    class Meta:
        model = Grupo
        fields = ['nome', 'participantes', 'permissions']
        widgets = {
            'participantes': forms.CheckboxSelectMultiple(),
        }

class ProfileForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ['first_name', 'last_name', 'email', 'profile_photo']  # Inclua os campos desejados
