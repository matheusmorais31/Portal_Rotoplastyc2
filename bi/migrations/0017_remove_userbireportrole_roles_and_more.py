# Generated by Django 5.1.2 on 2024-12-06 17:29

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bi', '0016_birole_bireport_allowed_roles_userbireportrole'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='userbireportrole',
            name='roles',
        ),
        migrations.RemoveField(
            model_name='bireport',
            name='allowed_roles',
        ),
        migrations.AlterUniqueTogether(
            name='userbireportrole',
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name='userbireportrole',
            name='bi_report',
        ),
        migrations.RemoveField(
            model_name='userbireportrole',
            name='user',
        ),
        migrations.DeleteModel(
            name='BIRole',
        ),
        migrations.DeleteModel(
            name='UserBIReportRole',
        ),
    ]