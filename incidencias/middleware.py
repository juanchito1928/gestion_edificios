from django.db import connection
from .models import RegistroAcceso
from .tenant import set_edificio_actual


def _obtener_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class EdificioActivoMiddleware:
    """
    Fija el edificio activo en el contexto de Python (PorEdificioManager)
    y en la sesión de PostgreSQL (Row-Level Security).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        edificio_id = None

        if request.user.is_authenticated:
            edificio_sesion = request.session.get('edificio_activo_id')
            if edificio_sesion:
                edificio_id = int(edificio_sesion)
            elif hasattr(request.user, 'perfil') and request.user.perfil.edificio_id:
                edificio_id = request.user.perfil.edificio_id

        # 1. Contexto en Python (PorEdificioManager)
        set_edificio_actual(edificio_id)
        request.edificio_id = edificio_id

        # 2. Variable de sesión en PostgreSQL (RLS)
        with connection.cursor() as cursor:
            if edificio_id is not None:
                cursor.execute(
                    "SELECT set_config('app.current_edificio_id', %s, false);",
                    [str(edificio_id)],
                )
            else:
                cursor.execute("RESET app.current_edificio_id;")

        try:
            response = self.get_response(request)
        finally:
            set_edificio_actual(None)
            with connection.cursor() as cursor:
                cursor.execute("RESET app.current_edificio_id;")

        # 3. Auditoría de accesos
        if not request.path.startswith(('/static/', '/media/')):
            try:
                RegistroAcceso.objects.create(
                    usuario=request.user if request.user.is_authenticated else None,
                    edificio_id=edificio_id,
                    ruta=request.path[:255],
                    metodo=request.method,
                    codigo_estado=response.status_code,
                    ip_origen=_obtener_ip(request),
                )
            except Exception:
                pass

        return response