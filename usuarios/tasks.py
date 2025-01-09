from celery import shared_task
from django.conf import settings
from ldap3 import Server, Connection, ALL
import logging
from usuarios.models import Usuario

logger = logging.getLogger(__name__)

@shared_task
def sync_ad_users():
    """
    Sincroniza o status de ativação dos usuários do AD que já existem no Django.
    Não cria novos usuários.
    """
    try:
        logger.info(f"Conectando ao servidor LDAP: {settings.LDAP_SERVER}")
        server = Server(settings.LDAP_SERVER, get_info=ALL)
        conn = Connection(server, user=settings.LDAP_USER, password=settings.LDAP_PASSWORD, auto_bind=True)
        logger.info("Conexão com o LDAP estabelecida com sucesso.")

        # Busca todos os usuários do portal que são do AD
        usuarios_ad = Usuario.objects.filter(is_ad_user=True)

        for usuario in usuarios_ad:
            # Filtro para buscar apenas o usuário atual no AD
            search_filter = f"(sAMAccountName={usuario.username})"

            conn.search(
                search_base=settings.LDAP_SEARCH_BASE,
                search_filter=search_filter,
                attributes=["sAMAccountName", "userAccountControl"]
            )

            if conn.entries:
                # Usuário encontrado no AD
                entry = conn.entries[0]
                user_account_control = entry.userAccountControl.value
                is_disabled = bool(user_account_control & 0x2)  # ACCOUNTDISABLE = 0x2

                # Atualiza se houver discrepância entre o status do AD e o do Django
                if usuario.ativo != (not is_disabled):
                    usuario.ativo = not is_disabled
                    usuario.is_active = usuario.ativo
                    usuario.save()
                    status = 'ativado' if usuario.ativo else 'inativado'
                    logger.info(f"Usuário '{usuario.username}' foi {status} no portal Django.")
            else:
                # Usuário não foi encontrado no AD => inativar
                if usuario.ativo:
                    usuario.ativo = False
                    usuario.is_active = False
                    usuario.save()
                    logger.info(f"Usuário '{usuario.username}' inativado porque não foi encontrado no AD.")

        conn.unbind()
        logger.info("Sincronização de usuários concluída com sucesso.")

    except Exception as e:
        logger.error(f"Erro durante a sincronização de usuários: {str(e)}")
