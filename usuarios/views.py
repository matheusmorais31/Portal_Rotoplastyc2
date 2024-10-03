# usuarios/views.py

import logging
from django.shortcuts import render, redirect, get_object_or_404
from .forms import UsuarioCadastroForm, UsuarioChangeForm
from .models import Usuario
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from ldap3 import Server, Connection, ALL

# Configuração do logger
logger = logging.getLogger(__name__)

# Registrar usuários locais no banco de dados
def registrar_usuario(request):
    if request.method == 'POST':
        form = UsuarioCadastroForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_ad_user = False  # Usuário local
            user.save()
            login(request, user)  # Faz login automaticamente após o cadastro
            return redirect('lista_usuarios')  # Redireciona para a página de lista de usuários
    else:
        form = UsuarioCadastroForm()

    return render(request, 'usuarios/registrar.html', {'form': form})

# Função de login
def login_usuario(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')

            logger.info(f"Tentando autenticar o usuário: {username}")
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)
                logger.info(f"Usuário {username} autenticado com sucesso.")
                return redirect('home')
            else:
                logger.warning(f"Falha na autenticação do usuário {username}.")
                messages.error(request, 'Usuário ou senha incorretos.')
        else:
            logger.error(f"Erros no formulário de login: {form.errors}")
            messages.error(request, 'Formulário inválido. Verifique os campos.')

        # Re-renderizar o formulário com erros e token CSRF
        return render(request, 'usuarios/login.html', {'form': form})
    else:
        # Instanciar o formulário com o objeto request
        form = AuthenticationForm(request)
        return render(request, 'usuarios/login.html', {'form': form})

# Função para listar os usuários
def lista_usuarios(request):
    usuarios = Usuario.objects.all()  # Lista todos os usuários
    return render(request, 'usuarios/lista_usuarios.html', {'usuarios': usuarios})

# Função para editar o usuário (sem opção de alterar senha para AD)
def editar_usuario(request, usuario_id):
    usuario = get_object_or_404(Usuario, id=usuario_id)

    if request.method == 'POST':
        form = UsuarioChangeForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()  # O método save() já lida com a atualização dos campos
            return redirect('lista_usuarios')  # Redireciona para a lista de usuários após salvar
    else:
        form = UsuarioChangeForm(instance=usuario)  # Preenche o formulário com os dados do usuário

    return render(request, 'usuarios/editar_usuario.html', {'form': form})

# Função para renderizar a página home
def home(request):
    return render(request, 'home.html')

# Função para buscar e importar usuários do Active Directory
def buscar_usuarios_ad(request):
    usuarios_ad = []
    if request.method == "POST":
        nome_usuario = request.POST.get("nome_usuario", "")
        
        # Configurações de conexão com o servidor LDAP
        ldap_server = "ldap://seu_servidor_ldap"
        ldap_user = "CN=SeuUsuario,CN=Users,DC=dominio,DC=com"
        ldap_password = "SuaSenha"

        try:
            logger.info(f"Tentando conectar ao servidor LDAP: {ldap_server}")
            server = Server(ldap_server, get_info=ALL)
            conn = Connection(server, user=ldap_user, password=ldap_password, auto_bind=True)
            logger.info("Conexão ao LDAP estabelecida com sucesso.")

            # Fazendo a busca no AD com o operador de substring "*"
            search_base = "CN=Users,DC=dominio,DC=com"
            search_filter = f"(sAMAccountName=*{nome_usuario}*)"  # Filtrando por nome de usuário usando curinga "*"

            # Atributos que queremos buscar no AD
            conn.search(search_base, search_filter, attributes=['sAMAccountName', 'givenName', 'sn', 'mail'])

            # Verifica se algum usuário foi encontrado
            if conn.entries:
                for entry in conn.entries:
                    usuario = {
                        'sAMAccountName': entry.sAMAccountName.value,
                        'givenName': entry.givenName.value,
                        'sn': entry.sn.value,
                        'mail': entry.mail.value if 'mail' in entry else ''  # Verifica se o email está disponível
                    }
                    usuarios_ad.append(usuario)
            else:
                logger.warning("Nenhum usuário encontrado no AD.")
                messages.error(request, "Nenhum usuário encontrado no AD.")
        except Exception as e:
            logger.error(f"Erro ao buscar usuários no AD: {str(e)}")
            messages.error(request, "Erro ao conectar ao Active Directory.")
        finally:
            conn.unbind()  # Fechar a conexão
            logger.info("Conexão com o LDAP encerrada.")

    return render(request, 'usuarios/buscar_usuarios_ad.html', {'usuarios_ad': usuarios_ad})

# Função para importar usuários do AD para o Django
def importar_usuarios_ad(request):
    if request.method == "POST":
        usuarios_selecionados = request.POST.getlist("usuarios")

        # Configurações de conexão com o servidor LDAP
        ldap_server = "ldap://seu_servidor_ldap"
        ldap_user = "CN=SeuUsuario,CN=Users,DC=dominio,DC=com"
        ldap_password = "SuaSenha"

        try:
            logger.info(f"Tentando conectar ao servidor LDAP: {ldap_server}")
            server = Server(ldap_server, get_info=ALL)
            conn = Connection(server, user=ldap_user, password=ldap_password, auto_bind=True)
            logger.info("Conexão ao LDAP estabelecida com sucesso.")

            for username in usuarios_selecionados:
                logger.info(f"Tentando importar usuário: {username}")

                # Verificar se o usuário já existe no sistema local
                if Usuario.objects.filter(username=username).exists():
                    logger.warning(f"O usuário {username} já existe no sistema.")
                    messages.warning(request, f"O usuário {username} já existe no sistema e não foi importado.")
                    continue  # Pular para o próximo usuário

                # Busca no AD
                search_filter = f"(sAMAccountName={username})"
                search_base = "CN=Users,DC=dominio,DC=com"
                logger.info(f"Buscando no AD com filtro: {search_filter}")

                conn.search(search_base, search_filter, attributes=['sAMAccountName', 'givenName', 'sn', 'mail'])
                logger.info(f"Busca no AD realizada. Resultados encontrados: {len(conn.entries)}")

                if conn.entries:
                    entry = conn.entries[0]
                    logger.info(f"Usuário encontrado no AD: {entry.sAMAccountName.value}")
                    user = Usuario(
                        username=entry.sAMAccountName.value,
                        first_name=entry.givenName.value,
                        last_name=entry.sn.value,
                        email=entry.mail.value if entry.mail.value else None,
                        is_ad_user=True,  # Indica que é usuário do AD
                        ativo=True
                    )
                    user.set_unusable_password()  # Define uma senha inutilizável
                    user.save()
                    logger.info(f"Usuário {username} importado com sucesso.")
                    messages.success(request, f"Usuário {username} importado com sucesso.")
                else:
                    logger.warning(f"Usuário {username} não encontrado no AD.")
                    messages.error(request, f"Usuário {username} não encontrado no AD.")

        except Exception as e:
            logger.error(f"Erro ao importar usuários do AD: {str(e)}")
            messages.error(request, "Erro ao importar usuários do Active Directory.")
        finally:
            conn.unbind()  # Fechar a conexão

    return redirect('buscar_usuarios_ad')
