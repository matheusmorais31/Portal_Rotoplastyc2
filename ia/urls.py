# ia/urls.py
from django.urls import path
from . import views

app_name = 'ia'

urlpatterns = [
    # CORRIGIDO para 'chat-page/':
    path('chat-page/', views.chat_page_view, name='chat_page'), # Mude o caminho aqui
    path('chats/', views.list_chats_view, name='list_chats'),
    path('chats/create/', views.create_chat_view, name='create_chat'),
    path('chats/<int:chat_id>/', views.get_chat_view, name='get_chat'),
    path('chats/<int:chat_id>/delete/', views.delete_chat_view, name='delete_chat'),
    path('chats/<int:chat_id>/send_message/', views.send_message_view, name='send_message'),
    path('chats/<int:chat_id>/messages/<int:message_id>/edit/', views.edit_user_message_view, name='edit_message'),
    path('chats/<int:chat_id>/upload/', views.upload_file_to_chat_view, name='upload_file'),
    path('monitor/costs/', views.api_cost_monitor_view, name='api_cost_monitor'), # <<< NOVA URL

]
