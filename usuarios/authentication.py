# authentication.py

import logging
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import Permission
from usuarios.models import Usuario, Grupo  # Importa o modelo Grupo personalizado

logger = logging.getLogger(__name__)

class CustomBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = Usuario.objects.get(username=username)
            if user.check_password(password):
                return user
        except Usuario.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return Usuario.objects.get(pk=user_id)
        except Usuario.DoesNotExist:
            return None

    def get_group_permissions(self, user_obj, obj=None):
        if not hasattr(user_obj, '_group_perm_cache'):
            # Obtém todos os grupos aos quais o usuário pertence
            grupos = Grupo.objects.filter(participantes=user_obj)

            # Obtém todas as permissões associadas a esses grupos
            permissions = Permission.objects.filter(grupos__in=grupos).values_list(
                'content_type__app_label', 'codename'
            ).distinct()

            user_obj._group_perm_cache = set(
                f"{perm[0]}.{perm[1]}" for perm in permissions
            )
            logger.debug(f"Permissões de grupo para {user_obj.username}: {user_obj._group_perm_cache}")
        return user_obj._group_perm_cache

    def get_user_permissions(self, user_obj, obj=None):
        if not hasattr(user_obj, '_user_perm_cache'):
            permissions = user_obj.user_permissions.all().values_list(
                'content_type__app_label', 'codename'
            )
            user_obj._user_perm_cache = set(
                f"{perm[0]}.{perm[1]}" for perm in permissions
            )
            logger.debug(f"Permissões de usuário para {user_obj.username}: {user_obj._user_perm_cache}")
        return user_obj._user_perm_cache

    def get_all_permissions(self, user_obj, obj=None):
        if not hasattr(user_obj, '_perm_cache'):
            user_obj._perm_cache = self.get_user_permissions(user_obj, obj).union(
                self.get_group_permissions(user_obj, obj)
            )
            logger.debug(f"Todas as permissões para {user_obj.username}: {user_obj._perm_cache}")
        return user_obj._perm_cache

    def has_perm(self, user_obj, perm, obj=None):
        if not user_obj.is_active:
            return False
        if perm in self.get_all_permissions(user_obj, obj):
            logger.debug(f"Usuário {user_obj.username} TEM permissão {perm}")
            return True
        logger.debug(f"Usuário {user_obj.username} NÃO TEM permissão {perm}")
        return False
