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
from .models import Usuario
from django.contrib.auth.models import Group
from .forms import DuplicarAcessoForm
from django.contrib import admin
from django.contrib.sessions.models import Session
from django.utils.timezone import localtime
from django.utils import timezone






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
                if user.is_active:
                    login(request, user)
                    logger.info(f"Usuário {username} autenticado com sucesso.")
                    return redirect('home')
                else:
                    logger.warning(f"Usuário {username} está inativo e tentou realizar login.")
                    form.add_error(None, 'Sua conta está inativa. Por favor, entre em contato com o administrador.')
            else:
                logger.warning(f"Falha na autenticação do usuário {username}. Tentando verificar status da conta.")
                # Verificação adicional para conta inativa
                User = get_user_model()
                try:
                    user = User.objects.get(username=username)
                    logger.debug(f"Usuário encontrado: {username} | Ativo: {user.is_active}")
                    if not user.is_active:
                        form.add_error(None, 'Sua conta está inativa. Por favor, entre em contato com o administrador.')
                        logger.info(f"Mensagem de conta inativa adicionada para o usuário: {username}")
                    else:
                        form.add_error(None, 'Usuário ou senha incorretos.')
                        logger.info(f"Mensagem genérica de erro adicionada para o usuário: {username}")
                except User.DoesNotExist:
                    form.add_error(None, 'Usuário ou senha incorretos.')
                    logger.debug(f"Usuário {username} não existe no sistema.")

        else:
            logger.error(f"Erros no formulário de login: {form.errors}")
            # Os erros do formulário já estão sendo exibidos no template

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
    groups = Group.objects.all()  # Renomear de 'grupos' para 'groups' no contexto
    return render(request, 'usuarios/lista_grupos.html', {'groups': groups})


@login_required
@permission_required('usuarios.can_add_group', raise_exception=True)
def cadastrar_grupo(request):
    if request.method == 'POST':
        nome_grupo = request.POST.get('nome')
        participantes_ids = request.POST.getlist('participantes')
        
        if not nome_grupo:
            messages.error(request, "O nome do grupo é obrigatório.")
            return render(request, 'usuarios/cadastrar_grupo.html')

        group, created = Group.objects.get_or_create(name=nome_grupo)

        for usuario_id in participantes_ids:
            try:
                usuario = Usuario.objects.get(id=usuario_id)
                group.user_set.add(usuario)
            except Usuario.DoesNotExist:
                messages.error(request, f"Usuário com ID {usuario_id} não existe.")

        messages.success(request, "Grupo criado com sucesso!")
        return redirect('usuarios:lista_grupos')

    usuarios = Usuario.objects.all()
    return render(request, 'usuarios/cadastrar_grupo.html', {'usuarios': usuarios})



@login_required
@permission_required('usuarios.can_edit_group', raise_exception=True)
def editar_grupo(request, grupo_id):
    group = get_object_or_404(Group, id=grupo_id)
    if request.method == 'POST':
        nome_grupo = request.POST.get('nome_grupo')
        participantes_ids = request.POST.getlist('participantes')

        if nome_grupo:
            group.name = nome_grupo
            group.save()
            group.user_set.clear()  # Remove todos os participantes antigos
            for usuario_id in participantes_ids:
                try:
                    usuario = Usuario.objects.get(id=usuario_id)
                    group.user_set.add(usuario)
                except Usuario.DoesNotExist:
                    messages.error(request, f"Usuário com ID {usuario_id} não existe.")
            messages.success(request, "Grupo atualizado com sucesso!")
            return redirect('usuarios:lista_grupos')
        else:
            messages.error(request, "O nome do grupo é obrigatório.")

    usuarios = Usuario.objects.all()
    return render(request, 'usuarios/editar_grupo.html', {'group': group, 'usuarios': usuarios})


@login_required
@permission_required('usuarios.can_delete_group', raise_exception=True)
def excluir_grupo(request, grupo_id):
    group = get_object_or_404(Group, id=grupo_id)
    if request.method == 'POST':
        group.delete()
        messages.success(request, "Grupo excluído com sucesso!")
        return redirect('usuarios:lista_grupos')
    return render(request, 'usuarios/excluir_grupo.html', {'group': group})


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
        # Filtra apenas usuários ativos (considerando 'ativo=True')
        usuarios = Usuario.objects.filter(username__icontains=query, ativo=True)[:5]
        for usuario in usuarios:
            sugestoes.append({
                'id': usuario.id,
                'nome': usuario.username,
                'tipo': 'usuario'  # Alterado para minúsculo
            })

        # Busca por grupos sem filtro de atividade
        grupos = Group.objects.filter(name__icontains=query)[:5]
        for grupo in grupos:
            sugestoes.append({
                'id': grupo.id,
                'nome': grupo.name,
                'tipo': 'grupo'  # Alterado para minúsculo
            })

    return JsonResponse(sugestoes, safe=False)

# Função para liberar permissões
@login_required
@permission_required('usuarios.change_permission', raise_exception=True)
def liberar_permissoes(request):
    if request.method == 'GET':
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            usuario_grupo_id = request.GET.get('id')
            tipo = request.GET.get('tipo')
            app_label = request.GET.get('app_label')

            # Caso para retornar a lista de apps se nenhum ID ou tipo for fornecido
            if not usuario_grupo_id and not tipo and not app_label:
                apps_permissions = Permission.objects.order_by('content_type__app_label').values_list('content_type__app_label', flat=True).distinct()
                apps_list = list(apps_permissions)
                return JsonResponse({'apps': apps_list})

            if usuario_grupo_id and tipo and app_label:
                ordered_permissions = []
                try:
                    app_config = apps.get_app_config(app_label)
                    app_models = app_config.get_models()
                except LookupError:
                    logger.error(f"App label inválido: {app_label}")
                    return JsonResponse({'error': 'Aplicação inválida.'}, status=400)

                # Carregar permissões do app
                for model in app_models:
                    content_type = ContentType.objects.get_for_model(model)
                    # Permissões customizadas
                    custom_permissions = getattr(model._meta, 'permissions', [])
                    for codename, name in custom_permissions:
                        try:
                            permission = Permission.objects.get(content_type=content_type, codename=codename)
                            ordered_permissions.append(permission)
                        except Permission.DoesNotExist:
                            pass

                    # Permissões padrão
                    default_permissions = getattr(model._meta, 'default_permissions', ('add', 'change', 'delete', 'view'))
                    for perm in default_permissions:
                        codename = f"{perm}_{model._meta.model_name}"
                        try:
                            permission = Permission.objects.get(content_type=content_type, codename=codename)
                            ordered_permissions.append(permission)
                        except Permission.DoesNotExist:
                            pass

                permissoes_list = [
                    {'id': p.id, 'name': p.name, 'app_label': p.content_type.app_label}
                    for p in ordered_permissions
                ]

                tipo_lower = tipo.lower()
                if tipo_lower == 'usuario':
                    usuario = get_object_or_404(Usuario, id=usuario_grupo_id)
                    permissoes_selecionadas = list(usuario.user_permissions.filter(content_type__app_label=app_label).values_list('id', flat=True))
                elif tipo_lower == 'grupo':
                    group = get_object_or_404(Group, id=usuario_grupo_id)
                    permissoes_selecionadas = list(group.permissions.filter(content_type__app_label=app_label).values_list('id', flat=True))
                else:
                    permissoes_selecionadas = []

                return JsonResponse({
                    'permissoes': permissoes_list,
                    'permissoes_selecionadas': permissoes_selecionadas
                })

            else:
                return JsonResponse({'error': 'Parâmetros insuficientes.'}, status=400)
        else:
            return render(request, 'usuarios/liberar_permissoes.html')

    elif request.method == 'POST':
        usuario_grupo_id = request.POST.get('usuario_grupo_id')
        tipo = request.POST.get('tipo')
        permissoes_ids = request.POST.getlist('permissoes')
        app_label = request.POST.get('app_label')

        if usuario_grupo_id and tipo and app_label:
            try:
                permissoes_submetidas = set(map(int, permissoes_ids))
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': 'IDs de permissões inválidos.'
                }, status=400)

            permissoes_app = Permission.objects.filter(content_type__app_label=app_label)
            permissoes_app_ids = set(permissoes_app.values_list('id', flat=True))

            # Filtrar apenas as permissões válidas para o app
            permissoes_submetidas = permissoes_submetidas & permissoes_app_ids

            tipo_lower = tipo.lower()
            if tipo_lower == 'usuario':
                usuario = get_object_or_404(Usuario, id=usuario_grupo_id)
                permissoes_atual = set(usuario.user_permissions.filter(content_type__app_label=app_label).values_list('id', flat=True))
                permissoes_a_adicionar = permissoes_submetidas - permissoes_atual
                permissoes_a_remover = permissoes_atual - permissoes_submetidas
                usuario.user_permissions.add(*Permission.objects.filter(id__in=permissoes_a_adicionar))
                usuario.user_permissions.remove(*Permission.objects.filter(id__in=permissoes_a_remover))

                return JsonResponse({
                    'success': True,
                    'message': f"Permissões atualizadas para o usuário {usuario.username}."
                })

            elif tipo_lower == 'grupo':
                group = get_object_or_404(Group, id=usuario_grupo_id)
                permissoes_atual = set(group.permissions.filter(content_type__app_label=app_label).values_list('id', flat=True))
                permissoes_a_adicionar = permissoes_submetidas - permissoes_atual
                permissoes_a_remover = permissoes_atual - permissoes_submetidas
                group.permissions.add(*Permission.objects.filter(id__in=permissoes_a_adicionar))
                group.permissions.remove(*Permission.objects.filter(id__in=permissoes_a_remover))

                return JsonResponse({
                    'success': True,
                    'message': f"Permissões atualizadas para o grupo {group.name}."
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': "Tipo inválido."
                }, status=400)
        else:
            return JsonResponse({
                'success': False,
                'message': "Por favor, selecione um usuário ou grupo, um aplicativo e as permissões."
            }, status=400)

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



@login_required
@permission_required('usuarios.can_duplica_acesso', raise_exception=True)
def duplicar_acesso(request):
    if request.method == 'POST':
        form = DuplicarAcessoForm(request.POST)
        if form.is_valid():
            origem_id = form.cleaned_data['origem_id']
            destino_id = form.cleaned_data['destino_id']
            origem_nome = form.cleaned_data.get('origem_nome', 'Origem')
            destino_nome = form.cleaned_data.get('destino_nome', 'Destino')
            
            logger.debug(f"Origem ID: {origem_id}, Destino ID: {destino_id}")

            # Determinar se a origem é um usuário ou grupo
            origem_entidade = None
            origem_tipo = None
            try:
                origem_entidade = Usuario.objects.get(id=origem_id)
                origem_tipo = 'usuario'
                logger.debug(f"Origem é um Usuário: {origem_entidade.username}")
            except Usuario.DoesNotExist:
                try:
                    origem_entidade = Group.objects.get(id=origem_id)
                    origem_tipo = 'grupo'
                    logger.debug(f"Origem é um Grupo: {origem_entidade.name}")
                except Group.DoesNotExist:
                    messages.error(request, "Origem inválida selecionada.")
                    logger.error("Origem inválida: Nenhum usuário ou grupo encontrado com o ID fornecido.")
                    return redirect('usuarios:duplicar_acesso')

            # Determinar se o destino é um usuário ou grupo
            destino_entidade = None
            destino_tipo = None
            try:
                destino_entidade = Usuario.objects.get(id=destino_id)
                destino_tipo = 'usuario'
                logger.debug(f"Destino é um Usuário: {destino_entidade.username}")
            except Usuario.DoesNotExist:
                try:
                    destino_entidade = Group.objects.get(id=destino_id)
                    destino_tipo = 'grupo'
                    logger.debug(f"Destino é um Grupo: {destino_entidade.name}")
                except Group.DoesNotExist:
                    messages.error(request, "Destino inválido selecionado.")
                    logger.error("Destino inválido: Nenhum usuário ou grupo encontrado com o ID fornecido.")
                    return redirect('usuarios:duplicar_acesso')

            # Obter permissões da origem
            origem_permissoes = set()
            if origem_tipo == 'usuario':
                # **Ajuste Aqui: Apenas permissões diretas do usuário**
                origem_permissoes.update(origem_entidade.user_permissions.all())
                logger.debug(f"Permissões da Origem (Usuário): {[perm.codename for perm in origem_permissoes]}")
            elif origem_tipo == 'grupo':
                origem_permissoes.update(origem_entidade.permissions.all())
                logger.debug(f"Permissões da Origem (Grupo): {[perm.codename for perm in origem_permissoes]}")

            # Aplicar permissões ao destino
            if destino_tipo == 'usuario':
                destino_entidade.user_permissions.set(origem_permissoes)
                logger.debug(f"Permissões aplicadas ao usuário {destino_entidade.username}")
                messages.success(request, f"Permissões duplicadas de {origem_entidade} para o usuário {destino_entidade} com sucesso.")
            elif destino_tipo == 'grupo':
                destino_entidade.permissions.set(origem_permissoes)
                logger.debug(f"Permissões aplicadas ao grupo {destino_entidade.name}")
                messages.success(request, f"Permissões duplicadas de {origem_entidade} para o grupo {destino_entidade} com sucesso.")

            # Verificar se as permissões foram aplicadas corretamente
            if destino_tipo == 'usuario':
                atual_permissoes = destino_entidade.user_permissions.all()
                logger.debug(f"Permissões atuais do usuário {destino_entidade.username}: {[perm.codename for perm in atual_permissoes]}")
            elif destino_tipo == 'grupo':
                atual_permissoes = destino_entidade.permissions.all()
                logger.debug(f"Permissões atuais do grupo {destino_entidade.name}: {[perm.codename for perm in atual_permissoes]}")

            return redirect('usuarios:duplicar_acesso')
        else:
            logger.error(f"Formulário inválido: {form.errors}")
            messages.error(request, "Erro ao processar o formulário. Verifique os dados inseridos.")
            return redirect('usuarios:duplicar_acesso')
    else:
        form = DuplicarAcessoForm()
    return render(request, 'usuarios/duplicar_acesso.html', {'form': form})

@login_required
@permission_required('usuarios.can_duplica_acesso', raise_exception=True)
def buscar_entidade(request):
    query = request.GET.get('q', '')
    resultados = []
    if query:
        usuarios = Usuario.objects.filter(username__icontains=query, ativo=True).values('id', 'username')
        grupos = Group.objects.filter(name__icontains=query).values('id', 'name')
        for user in usuarios:
            resultados.append({
                'id': user['id'],
                'nome': user['username'],
                'tipo': 'usuario'
            })
        for group in grupos:
            resultados.append({
                'id': group['id'],
                'nome': group['name'],
                'tipo': 'grupo'
            })
    return JsonResponse(resultados, safe=False)



