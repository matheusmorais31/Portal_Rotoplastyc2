from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model
from ldap3 import Server, Connection, ALL
from django.conf import settings
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

class ActiveDirectoryBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            logger.info(f"Iniciando autenticação no AD para o usuário: {username}")

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
            conn.search(settings.LDAP_SEARCH_BASE, search_filter, attributes=['sAMAccountName','userAccountControl'])
            
            if not conn.entries:
                logger.warning(f"Usuário {username} não encontrado no AD.")
                return None

            # Pega a primeira entrada
            entry = conn.entries[0]
            user_account_control = entry.userAccountControl.value
            is_disabled = bool(user_account_control & 0x2)  # ACCOUNTDISABLE = 0x2

            # Tenta recuperar o usuário local que seja AD
            try:
                user = User.objects.get(username=username, is_ad_user=True)
            except User.DoesNotExist:
                # Aqui está o pulo do gato:
                # Se não existe localmente como is_ad_user=True,
                # simplesmente não autentica.
                logger.warning(
                    f"Usuário {username} existe no AD mas não foi importado (não existe no Django)."
                )
                return None

            # Verifica se está inativo
            if is_disabled:
                logger.warning(f"Usuário {username} está desabilitado no AD.")
                # Opcionalmente você pode inativar também localmente
                if user.is_active:
                    user.is_active = False
                    user.ativo = False
                    user.save()
                return None

            # Se no local (Django) o usuário estiver marcado como inativo
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
            user = User.objects.get(pk=user_id)
            logger.debug(f"Recuperando usuário pelo ID: {user_id} | Usuário: {user.username}")
            return user
        except User.DoesNotExist:
            logger.warning(f"Usuário com ID {user_id} não existe.")
            return None
