# Generated by Django 5.1.2 on 2024-11-14 17:02

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0018_alter_documento_status'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='documento',
            options={'permissions': [('can_approve', 'Pode aprovar documentos'), ('can_reject', 'Pode reprovar documentos'), ('can_analyze', 'Pode analisar documentos'), ('can_view_editables', 'Pode visualizar documentos editáveis'), ('can_view_revisions', 'Pode visualizar revisões de documentos')]},
        ),
    ]