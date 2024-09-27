from django.shortcuts import render, redirect, get_object_or_404
from .forms import UsuarioCadastroForm, UsuarioChangeForm
from .models import Usuario
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm  # Importando o AuthenticationForm
from django.contrib import messages

def registrar_usuario(request):
    if request.method == 'POST':
        form = UsuarioCadastroForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Faz login automaticamente após o cadastro
            return redirect('home')  # Redireciona para a página inicial ou outra página
    else:
        form = UsuarioCadastroForm()

    return render(request, 'usuarios/registrar.html', {'form': form})

def login_usuario(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
                return redirect('home')
            else:
                messages.error(request, 'Usuário ou senha incorretos.')
        else:
            messages.error(request, 'Usuário ou senha incorretos.')
    else:
        form = AuthenticationForm()

    return render(request, 'usuarios/login.html', {'form': form})

# Função para listar os usuários
def lista_usuarios(request):
    usuarios = Usuario.objects.all()  # Lista todos os usuários
    return render(request, 'usuarios/lista_usuarios.html', {'usuarios': usuarios})

# Função para editar o usuário (incluindo edição de senha)
def editar_usuario(request, usuario_id):
    usuario = get_object_or_404(Usuario, id=usuario_id)
    
    if request.method == 'POST':
        form = UsuarioChangeForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()  # O método save() já lida com a atualização da senha
            return redirect('lista_usuarios')  # Redireciona para a lista de usuários após salvar
    else:
        form = UsuarioChangeForm(instance=usuario)  # Preenche o formulário com os dados do usuário
    
    return render(request, 'usuarios/editar_usuario.html', {'form': form})

# Função para renderizar a página home
def home(request):
    return render(request, 'home.html')
