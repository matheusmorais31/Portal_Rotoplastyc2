# Generated by Django 5.1.2 on 2024-11-05 19:14

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0009_alter_documento_solicitante'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='documento',
            options={'permissions': [('can_approve', 'Pode aprovar documentos'), ('can_reject', 'Pode reprovar documentos'), ('can_analyze', 'Pode analisar documentos')]},
        ),
        migrations.AddField(
            model_name='documento',
            name='analista',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documentos_analisados', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='documento',
            name='status',
            field=models.CharField(choices=[('aguardando_analise', 'Aguardando Análise'), ('analise_concluida', 'Análise Concluída'), ('aguardando_elaborador', 'Aguardando Aprovação do Elaborador'), ('aguardando_aprovador1', 'Aguardando Aprovação do Aprovador 1'), ('aguardando_aprovador2', 'Aguardando Aprovação do Aprovador 2'), ('aprovado', 'Aprovado'), ('reprovado', 'Reprovado')], default='aguardando_analise', max_length=30),
        ),
    ]
