from django.db import connection
from rest_framework.permissions import BasePermission
from incidencias.tenant import set_edificio_actual


class ContextoEdificioRLSPermission(BasePermission):
    """
    Asegura que el usuario autenticado (JWT o Sesión) tenga un edificio asignado
    y activa tanto el contexto en Python como la variable RLS de PostgreSQL.
    """
    message = "El usuario no tiene un edificio asociado."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        perfil = getattr(user, 'perfil', None)
        edificio_id = getattr(perfil, 'edificio_id', None)
        if not edificio_id:
            return False

        set_edificio_actual(edificio_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.current_edificio_id', %s, false);",
                [str(edificio_id)],
            )
        return True