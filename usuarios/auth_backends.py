import logging
from ldap3 import Server, Connection, ALL
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

logger = logging.getLogger(__name__)
User = get_user_model()

# Backend para autenticação via Active Directory
class ActiveDirectoryBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            logger.info(f"Iniciando autenticação no AD para o usuário: {username}")

            # Conecta ao servidor LDAP com credenciais administrativas para buscar o DN do usuário
            server = Server(settings.LDAP_SERVER, get_info=ALL)
            admin_conn = Connection(
                server,
                user=settings.LDAP_USER,
                password=settings.LDAP_PASSWORD,
                auto_bind=True
            )

            search_filter = f"(sAMAccountName={username})"
            admin_conn.search(
                settings.LDAP_SEARCH_BASE,
                search_filter,
                attributes=['distinguishedName', 'userAccountControl']
            )

            if not admin_conn.entries:
                logger.warning(f"Usuário {username} não encontrado no AD.")
                return None

            entry = admin_conn.entries[0]
            user_dn = entry.distinguishedName.value
            user_account_control = entry.userAccountControl.value
            is_disabled = bool(user_account_control & 0x2)  # Verifica se a conta está desabilitada
            admin_conn.unbind()

            # Tenta realizar um novo bind com o DN do usuário e a senha informada
            user_conn = Connection(server, user=user_dn, password=password)
            if not user_conn.bind():
                logger.warning(f"Senha incorreta para o usuário {username}.")
                return None
            user_conn.unbind()

            # Recupera o usuário local importado (deve estar marcado com is_ad_user=True)
            try:
                user = User.objects.get(username=username, is_ad_user=True)
            except User.DoesNotExist:
                logger.warning(f"Usuário {username} existe no AD, mas não foi importado no Django.")
                return None

            # Se o AD indicar que o usuário está desabilitado, inativa também localmente
            if is_disabled:
                logger.warning(f"Usuário {username} está desabilitado no AD.")
                if user.is_active:
                    user.is_active = False
                    # Se houver um campo personalizado, por exemplo "ativo", atualize-o também
                    if hasattr(user, 'ativo'):
                        user.ativo = False
                    user.save()
                return None

            if not user.is_active:
                logger.warning(f"Usuário {username} está inativo no Django.")
                return None

            logger.info(f"Usuário {username} autenticado com sucesso via AD.")
            return user

        except Exception as e:
            logger.error(f"Erro na autenticação do usuário {username}: {str(e)}")
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


# Backend para autenticação de usuários locais
class CustomBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = User.objects.get(username=username)
            # Se o usuário for do AD, a autenticação deverá ser realizada pelo ActiveDirectoryBackend
            if user.is_ad_user:
                return None
            else:
                if user.check_password(password):
                    return user
        except User.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


"""
IMPORTANTE:

1. Certifique-se de definir as seguintes variáveis em suas configurações (settings.py):
    
    LDAP_SERVER = "ldap://seu_servidor_ldap"
    LDAP_USER = "CN=Administrador,CN=Users,DC=seu_dominio,DC=com"
    LDAP_PASSWORD = "sua_senha_ldap"
    LDAP_SEARCH_BASE = "OU=Usuarios,DC=seu_dominio,DC=com"

2. No settings.py, ajuste a ordem dos backends de autenticação conforme necessário. Por exemplo:

    AUTHENTICATION_BACKENDS = [
        'caminho.para.ActiveDirectoryBackend',  # Utilize o caminho correto para o backend
        'caminho.para.CustomBackend',
        'django.contrib.auth.backends.ModelBackend',
    ]

3. Garanta que o modelo de usuário possua o campo booleano "is_ad_user" (ou similar) para identificar quais usuários foram importados do AD.
4. Se o seu modelo também possuir um campo “ativo” (diferente de is_active), ajuste as referências conforme a sua implementação.

Com este código, a autenticação via AD tentará:
  - Buscar o DN do usuário usando uma conexão LDAP autenticada com credenciais administrativas.
  - Realizar o bind usando o DN do usuário e a senha informada.
  - Validar o estado (ativo/inativo) conforme as informações do AD e do Django.
  
Assim, somente a senha correta permitirá a autenticação de usuários importados do AD.
"""
