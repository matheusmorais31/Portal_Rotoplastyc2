# models.py

from django.db import models
from django.contrib.auth.models import AbstractUser, Permission
from django.contrib.auth import get_user_model

class Usuario(AbstractUser):
    is_ad_user = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'
        default_permissions = ()
        permissions = [
            ('list_user', 'Lista de Usuários'),
            ('can_add_user', 'Cadastra Usuário'),
            ('can_import_user', 'Importar Usuário'),
            ('can_edit_user', 'Editar Usuário'),    
            ('change_permission', 'Liberar Permissões'),
            ('can_duplica_acesso', 'Duplicar Acesso'),
            ('can_view_list_group', 'Lista de Grupos'),
            ('can_add_group', 'Cadastra Grupo'),
            ('can_edit_group', 'Editar Grupo'),
            ('can_delete_group', 'Excluir Grupo'),
            
        ]

    def save(self, *args, **kwargs):
        self.is_active = self.ativo
        super().save(*args, **kwargs)

