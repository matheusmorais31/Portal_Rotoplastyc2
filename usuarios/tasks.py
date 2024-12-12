# usuarios/tasks.py

import logging
from celery import shared_task
from django.conf import settings
from ldap3 import Server, Connection, ALL
from usuarios.models import Usuario

logger = logging.getLogger(__name__)

@shared_task
def sync_ad_users():
    """
    Sincroniza o status de ativação dos usuários do AD com o portal Django.
    """
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

        # Obter uma lista de todos os usernames no AD
        ad_usernames = set()
        
        # Processar cada usuário encontrado no AD
        for entry in conn.entries:
            username = entry.sAMAccountName.value
            user_account_control = entry.userAccountControl.value

            ad_usernames.add(username)

            # Verificar se o usuário está desativado no AD
            is_disabled = bool(user_account_control & 0x2)  # ACCOUNTDISABLE = 0x2

            try:
                usuario = Usuario.objects.get(username=username)
                # Atualizar o campo 'ativo' baseado no status do AD
                if usuario.ativo != (not is_disabled):
                    usuario.ativo = not is_disabled
                    usuario.is_active = usuario.ativo  # Sincronizar is_active com ativo
                    usuario.save()
                    status = 'ativado' if usuario.ativo else 'inativado'
                    logger.info(f"Usuário '{username}' foi {status} no portal Django.")
            except Usuario.DoesNotExist:
                logger.warning(f"Usuário '{username}' encontrado no AD, mas não existe no portal Django.")
                # Opcional: Criar o usuário no portal se desejar
                # Usuario.objects.create(username=username, ativo=not is_disabled, is_ad_user=True)

        # Opcional: Inativar usuários que não estão mais no AD
        usuarios_no_portal = Usuario.objects.filter(is_ad_user=True)
        for usuario in usuarios_no_portal:
            if usuario.username not in ad_usernames:
                if usuario.ativo:
                    usuario.ativo = False
                    usuario.is_active = False  # Sincronizar is_active com ativo
                    usuario.save()
                    logger.info(f"Usuário '{usuario.username}' inativado porque não foi encontrado no AD.")

        logger.info("Sincronização de usuários concluída com sucesso.")

    except Exception as e:
        logger.error(f"Erro durante a sincronização de usuários: {str(e)}")
