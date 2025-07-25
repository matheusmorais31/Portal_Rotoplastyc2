# --------------------------- Padrão Python ---------------------------
import logging
from itertools import chain
from collections import defaultdict

# -------------------------- Bibliotecas 3rd‑party --------------------
from ldap3 import Server, Connection, ALL

# -------------------------------- Django -----------------------------
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    models as auth_models,
)
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.views import LogoutView
from django.contrib.contenttypes.models import ContentType
from django.db.models import CharField, F, IntegerField, Value
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.timezone import localtime
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

# --------------------------- Apps locais -----------------------------
from .forms import (
    DuplicarAcessoForm,
    GrupoForm,
    ProfileForm,
    UsuarioCadastroForm,
    UsuarioChangeForm,
    UsuarioPermissaoForm,
)
from .models import Usuario





# Configuração do logger
logger = logging.getLogger(__name__)

# Função de login
def login_usuario(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        # Captura o parâmetro "next" enviado como campo hidden no formulário
        next_url = request.POST.get('next') or 'home'
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')

            logger.info(f"Tentando autenticar o usuário: {username}")
            user = authenticate(request, username=username, password=password)

            if user is not None:
                if user.is_active:
                    login(request, user)
                    logger.info(f"Usuário {username} autenticado com sucesso.")
                    return redirect(next_url)
                else:
                    logger.warning(f"Usuário {username} está inativo e tentou realizar login.")
                    form.add_error(None, 'Sua conta está inativa. Por favor, entre em contato com o administrador.')
            else:
                logger.warning(f"Falha na autenticação do usuário {username}. Tentando verificar status da conta.")
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

        return render(request, 'usuarios/login.html', {'form': form, 'next': next_url})
    else:
        form = AuthenticationForm(request)
        # Captura o parâmetro "next" da URL (caso exista)
        next_url = request.GET.get('next', '')
        return render(request, 'usuarios/login.html', {'form': form, 'next': next_url})
    
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



@login_required
@permission_required('usuarios.list_user', raise_exception=True) # Ajuste a permissão se necessário, ex: 'usuarios.can_impersonate_user'
def personificar_usuario(request, usuario_id):
    """
    Personifica outro usuário local/AD.
    """
    if 'original_user_id' not in request.session:
        request.session['original_user_id'] = request.user.pk

    # Guarde localmente
    original_id = request.session['original_user_id']
    impersonation_type = 'usuario'

    # Use o seu modelo de usuário customizado 'Usuario'
    user_alvo = get_object_or_404(Usuario, pk=usuario_id)

    if user_alvo.is_ad_user:
        backend = 'usuarios.auth_backends.ActiveDirectoryBackend'
    else:
        backend = 'django.contrib.auth.backends.ModelBackend'

    # Use a função 'login' importada do Django
    login(request, user_alvo, backend=backend)

    # Regrava as chaves
    request.session['original_user_id'] = original_id
    request.session['impersonation_type'] = impersonation_type

    messages.success(request, f"Personificando usuário {user_alvo.username}.")
    return redirect('home')


@login_required
def reverter_personificacao(request):
    """
    Reverte a personificação do usuário.
    """
    original_user_id = request.session.pop('original_user_id', None)
    request.session.pop('impersonation_type', None)

    if original_user_id:
        try:
            # Use o seu modelo de usuário customizado 'Usuario'
            original_user = Usuario.objects.get(pk=original_user_id)
            if original_user.is_ad_user:
                backend = 'usuarios.auth_backends.ActiveDirectoryBackend'
            else:
                backend = 'django.contrib.auth.backends.ModelBackend'

            # Use a função 'login' importada do Django
            login(request, original_user, backend=backend)
            messages.success(request, f"Você voltou ao seu usuário original: {original_user.username}")
        except Usuario.DoesNotExist: # Use a exceção do seu modelo customizado
            messages.error(request, "Usuário original não encontrado.")
    else:
        messages.warning(request, "Nenhum usuário original foi encontrado para reverter.")

    return redirect('usuarios:lista_usuarios')


def user_relatorios(request):
    return render(request, 'usuarios/user_relatorios.html')




@login_required
@permission_required("usuarios.permission_report", raise_exception=True)
def relatorio_permissoes(request):
    """
    Relatório de permissões de USUÁRIOS.

    Query‑string (texto livre):
        app=<parte do app_label>
        group=<parte do nome do grupo>
        user=<parte do username>
        desc=<parte da descrição da permissão>
        formato=csv|json   (exportações)
    """

    # 1. Filtros enviados
    app_text   = (request.GET.get("app")   or "").strip().lower()
    group_text = (request.GET.get("group") or "").strip().lower()
    user_text  = (request.GET.get("user")  or "").strip().lower()
    desc_text  = (request.GET.get("desc")  or "").strip().lower()

    User = get_user_model()

    # 2. Permissões (diretas e via grupo)
    direct_qs = (
        User.objects.filter(user_permissions__isnull=False)
        .annotate(
            app_label     = F("user_permissions__content_type__app_label"),
            codename      = F("user_permissions__codename"),
            descricao     = F("user_permissions__name"),
            via           = Value("Acesso individual", output_field=CharField()),
            user_id       = F("id"),
            perm_group_id = Value(None, output_field=IntegerField()),
        )
        .values(
            "username", "user_id", "app_label", "codename",
            "descricao", "via", "perm_group_id",
        )
        .distinct()
    )

    group_qs = (
        User.objects.filter(groups__permissions__isnull=False)
        .annotate(
            app_label     = F("groups__permissions__content_type__app_label"),
            codename      = F("groups__permissions__codename"),
            descricao     = F("groups__permissions__name"),
            via           = F("groups__name"),
            user_id       = F("id"),
            perm_group_id = F("groups__id"),
        )
        .values(
            "username", "user_id", "app_label", "codename",
            "descricao", "via", "perm_group_id",
        )
        .distinct()
    )

    permissoes = list(chain(direct_qs, group_qs))

    # 3. Aplica filtros
    if app_text:
        permissoes = [p for p in permissoes if app_text in p["app_label"].lower()]
    if user_text:
        permissoes = [p for p in permissoes if user_text in p["username"].lower()]
    if group_text:
        permissoes = [p for p in permissoes if group_text in p["via"].lower()]
    if desc_text:
        permissoes = [p for p in permissoes if desc_text in p["descricao"].lower()]

    # 4. Ordenação padrão
    permissoes.sort(key=lambda p: (
        p["app_label"].lower(),
        p["username"].lower(),
        p["via"].lower(),
        p["codename"],
    ))

    # 5. Opções para datalist
    app_opts   = sorted({p["app_label"] for p in permissoes})
    group_opts = list(Group.objects.order_by("name")
                      .values_list("name", flat=True))
    user_opts  = list(User.objects.order_by("username")
                      .values_list("username", flat=True))

    # 6. Exportações CSV / JSON
    fmt = request.GET.get("formato", "html").lower()
    if fmt == "json":
        return JsonResponse(permissoes, safe=False)

    if fmt == "csv":
        from csv import writer
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="permissoes_usuarios.csv"'
        w = writer(resp)
        w.writerow(["usuario", "aplicacao", "codename", "descricao", "via"])
        for p in permissoes:
            w.writerow([
                p["username"], p["app_label"], p["codename"],
                p["descricao"], p["via"],
            ])
        return resp

    # 6½. URL do botão “Exportar CSV” mantendo filtros atuais
    qs_csv = request.GET.copy()
    qs_csv["formato"] = "csv"
    export_url = f"{request.path}?{qs_csv.urlencode()}"

    # 7. Renderiza
    return render(
        request,
        "usuarios/relatorio_permissoes.html",
        {
            "permissoes": permissoes,

            "app_opts":   app_opts,
            "group_opts": group_opts,
            "user_opts":  user_opts,

            "app_text":   request.GET.get("app", ""),
            "group_text": request.GET.get("group", ""),
            "user_text":  request.GET.get("user", ""),
            "desc_text":  request.GET.get("desc", ""),

            "export_url": export_url,
        },
    )