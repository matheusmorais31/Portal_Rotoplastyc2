from django.urls import path
from . import views

app_name = 'bi'

urlpatterns = [
    path('', views.bi_report_list, name='bi_report_list'),  # Lista geral
    path('my_bi_reports/', views.my_bi_report_list, name='my_bi_report_list'),  # Lista filtrada
    path('create/', views.create_bi_report, name='create_bi_report'),
    path('edit/<int:pk>/', views.edit_bi_report, name='edit_bi_report'),
    path('<int:pk>/', views.bi_report_detail, name='bi_report_detail'),
    path('get_embed_params/', views.get_embed_params, name='get_embed_params'),
    path('visualizar_acessos_bi/<int:pk>/', views.visualizar_acessos_bi, name='visualizar_acessos_bi'),
    path('buscar_grupos/', views.buscar_grupos, name='buscar_grupos'),
    path('bi_relatorios/', views.bi_relatorios, name='bi_relatorios'),
    path('permissoes/', views.relatorio_permissoes, name='relatorio_permissoes'),
    path('salvar_estado_relatorio/', views.salvar_estado_relatorio, name='salvar_estado_relatorio'),
    path('get_last_update_rt/', views.get_last_update_rt, name='get_last_update_rt'),
    path('refresh_now/', views.refresh_now, name='refresh_now'),
    path('get_refresh_status/', views.get_refresh_status, name='get_refresh_status'),



]
