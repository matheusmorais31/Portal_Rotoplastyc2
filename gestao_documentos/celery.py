# Portal_Rotoplastyc/celery.py

import os
from celery import Celery

# Definir o módulo de configurações do Django para o Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_documentos.settings')

app = Celery('gestao_documentos')

# Carregar as configurações do Celery a partir do settings.py com o prefixo 'CELERY'
app.config_from_object('django.conf:settings', namespace='CELERY')

# Descobrir e carregar tarefas em todos os aplicativos Django instalados
app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
