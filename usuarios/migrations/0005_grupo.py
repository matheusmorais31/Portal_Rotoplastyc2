# Generated by Django 5.1.1 on 2024-10-07 14:57

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0004_rename_meu_checkbox_usuario_gerente'),
    ]

    operations = [
        migrations.CreateModel(
            name='Grupo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=255)),
                ('participantes', models.ManyToManyField(related_name='grupos', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
