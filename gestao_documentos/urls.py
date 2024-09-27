from django.contrib import admin
from django.urls import path, include
from usuarios import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),  # Página inicial (home)
    path('usuarios/', include('usuarios.urls')),  # Inclui as URLs do app 'usuarios'
]
