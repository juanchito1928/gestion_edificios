from contextvars import ContextVar
from django.db import models

# Variable segura por contexto/hilo para el edificio activo
_edificio_actual: ContextVar[int | None] = ContextVar("edificio_actual", default=None)


def set_edificio_actual(edificio_id: int | None) -> None:
    _edificio_actual.set(edificio_id)


def get_edificio_actual() -> int | None:
    return _edificio_actual.get()


class PorEdificioQuerySet(models.QuerySet):
    def for_edificio(self, edificio_id: int | None):
        if edificio_id is None:
            return self.none()
        return self.filter(edificio_id=edificio_id)


class PorEdificioManager(models.Manager):
    """
    Manager obligatorio por defecto: filtra automáticamente por el edificio activo
    del contexto actual. Si no hay edificio activo, devuelve vacío (fail-closed).
    """
    def get_queryset(self):
        qs = PorEdificioQuerySet(self.model, using=self._db)
        edificio_id = get_edificio_actual()
        if edificio_id is None:
            return qs.none()
        return qs.filter(edificio_id=edificio_id)


class TodosLosEdificiosManager(models.Manager):
    """Manager explícito únicamente para tareas administrativas internas o auditoría global."""
    pass