# rh/urls.py
from django.urls import path
from . import views

app_name = "rh"
urlpatterns = [
    path("entregas-epi/", views.EntregasEPIListView.as_view(), name="entregas_pendentes"),
    path("entregas-epi/todas/", views.TodasEntregasEPIListView.as_view(), name="entregas_todas"),
    # URL para dar baixa em múltiplos itens (agora não precisa de <int:pk>)
    path("entregas-epi/baixar/", views.baixar_entrega_epi, name="baixar_entrega_epi"), # <-- ALTERADO
    # Endpoint para reverter o status de um item (via POST, AJAX) - mantido por PK individual
    path("entregas-epi/reverter/<int:pk>/", views.reverter_entrega_epi, name="reverter_entrega_epi"),
]