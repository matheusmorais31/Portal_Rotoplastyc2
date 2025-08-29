from django.urls import path
from . import views

app_name = "formularios"

urlpatterns = [
    # ---------- listas ----------
    path("", views.MeusFormulariosView.as_view(),            name="listar_meus"),
    path("todos/", views.TodosFormulariosView.as_view(),     name="todos_formularios"),

    # ---------- criação & builder ----------
    path("novo/",               views.CriarFormularioView.as_view(),   name="criar_formulario"),
    path("<int:pk>/builder/",   views.EditarFormularioView.as_view(),  name="construtor_formulario"),

    # --- endpoint para adicionar linha vazia no formset (HTMX) ---
    path("api/campo-vazio/", views.campo_vazio, name="campo_vazio"),

    # ---------- resposta ----------
    path("<int:pk>/",                 views.exibir_formulario,          name="exibir_formulario"),
    path("<int:pk>/responder/",       views.enviar_resposta_formulario, name="enviar_resposta_formulario"),
    path("resposta/<int:pk>/",        views.DetalheRespostaView.as_view(), name="detalhe_resposta"),
    path("<int:pk>/exportar/csv/",    views.exportar_respostas_csv,     name="exportar_respostas_csv"),
    path("<int:pk>/aba-respostas/",   views.AbaRespostasView.as_view(), name="aba_respostas"),
    path("<int:pk>/exportar/zip/",    views.exportar_anexos_zip,        name="exportar_anexos_zip"),
    path("<int:pk>/respostas/excluir/", views.excluir_respostas,        name="excluir_respostas"),

    # ---------- NOVO: compartilhamento (colaboradores) ----------
    path("<int:pk>/colabs/fragment/",          views.colabs_fragment,     name="colabs_fragment"),
    path("<int:pk>/colabs/add/",               views.add_colab,           name="add_colab"),
    path("<int:pk>/colabs/<int:colab_id>/role/",   views.set_colab_role,  name="set_colab_role"),
    path("<int:pk>/colabs/<int:colab_id>/remove/", views.remove_colab,    name="remove_colab"),
]
