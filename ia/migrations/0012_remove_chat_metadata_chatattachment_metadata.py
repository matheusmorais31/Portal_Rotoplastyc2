# Generated by Django 5.1.2 on 2025-06-06 15:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ia', '0011_chat_metadata'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='chat',
            name='metadata',
        ),
        migrations.AddField(
            model_name='chatattachment',
            name='metadata',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
