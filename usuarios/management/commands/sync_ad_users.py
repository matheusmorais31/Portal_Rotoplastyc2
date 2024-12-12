# usuarios/management/commands/sync_ad_users.py

import logging
from django.core.management.base import BaseCommand
from ldap3 import Server, Connection, ALL, NTLM
from django.conf import settings
from usuarios.models import Usuario

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Sincroniza o status de ativação dos usuários do AD com o portal Django.'

    def handle(self, *args, **kwargs):
        ldap_server = settings.LDAP_SERVER
        ldap_user = settings.LDAP_USER
        ldap_password = settings.LDAP_PASSWORD
        search_base = settings.LDAP_SEARCH_BASE

        try:
            logger.info(f"Conectando ao servidor LDAP: {ldap_server}")
            server = Server(ldap_server, get_info=ALL)
            conn = Connection(server, user=ldap_user, password=ldap_password, auto_bind=True)
            logger.info("Conexão com o LDAP estabelecida com sucesso.")

            # Definir o filtro para buscar todos os usuários
            search_filter = "(objectClass=user)"
            attributes = ['sAMAccountName', 'userAccountControl']

            conn.search(search_base, search_filter, attributes=attributes)

            if not conn.entries:
                logger.warning("Nenhum usuário encontrado no AD.")
                return

            # Processar cada usuário encontrado no AD
            for entry in conn.entries:
                username = entry.sAMAccountName.value
                user_account_control = entry.userAccountControl.value

                # Verificar se o usuário está desativado no AD
                is_disabled = bool(user_account_control & 0x2)  # ACCOUNTDISABLE = 0x2

                try:
                    usuario = Usuario.objects.get(username=username)
                    # Atualizar o campo 'ativo' baseado no status do AD
                    if usuario.ativo != (not is_disabled):
                        usuario.ativo = not is_disabled
                        usuario.save()
                        status = 'ativado' if usuario.ativo else 'inativado'
                        logger.info(f"Usuário '{username}' foi {status} no portal Django.")
                except Usuario.DoesNotExist:
                    logger.warning(f"Usuário '{username}' encontrado no AD, mas não existe no portal Django.")

            logger.info("Sincronização de usuários concluída com sucesso.")

        except Exception as e:
            logger.error(f"Erro durante a sincronização de usuários: {str(e)}")
