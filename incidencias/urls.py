from django.urls import path
from . import views

app_name = 'incidencias'

urlpatterns = [
    path('', views.IncidenciaListView.as_view(), name='lista_incidencias'),
    path('nueva/', views.crear_incidencia_view, name='crear_incidencia'),
    path('<int:pk>/', views.IncidenciaDetailView.as_view(), name='detalle_incidencia'),
    path('<int:pk>/comentar/', views.agregar_comentario, name='agregar_comentario'),
    path('registro/', views.registro_usuario, name='registro'),
]