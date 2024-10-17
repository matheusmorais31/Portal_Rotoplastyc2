# auth_backends.py

from django.contrib.auth.backends import BaseBackend
from .models import Usuario
import logging
from ldap3 import Server, Connection, ALL

logger = logging.getLogger(__name__)

def autenticar_usuario_ad(username, password):
    ldap_server = "ldap://tcc1.net"
    admin_user = "CN=Administrator,CN=Users,DC=tcc1,DC=net"
    admin_password = "Admin@ti"

    try:
        logger.info(f"Tentando autenticar o usuário {username} no LDAP.")
        server = Server(ldap_server, get_info=ALL)

        # Conexão com credenciais de administrador para buscar o DN do usuário
        admin_conn = Connection(server, user=admin_user, password=admin_password, auto_bind=True)
        search_base = "CN=Users,DC=tcc1,DC=net"
        search_filter = f"(sAMAccountName={username})"
        admin_conn.search(search_base, search_filter, attributes=['distinguishedName'])
        
        if not admin_conn.entries:
            logger.warning(f"Usuário {username} não encontrado no LDAP.")
            admin_conn.unbind()
            return False
        
        user_dn = admin_conn.entries[0].distinguishedName.value
        admin_conn.unbind()

        # Tentar autenticar com as credenciais do usuário
        user_conn = Connection(server, user=user_dn, password=password, auto_bind=True)
        logger.info(f"Usuário {username} autenticado com sucesso no LDAP.")
        user_conn.unbind()
        return True

    except Exception as e:
        logger.error(f"Erro ao autenticar o usuário {username} no LDAP: {str(e)}")
        return False

class ActiveDirectoryBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = Usuario.objects.get(username=username)
            logger.info(f"Usuário encontrado: {user.username}")

            if user.is_ad_user:
                # Tentar autenticar via AD
                logger.info(f"Tentando autenticar {username} no AD.")
                if autenticar_usuario_ad(username, password):
                    logger.info(f"Usuário {username} autenticado com sucesso via AD.")
                    return user
                else:
                    logger.warning(f"Falha na autenticação do usuário {username} no AD.")
                    return None
            else:
                # Usuário local, verifica a senha local
                if user.check_password(password):
                    logger.info(f"Usuário {username} autenticado com sucesso com senha local.")
                    return user
                else:
                    logger.warning(f"Senha incorreta para o usuário {username}.")
                    return None

        except Usuario.DoesNotExist:
            logger.warning(f"O usuário {username} não existe no sistema.")
            return None

    def get_user(self, user_id):
        try:
            return Usuario.objects.get(pk=user_id)
        except Usuario.DoesNotExist:
            return None
