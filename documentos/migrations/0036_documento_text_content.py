# Generated by Django 5.1.2 on 2025-05-01 10:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0035_alter_documento_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='documento',
            name='text_content',
            field=models.TextField(blank=True, editable=False, help_text='Texto extraído automaticamente para busca IA'),
        ),
    ]
