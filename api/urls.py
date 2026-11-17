from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import IncidenciaViewSet, SubidaPrefirmadaView, SuscripcionWebhookViewSet

router = DefaultRouter()
router.register(r'incidencias', IncidenciaViewSet, basename='api-incidencia')
router.register(r'webhooks', SuscripcionWebhookViewSet, basename='api-webhook')

urlpatterns = [
    path('', include(router.urls)),
    # JWT con rotación de tokens de refresco
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # OpenAPI / Swagger
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    # Subida prefirmada
    path('uploads/prefirmado/<str:token>/', SubidaPrefirmadaView.as_view(), name='adjunto-upload-directo'),
]
