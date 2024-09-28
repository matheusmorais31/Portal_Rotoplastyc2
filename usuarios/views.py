from django.shortcuts import render, redirect, get_object_or_404
from .forms import UsuarioCadastroForm, UsuarioChangeForm
from .models import Usuario
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm  # Importando o AuthenticationForm
from django.contrib import messages
from ldap3 import Server, Connection, ALL

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

# Função para buscar usuários no Active Directory
def buscar_usuarios_ad(request):
    if request.method == "POST":
        nome_usuario = request.POST.get("nome_usuario", "")
        
        # Configurações de conexão com o servidor LDAP
        ldap_server = "ldap://tcc1.net"  # IP ou URL do seu servidor AD
        ldap_user = "CN=Administrator,CN=Users,DC=tcc1,DC=net"  # DN do usuário administrador do AD
        ldap_password = "Admin@ti"  # Senha do administrador do AD

        # Conectando ao servidor LDAP
        server = Server(ldap_server, get_info=ALL)
        conn = Connection(server, user=ldap_user, password=ldap_password, auto_bind=True)

        # Fazendo a busca no AD
        search_base = "CN=Users,DC=tcc1,DC=net"
        search_filter = f"(sAMAccountName={nome_usuario})"  # Filtrando por nome de usuário
        conn.search(search_base, search_filter, attributes=['cn', 'givenName', 'sn', 'mail'])

        # Verifica se o usuário foi encontrado
        if conn.entries:
            for entry in conn.entries:
                messages.success(request, f"Usuário encontrado: {entry.cn}")
        else:
            messages.error(request, "Usuário não encontrado no AD.")
        
        conn.unbind()  # Fechar a conexão
    
    return render(request, 'usuarios/buscar_usuarios_ad.html')
