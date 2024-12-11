# authentication.py

import logging
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import Permission, Group
from usuarios.models import Usuario
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)

class CustomBackend(BaseBackend):
    def get_group_permissions(self, user_obj, obj=None):
        if not hasattr(user_obj, '_group_perm_cache'):
            groups = user_obj.groups.all()
            permissions = Permission.objects.filter(group__in=groups).values_list(
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

    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = Usuario.objects.get(username=username)
            if user.is_ad_user:
                # Implementar autenticação via AD se necessário
                pass
            else:
                if user.check_password(password):
                    return user
        except Usuario.DoesNotExist:
            return None
