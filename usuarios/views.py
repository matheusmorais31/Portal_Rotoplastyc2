import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.views import LogoutView
from django.contrib.auth.models import Permission
from django.utils.translation import gettext as _
from django.urls import reverse_lazy
from ldap3 import Server, Connection, ALL
from collections import defaultdict
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from .forms import UsuarioCadastroForm, UsuarioChangeForm, GrupoForm, UsuarioPermissaoForm, ProfileForm
from .models import Usuario, Grupo



# Configuração do logger
logger = logging.getLogger(__name__)

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
                # Não é mais necessário sincronizar permissões aqui
                login(request, user)
                logger.info(f"Usuário {username} autenticado com sucesso.")
                return redirect('home')
            else:
                logger.warning(f"Falha na autenticação do usuário {username}.")
                messages.error(request, 'Usuário ou senha incorretos.')
        else:
            logger.error(f"Erros no formulário de login: {form.errors}")
            messages.error(request, 'Formulário inválido. Verifique os campos.')

        return render(request, 'usuarios/login.html', {'form': form})
    else:
        form = AuthenticationForm(request)
        return render(request, 'usuarios/login.html', {'form': form})

    
# Função para registrar usuários locais no banco de dados
@login_required
@permission_required('usuarios.can_add_user', raise_exception=True)
def registrar_usuario(request):
    if request.method == 'POST':
        form = UsuarioCadastroForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_ad_user = False  # Usuário local
            user.save()
            login(request, user)  # Faz login automaticamente após o cadastro
            return redirect('usuarios:lista_usuarios')  # Redireciona com o namespace correto
    else:
        form = UsuarioCadastroForm()
    return render(request, 'usuarios/registrar.html', {'form': form})

# Função para listar os usuários
@login_required
@permission_required('usuarios.list_user', raise_exception=True)
def lista_usuarios(request):
    usuarios = Usuario.objects.all()
    return render(request, 'usuarios/lista_usuarios.html', {'usuarios': usuarios})

# Função para editar o usuário
@login_required
@permission_required('usuarios.can_edit_user', raise_exception=True)
def editar_usuario(request, usuario_id):
    usuario = get_object_or_404(Usuario, id=usuario_id)
    if request.method == 'POST':
        form = UsuarioChangeForm(request.POST, instance=usuario)
        if form.is_valid():
            form.save()
            return redirect('usuarios:lista_usuarios')
    else:
        form = UsuarioChangeForm(instance=usuario)
    return render(request, 'usuarios/editar_usuario.html', {'form': form})

# Função para buscar e importar usuários do Active Directory
@login_required
@permission_required('usuarios.can_import_user', raise_exception=True)
def buscar_usuarios_ad(request):
    usuarios_ad = []
    conn = None
    if request.method == "POST":
        nome_usuario = request.POST.get("nome_usuario", "")
        ldap_server = "ldap://rotoplastyc.net"
        ldap_user = "CN=Administrador,CN=Users,DC=rotoplastyc,DC=net"
        ldap_password = "56dgqipcDuq78fRNhEkEkxvJGoeKa5hA"

        try:
            logger.info(f"Tentando conectar ao servidor LDAP: {ldap_server}")
            server = Server(ldap_server, get_info=ALL)
            conn = Connection(server, user=ldap_user, password=ldap_password, auto_bind=True)
            logger.info("Conexão ao LDAP estabelecida com sucesso.")

            search_base = "OU=Usuarios,OU=Rotoplastyc,DC=rotoplastyc,DC=net"
            search_filter = f"(sAMAccountName=*{nome_usuario}*)"
            conn.search(search_base, search_filter, attributes=['sAMAccountName', 'givenName', 'sn', 'mail'])

            if conn.entries:
                for entry in conn.entries:
                    usuario = {
                        'sAMAccountName': entry.sAMAccountName.value,
                        'givenName': entry.givenName.value,
                        'sn': entry.sn.value,
                        'mail': entry.mail.value if 'mail' in entry else ''
                    }
                    usuarios_ad.append(usuario)
            else:
                logger.warning("Nenhum usuário encontrado no AD.")
                messages.error(request, "Nenhum usuário encontrado no AD.")
        except Exception as e:
            logger.error(f"Erro ao buscar usuários no AD: {str(e)}")
            messages.error(request, "Erro ao conectar ao Active Directory.")
        finally:
            if conn:
                conn.unbind()
            logger.info("Conexão com o LDAP encerrada.")

    return render(request, 'usuarios/buscar_usuarios_ad.html', {'usuarios_ad': usuarios_ad})

# Função para importar usuários do AD para o Django
@login_required
def importar_usuarios_ad(request):
    conn = None
    if request.method == "POST":
        usuarios_selecionados = request.POST.getlist("usuarios")
        ldap_server = "ldap://rotoplastyc.net"
        ldap_user = "CN=Administrador,CN=Users,DC=rotoplastyc,DC=net"
        ldap_password = "56dgqipcDuq78fRNhEkEkxvJGoeKa5hA"

        try:
            logger.info(f"Tentando conectar ao servidor LDAP: {ldap_server}")
            server = Server(ldap_server, get_info=ALL)
            conn = Connection(server, user=ldap_user, password=ldap_password, auto_bind=True)
            logger.info("Conexão ao LDAP estabelecida com sucesso.")

            for username in usuarios_selecionados:
                logger.info(f"Tentando importar usuário: {username}")

                if Usuario.objects.filter(username=username).exists():
                    logger.warning(f"O usuário {username} já existe no sistema.")
                    messages.warning(request, f"O usuário {username} já existe no sistema e não foi importado.")
                    continue

                search_filter = f"(sAMAccountName={username})"
                search_base = "OU=Usuarios,OU=Rotoplastyc,DC=rotoplastyc,DC=net"
                conn.search(search_base, search_filter, attributes=['sAMAccountName', 'givenName', 'sn', 'mail'])

                if conn.entries:
                    entry = conn.entries[0]
                    user = Usuario(
                        username=entry.sAMAccountName.value,
                        first_name=entry.givenName.value,
                        last_name=entry.sn.value,
                        email=entry.mail.value if entry.mail else None,
                        is_ad_user=True,
                        ativo=True
                    )
                    user.set_unusable_password()
                    user.save()
                    messages.success(request, f"Usuário {username} importado com sucesso.")
                else:
                    messages.error(request, f"Usuário {username} não encontrado no AD.")

        except Exception as e:
            logger.error(f"Erro ao importar usuários do AD: {str(e)}")
            messages.error(request, "Erro ao importar usuários do Active Directory.")
        finally:
            if conn:
                conn.unbind()
            logger.info("Conexão com o LDAP encerrada.")

    return redirect('usuarios:buscar_usuarios_ad')

# Funções relacionadas a grupos
@login_required
@permission_required('usuarios.can_view_list_group', raise_exception=True)
def lista_grupos(request):
    grupos = Grupo.objects.all()
    return render(request, 'usuarios/lista_grupos.html', {'grupos': grupos})

@login_required
@permission_required('usuarios.can_add_group', raise_exception=True)
def cadastrar_grupo(request):
    if request.method == 'POST':
        nome_grupo = request.POST.get('nome')
        participantes_ids = request.POST.getlist('participantes')
        
        # Log dos dados recebidos
        logger.debug(f"Nome do Grupo: {nome_grupo}")
        logger.debug(f"Participantes IDs: {participantes_ids}")

        if not nome_grupo:
            messages.error(request, "O nome do grupo é obrigatório.")
            return render(request, 'usuarios/cadastrar_grupo.html')

        grupo = Grupo(nome=nome_grupo)
        grupo.save()

        for usuario_id in participantes_ids:
            try:
                usuario = Usuario.objects.get(id=usuario_id)
                grupo.participantes.add(usuario)
            except Usuario.DoesNotExist:
                messages.error(request, f"Usuário com ID {usuario_id} não existe.")

        grupo.save()
        messages.success(request, "Grupo criado com sucesso!")
        return redirect('usuarios:lista_grupos')

    usuarios = Usuario.objects.all()
    return render(request, 'usuarios/cadastrar_grupo.html', {'usuarios': usuarios})


@login_required
@permission_required('usuarios.can_edit_group', raise_exception=True)
def editar_grupo(request, grupo_id):
    grupo = get_object_or_404(Grupo, id=grupo_id)
    if request.method == 'POST':
        nome_grupo = request.POST.get('nome_grupo')
        participantes_ids = request.POST.getlist('participantes')

        if nome_grupo:
            grupo.nome = nome_grupo
            grupo.participantes.clear()  # Remove todos os participantes antigos
            for usuario_id in participantes_ids:
                try:
                    usuario = Usuario.objects.get(id=usuario_id)
                    grupo.participantes.add(usuario)
                except Usuario.DoesNotExist:
                    messages.error(request, f"Usuário com ID {usuario_id} não existe.")
            grupo.save()
            messages.success(request, "Grupo atualizado com sucesso!")
            return redirect('usuarios:lista_grupos')
        else:
            messages.error(request, "O nome do grupo é obrigatório.")

    usuarios = Usuario.objects.all()
    return render(request, 'usuarios/editar_grupo.html', {'grupo': grupo, 'usuarios': usuarios})

@login_required
@permission_required('usuarios.can_delete_group', raise_exception=True)
def excluir_grupo(request, grupo_id):
    grupo = get_object_or_404(Grupo, id=grupo_id)
    if request.method == 'POST':
        grupo.delete()
        messages.success(request, "Grupo excluído com sucesso!")
        return redirect('usuarios:lista_grupos')
    return render(request, 'usuarios/excluir_grupo.html', {'grupo': grupo})

# Função para buscar participantes (usuários) via AJAX
@login_required
def buscar_participantes(request):
    query = request.GET.get('q', '')
    if query:
        usuarios = Usuario.objects.filter(username__icontains=query)
        resultados = [{'id': usuario.id, 'username': usuario.username} for usuario in usuarios]
    else:
        resultados = []
    return JsonResponse(resultados, safe=False)

# Função para sugerir usuários ou grupos conforme a busca
@login_required
def sugestoes(request):
    query = request.GET.get('q', '')
    sugestoes = []

    if query:
        usuarios = Usuario.objects.filter(username__icontains=query)[:5]
        for usuario in usuarios:
            sugestoes.append({'id': usuario.id, 'nome': usuario.username, 'tipo': 'Usuário'})

        grupos = Grupo.objects.filter(nome__icontains=query)[:5]
        for grupo in grupos:
            sugestoes.append({'id': grupo.id, 'nome': grupo.nome, 'tipo': 'Grupo'})

    return JsonResponse(sugestoes, safe=False)
# Função para liberar permissões
@login_required
@permission_required('usuarios.change_permission', raise_exception=True)
def liberar_permissoes(request):
    if request.method == 'GET':
        # Verifica se a requisição é AJAX
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            usuario_grupo_id = request.GET.get('id')
            tipo = request.GET.get('tipo')
            app_label = request.GET.get('app_label')  # Parâmetro para filtrar por app

            if usuario_grupo_id and tipo:
                ordered_permissions = []
                if app_label:
                    # Obtém todos os modelos do aplicativo especificado
                    app_models = apps.get_app_config(app_label).get_models()

                    for model in app_models:
                        content_type = ContentType.objects.get_for_model(model)

                        # Coleta permissões personalizadas na ordem definida nos modelos
                        custom_permissions = getattr(model._meta, 'permissions', [])
                        for codename, name in custom_permissions:
                            try:
                                permission = Permission.objects.get(content_type=content_type, codename=codename)
                                ordered_permissions.append(permission)
                            except Permission.DoesNotExist:
                                pass

                        # Verifica se as permissões padrão estão habilitadas
                        default_permissions = getattr(model._meta, 'default_permissions', ('add', 'change', 'delete', 'view'))
                        for perm in default_permissions:
                            codename = f"{perm}_{model._meta.model_name}"
                            try:
                                permission = Permission.objects.get(content_type=content_type, codename=codename)
                                ordered_permissions.append(permission)
                            except Permission.DoesNotExist:
                                pass

                # Constrói a lista de permissões ordenadas
                permissoes_list = [
                    {'id': p.id, 'name': p.name, 'app_label': p.content_type.app_label}
                    for p in ordered_permissions
                ]

                if tipo == 'Usuário':
                    usuario = get_object_or_404(Usuario, id=usuario_grupo_id)
                    permissoes_selecionadas = usuario.user_permissions.filter(content_type__app_label=app_label).values_list('id', flat=True)
                elif tipo == 'Grupo':
                    grupo = get_object_or_404(Grupo, id=usuario_grupo_id)
                    permissoes_selecionadas = grupo.permissions.filter(content_type__app_label=app_label).values_list('id', flat=True)
                else:
                    permissoes_selecionadas = []

                return JsonResponse({
                    'permissoes': permissoes_list,
                    'permissoes_selecionadas': list(permissoes_selecionadas)
                })
            else:
                # Retorna a lista de apps únicos e ordenados
                apps_permissions = Permission.objects.order_by('content_type__app_label').values_list('content_type__app_label', flat=True).distinct()
                apps_list = list(apps_permissions)
                return JsonResponse({
                    'apps': apps_list
                })

        else:
            # Requisição normal: renderiza o template
            return render(request, 'usuarios/liberar_permissoes.html')

    elif request.method == 'POST':
        usuario_grupo_id = request.POST.get('usuario_grupo_id')
        tipo = request.POST.get('tipo')
        permissoes_ids = request.POST.getlist('permissoes')
        app_label = request.POST.get('app_label')  # Campo para identificar o app

        if usuario_grupo_id and tipo and app_label:
            permissoes_submetidas = set(map(int, permissoes_ids))
            permissoes_app = Permission.objects.filter(content_type__app_label=app_label)
            permissoes_app_ids = set(permissoes_app.values_list('id', flat=True))

            if tipo == 'Usuário':
                usuario = get_object_or_404(Usuario, id=usuario_grupo_id)
                permissoes_atual = set(usuario.user_permissions.filter(content_type__app_label=app_label).values_list('id', flat=True))
                permissoes_a_adicionar = permissoes_submetidas - permissoes_atual
                permissoes_a_remover = permissoes_atual - permissoes_submetidas
                usuario.user_permissions.add(*Permission.objects.filter(id__in=permissoes_a_adicionar))
                usuario.user_permissions.remove(*Permission.objects.filter(id__in=permissoes_a_remover))
                messages.success(request, f"Permissões atualizadas para o usuário {usuario.username}")
            elif tipo == 'Grupo':
                grupo = get_object_or_404(Grupo, id=usuario_grupo_id)
                permissoes_atual = set(grupo.permissions.filter(content_type__app_label=app_label).values_list('id', flat=True))
                permissoes_a_adicionar = permissoes_submetidas - permissoes_atual
                permissoes_a_remover = permissoes_atual - permissoes_submetidas
                grupo.permissions.add(*Permission.objects.filter(id__in=permissoes_a_adicionar))
                grupo.permissions.remove(*Permission.objects.filter(id__in=permissoes_a_remover))
                messages.success(request, f"Permissões atualizadas para o grupo {grupo.nome}")
            else:
                messages.error(request, "Tipo inválido.")
                return redirect('usuarios:liberar_permissoes')

            return redirect('usuarios:liberar_permissoes')
        else:
            messages.error(request, "Por favor, selecione um usuário ou grupo, um aplicativo e as permissões.")
            return redirect('usuarios:liberar_permissoes')
    else:
        return HttpResponseNotAllowed(['GET', 'POST'])
    
  
def get_permission_display_name(permission):
    codename = permission.codename
    model = permission.content_type.model_class()
    model_name = model._meta.verbose_name

    if codename.startswith('add_'):
        action = _('Pode adicionar')
    elif codename.startswith('change_'):
        action = _('Pode alterar')
    elif codename.startswith('delete_'):
        action = _('Pode excluir')
    elif codename.startswith('view_'):
        action = _('Pode visualizar')
    else:
        return _(permission.name)

    return f'{action} {model_name}'

# Página de perfil
class ProfileView(TemplateView):
    template_name = 'usuarios/profile.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user'] = self.request.user
        return context

class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('usuarios:login_usuario')

# Função para listar permissões
@login_required
@permission_required('usuarios.change_permission', raise_exception=True)
def lista_permissoes(request):
    permissoes = Permission.objects.all()
    return render(request, 'usuarios/lista_permissoes.html', {'permissoes': permissoes})

# Função para editar o perfil do usuário
@login_required
def editar_perfil(request):
    usuario = request.user
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=usuario)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil atualizado com sucesso!")
            return redirect('usuarios:editar_perfil')
    else:
        form = ProfileForm(instance=usuario)
    return render(request, 'usuarios/editar_perfil.html', {'form': form})

# Função de erro 403 personalizada
def error_403_view(request, exception):
    return render(request, 'usuarios/403.html', status=403)
