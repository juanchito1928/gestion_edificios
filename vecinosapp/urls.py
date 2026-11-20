from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.db import connection
from django.http import JsonResponse
from django_otp.admin import OTPAdminSite
from incidencias.views import pwa_manifest, pwa_service_worker

admin.site.__class__ = OTPAdminSite


def healthcheck(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
        return JsonResponse({"status": "ok", "database": "connected"}, status=200)
    except Exception as exc:
        return JsonResponse({"status": "error", "database": str(exc)}, status=503)


urlpatterns = [
    path('health/', healthcheck, name='healthcheck'),
    path('admin/', admin.site.urls),
    path('api/v1/', include('api.urls')),
    path('cuentas/', include('django.contrib.auth.urls')),
    path('', include('incidencias.urls')),
    path('manifest.json', pwa_manifest, name='pwa_manifest'),
    path('sw.js', pwa_service_worker, name='pwa_sw'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)