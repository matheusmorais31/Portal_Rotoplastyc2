from django.db import models
from django.conf import settings

class BIReport(models.Model):
    title = models.CharField(max_length=200)
    embed_code = models.TextField(blank=True, null=True)
    allowed_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='bi_reports',blank=True )
    report_id = models.CharField(max_length=100, unique=True)
    group_id = models.CharField(max_length=100, default='dc152d8a-7555-42d7-b53d-fbe1ce0dff28')  # ID do seu workspace
    dataset_id = models.CharField(max_length=100, blank=True, null=True)  # Novo campo adicionado
    last_updated = models.DateTimeField(blank=True, null=True)
    next_update = models.DateTimeField(null=True, blank=True)  # Permite valores nulos

    def __str__(self):
        return self.title
    
    class Meta:
        default_permissions = ()
    
    from django.db import models
from django.conf import settings

class BIAccess(models.Model):
    bi_report = models.ForeignKey('BIReport', on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    accessed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} acessou {self.bi_report.title} em {self.accessed_at}"


    class Meta:
        default_permissions = ()  # Desativa as permissões padrão
        permissions = [
            ('view_bi', 'Lista geral BI'),
            ('edit_bi', 'Editar BI'),
            ('view_access', 'Visualizar Acessos'),

        
        ]
