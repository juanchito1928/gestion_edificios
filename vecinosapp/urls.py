from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.db import connection
from django.db.models import Count
from django.http import JsonResponse
from django_otp.admin import OTPAdminSite
from incidencias.models import Incidencia
from incidencias.views import pwa_manifest, pwa_service_worker
from mensajeria.models import MensajeOutbox

admin.site.__class__ = OTPAdminSite


def healthcheck(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1;")
        return JsonResponse({"status": "ok", "database": "connected"}, status=200)
    except Exception as exc:
        return JsonResponse({"status": "error", "database": str(exc)}, status=503)


def system_metrics(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return JsonResponse({"detail": "Acceso restringido a administradores."}, status=403)

    por_estado = dict(
        Incidencia.objects.values_list("estado").annotate(total=Count("id"))
    )
    outbox_pendientes = MensajeOutbox.objects.filter(estado="PENDIENTE").count()

    return JsonResponse({
        "service": "vecinosapp",
        "incidencias_por_estado": por_estado,
        "outbox_pendientes": outbox_pendientes,
        "debug_mode": settings.DEBUG,
    })


urlpatterns = [
    path('health/', healthcheck, name='healthcheck'),
    path('metrics/', system_metrics, name='system_metrics'),
    path('admin/', admin.site.urls),
    path('api/v1/', include('api.urls')),
    path('cuentas/', include('django.contrib.auth.urls')),
    path('', include('incidencias.urls')),
    path('manifest.json', pwa_manifest, name='pwa_manifest'),
    path('sw.js', pwa_service_worker, name='pwa_sw'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)