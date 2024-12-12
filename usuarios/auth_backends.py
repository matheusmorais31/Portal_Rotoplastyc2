# usuarios/auth_backends.py

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model
from ldap3 import Server, Connection, ALL, NTLM
from django.conf import settings
import logging


User = get_user_model()
logger = logging.getLogger(__name__)
# usuarios/auth_backends.py

# usuarios/auth_backends.py

class ActiveDirectoryBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            logger.info(f"Iniciando autenticação para o usuário: {username}")

            # Configurações do AD
            server = Server(settings.LDAP_SERVER, get_info=ALL)
            conn = Connection(
                server, 
                user=settings.LDAP_USER, 
                password=settings.LDAP_PASSWORD, 
                auto_bind=True
            )
            
            # Realiza a busca do usuário no AD
            search_filter = f"(sAMAccountName={username})"
            conn.search(settings.LDAP_SEARCH_BASE, search_filter, attributes=['sAMAccountName', 'userAccountControl'])
            
            if not conn.entries:
                logger.warning(f"Usuário {username} não encontrado no AD.")
                return None
            
            entry = conn.entries[0]
            user_account_control = entry.userAccountControl.value
            is_disabled = bool(user_account_control & 0x2)  # ACCOUNTDISABLE = 0x2
            
            # Busca ou cria o usuário no Django
            user, created = User.objects.get_or_create(username=username, defaults={
                'is_ad_user': True,
                'ativo': not is_disabled,
                'is_active': not is_disabled
            })
            
            if not created:
                # Atualiza o status do usuário se necessário
                if user.ativo != (not is_disabled):
                    user.ativo = not is_disabled
                    user.is_active = user.ativo
                    user.save()
                    status = 'ativado' if user.is_active else 'inativado'
                    logger.info(f"Usuário '{username}' foi {status} no portal Django.")
            
            if not user.is_active:
                logger.warning(f"Usuário {username} está inativo e não pode ser autenticado.")
                return None  # Não autentica usuários inativos
            
            logger.info(f"Usuário {username} autenticado com sucesso.")
            return user
        except Exception as e:
            logger.error(f"Erro na autenticação do usuário {username}: {str(e)}")
            return None

    def get_user(self, user_id):
        try:
            user = User.objects.get(pk=user_id)
            logger.debug(f"Recuperando usuário pelo ID: {user_id} | Usuário: {user.username}")
            return user
        except User.DoesNotExist:
            logger.warning(f"Usuário com ID {user_id} não existe.")
            return None
