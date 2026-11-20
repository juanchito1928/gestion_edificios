from django.urls import path
from django.urls import path
from . import views

app_name = 'incidencias'

urlpatterns = [
    path('', views.IncidenciaListView.as_view(), name='lista_incidencias'),
    path('nueva/', views.crear_incidencia_view, name='crear_incidencia'),
    path('panel/', views.panel_indicadores, name='panel_indicadores'),
    path('panel/api/', views.api_indicadores_json, name='api_indicadores_json'),
    path('<int:pk>/', views.IncidenciaDetailView.as_view(), name='detalle_incidencia'),
    path('<int:pk>/comentar/', views.agregar_comentario, name='agregar_comentario'),
    path('<int:pk>/eliminar/', views.eliminar_incidencia, name='eliminar_incidencia'),
    path('<int:pk>/sincronizar-offline/', views.sincronizar_comentario_offline, name='sincronizar_offline'),
    path('registro/', views.registro_usuario, name='registro'),
]