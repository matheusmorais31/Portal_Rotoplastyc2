from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.contrib.auth import get_user_model

class Usuario(AbstractUser):
    is_ad_user = models.BooleanField(default=False)
    ativo = models.BooleanField(default=True)
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True, default='default_user.png')



    class Meta:
        permissions = [
            ('can_approve_documents', 'Pode aprovar documentos'),
        ]

class Grupo(models.Model):
    nome = models.CharField(max_length=255, unique=True)
    participantes = models.ManyToManyField(get_user_model(), related_name='grupos')
    permissions = models.ManyToManyField(Permission, blank=True)

    def __str__(self):
        return self.nome
