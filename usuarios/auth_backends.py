# auth_backends.py

import logging
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import Permission, Group
from .models import Usuario
from ldap3 import Server, Connection, ALL, NTLM

logger = logging.getLogger(__name__)

def autenticar_usuario_ad(username, password):
    ldap_server = "ldap://rotoplastyc.net"
    admin_user = "CN=Administrador,CN=Users,DC=rotoplastyc,DC=net"
    admin_password = "56dgqipcDuq78fRNhEkEkxvJGoeKa5hA"

    try:
        logger.info(f"Tentando autenticar o usuário {username} no LDAP.")
        server = Server(ldap_server, get_info=ALL)

        with Connection(server, user=admin_user, password=admin_password, auto_bind=True) as admin_conn:
            search_base = "OU=Usuarios,OU=Rotoplastyc,DC=rotoplastyc,DC=net"
            search_filter = f"(sAMAccountName={username})"
            admin_conn.search(search_base, search_filter, attributes=['distinguishedName'])

            if not admin_conn.entries:
                logger.warning(f"Usuário {username} não encontrado no LDAP.")
                return False

            user_dn = admin_conn.entries[0].distinguishedName.value
            logger.info(f"DN encontrado para o usuário {username}: {user_dn}")

        with Connection(server, user=user_dn, password=password, auto_bind=True) as user_conn:
            logger.info(f"Usuário {username} autenticado com sucesso no LDAP.")
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
                logger.info(f"Tentando autenticar {username} no AD.")
                if autenticar_usuario_ad(username, password):
                    logger.info(f"Usuário {username} autenticado com sucesso via AD.")
                    return user
                else:
                    logger.warning(f"Falha na autenticação do usuário {username} no AD.")
                    return None
            else:
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
