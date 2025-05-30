# Generated by Django 5.1.2 on 2024-12-10 16:49

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0030_alter_usuario_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='grupo',
            options={'default_permissions': (), 'permissions': [('can_view_list_group', 'Lista de Grupos'), ('can_add_group', 'Cadastra Grupo'), ('can_edit_group', 'Editar Grupo'), ('can_delete_group', 'Excluir Grupo')], 'verbose_name': 'Usuário', 'verbose_name_plural': 'Usuários'},
        ),
        migrations.AlterModelOptions(
            name='usuario',
            options={'default_permissions': (), 'permissions': [('list_user', 'Lista de Usuários'), ('can_add_user', 'Cadastra Usuário'), ('can_import_user', 'Importar Usuário'), ('can_edit_user', 'Editar Usuário'), ('change_permission', 'Liberar Permissões')], 'verbose_name': 'Usuário', 'verbose_name_plural': 'Usuários'},
        ),
    ]
