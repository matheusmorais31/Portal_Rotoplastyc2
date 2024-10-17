<<<<<<< HEAD
# usuarios/apps.py

from django.apps import AppConfig
=======
from django.apps import AppConfig
from django.db.models.signals import post_migrate

def create_approver_group(sender, **kwargs):
    from django.contrib.auth.models import Group, Permission
    from django.contrib.contenttypes.models import ContentType
    from .models import Usuario

    # Obter ou criar o grupo de aprovadores
    approver_group, created = Group.objects.get_or_create(name='Aprovadores')
    
    # Criar a permissão de aprovar documentos
    content_type = ContentType.objects.get_for_model(Usuario)
    permission, created = Permission.objects.get_or_create(
        codename='can_approve_documents',
        name='Pode aprovar documentos',
        content_type=content_type,
    )

    # Adicionar a permissão ao grupo de aprovadores
    approver_group.permissions.add(permission)
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22

class UsuariosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usuarios'

    def ready(self):
<<<<<<< HEAD
        pass  # Nenhuma ação necessária aqui
=======
        # Conecta a função de criação de grupos e permissões ao sinal post_migrate
        post_migrate.connect(create_approver_group, sender=self)
>>>>>>> 1b655a619311fa616be6d4c7b58a164c69f90e22
