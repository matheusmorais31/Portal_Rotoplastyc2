# Generated by Django 5.1.2 on 2025-05-23 10:47

import django.db.models.deletion
import documentos.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0040_alter_documento_options_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='documento',
            name='identificador_raiz',
            field=models.CharField(blank=True, db_index=True, editable=False, help_text='Identificador único para todas as revisões de um mesmo documento.', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='documentodeletado',
            name='identificador_raiz_deletado',
            field=models.CharField(blank=True, help_text='ID raiz do documento deletado', max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='documento',
            name='aprovador1',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='aprovador1_documentos', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='documento',
            name='document_type',
            field=models.CharField(choices=[('pdf', 'PDF'), ('spreadsheet', 'Planilha'), ('pdf_spreadsheet', 'PDF da Planilha')], default='pdf', help_text='Tipo do documento: PDF, Planilha ou PDF da Planilha (manual).', max_length=20),
        ),
        migrations.AlterField(
            model_name='documento',
            name='documento',
            field=models.FileField(help_text='Arquivo editável (.doc, .docx, .odt, .xls, .xlsx, .ods)', storage=documentos.models.OverwriteStorage(), upload_to=documentos.models.documento_upload_path),
        ),
        migrations.AlterField(
            model_name='documento',
            name='documento_original',
            field=models.ForeignKey(blank=True, help_text='Referência à primeira revisão (versão inicial) deste conjunto de documentos.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='revisoes_filhas', to='documentos.documento'),
        ),
        migrations.AlterField(
            model_name='documento',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Indica se o documento (esta revisão) está ativo e listado.'),
        ),
        migrations.AlterField(
            model_name='documento',
            name='nome',
            field=models.CharField(help_text='Nome desta revisão específica do documento.', max_length=200),
        ),
        migrations.AlterField(
            model_name='documento',
            name='solicitante',
            field=models.ForeignKey(default=38, on_delete=django.db.models.deletion.CASCADE, related_name='documentos_solicitados', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='documentodeletado',
            name='usuario',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documentos_deletados_por_usuario', to=settings.AUTH_USER_MODEL),
        ),
    ]
