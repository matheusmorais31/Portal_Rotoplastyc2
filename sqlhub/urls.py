# sqlhub/urls.py
from django.urls import path
from . import views

app_name = "sqlhub"

urlpatterns = [
    # Conexões
    path("connections/", views.ConnectionList.as_view(), name="conn_list"),
    path("connections/new/", views.ConnectionCreate.as_view(), name="conn_new"),
    path("connections/<int:pk>/edit/", views.ConnectionUpdate.as_view(), name="conn_edit"),
    path("connections/<int:pk>/test/", views.test_connection_view, name="conn_test"),

    # Consultas
    path("queries/", views.QueryList.as_view(), name="query_list"),
    path("queries/new/", views.QueryCreate.as_view(), name="query_new"),
    path("queries/<int:pk>/edit/", views.QueryUpdate.as_view(), name="query_edit"),
    path("queries/<int:pk>/preview/", views.query_preview, name="query_preview"),
    path("queries/<int:pk>/columns/", views.query_columns, name="query_columns"),

    # Ad-hoc (editor)
    path("queries/adhoc-preview/", views.query_preview_adhoc, name="query_preview_adhoc"),
    path("queries/adhoc-export/", views.query_export_adhoc, name="query_export_adhoc"),
    path("queries/adhoc-page/", views.query_page_adhoc, name="query_page_adhoc"),

    # API de opções (selects)
    path("api/query/<int:pk>/options/", views.query_options_api, name="query_options_api"),
    path("api/query/adhoc/count/", views.query_count_adhoc, name="query_count_adhoc"),

    # ===== NOVO: listas para o builder dos formulários =====
    path("api/connections/", views.connections_list_api, name="api_connections"),
    path("api/queries/", views.queries_list_api, name="api_queries"),
]
