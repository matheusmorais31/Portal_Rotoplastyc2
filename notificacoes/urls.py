# notificacoes/urls.py

from django.urls import path
from . import views

app_name = 'notificacoes'

urlpatterns = [
    path('', views.listar_notificacoes, name='listar_notificacoes'),
    path('marcar-notificacao-como-lida/<int:notificacao_id>/', views.marcar_notificacao_como_lida, name='marcar_notificacao_como_lida'),
    path('limpar-todas/', views.limpar_todas_notificacoes, name='limpar_todas_notificacoes'),  # Nova rota

]
