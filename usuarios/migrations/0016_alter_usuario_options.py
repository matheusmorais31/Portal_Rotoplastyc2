# Generated by Django 5.1.2 on 2024-11-14 20:40

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0015_alter_usuario_options'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='usuario',
            options={'permissions': [('can_view_list_user', 'Pode ver lista de Usuário'), ('can_edit_user', 'Pode editar Usuário'), ('can_add_user', 'Pode adicionar Usuário')], 'verbose_name': 'Usuário', 'verbose_name_plural': 'Usuários'},
        ),
    ]