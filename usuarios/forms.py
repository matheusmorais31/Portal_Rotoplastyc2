from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, UserChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Usuario


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
        label="Gerente"  # Etiqueta do campo no formulário
    )

    class Meta:
        model = Usuario  # Use o modelo personalizado de usuário
        fields = ['first_name', 'last_name', 'username', 'email', 'ativo', 'gerente']  # Campos que podem ser editados

    def __init__(self, *args, **kwargs):
        super(UsuarioChangeForm, self).__init__(*args, **kwargs)
        user = self.instance
        # Remove o campo 'password' do formulário para todos os usuários
        self.fields.pop('password', None)
        if user.is_ad_user:
            # Se o usuário é do AD, não permitimos a alteração da senha
            self.fields.pop('password1', None)
            self.fields.pop('password2', None)

    def clean_password1(self):
        # Este método só é chamado se 'password1' estiver presente nos campos
        password1 = self.cleaned_data.get('password1')

        if password1:
            try:
                # Valida a senha usando as validações padrão do Django
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
        if password1 and password1 != password2:
            self.add_error('password2', "As senhas não correspondem.")  # Adiciona erro específico ao campo 'password2'
        
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        password = self.cleaned_data.get('password1')

        # Se o campo de senha foi preenchido, atualiza a senha do usuário
        if password:
            user.set_password(password)  # Atualiza a senha apenas se uma nova senha foi fornecida

        # Atribuir o valor do checkbox ao campo do modelo
        user.gerente = self.cleaned_data.get('gerente')

        if commit:
            user.save()

        return user
