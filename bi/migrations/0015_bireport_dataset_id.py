# Generated by Django 5.1.2 on 2024-12-06 13:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bi', '0014_remove_bireport_dataset_id_remove_bireport_roles'),
    ]

    operations = [
        migrations.AddField(
            model_name='bireport',
            name='dataset_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
