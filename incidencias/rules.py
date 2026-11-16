import rules
from .models import RolUsuario


def _get_perfil(user):
    if not user or not user.is_authenticated:
        return None
    return getattr(user, 'perfil', None)


def _mismo_edificio(user, obj):
    perfil = _get_perfil(user)
    if not perfil or not perfil.edificio_id:
        return False
    if obj is None:
        return True
    edificio_obj = getattr(obj, 'edificio_id', None)
    return edificio_obj == perfil.edificio_id


# --- Predicados de Rol ---
@rules.predicate
def es_residente(user):
    perfil = _get_perfil(user)
    return bool(perfil and perfil.rol == RolUsuario.RESIDENTE)


@rules.predicate
def es_admin_edificio(user):
    perfil = _get_perfil(user)
    return bool(perfil and perfil.rol == RolUsuario.ADMIN_EDIFICIO)


@rules.predicate
def es_tecnico(user):
    perfil = _get_perfil(user)
    return bool(perfil and perfil.rol == RolUsuario.TECNICO)


@rules.predicate
def es_auditor(user):
    perfil = _get_perfil(user)
    return bool(perfil and perfil.rol == RolUsuario.AUDITOR)


# --- Predicados de Objeto / Pertenencia ---
@rules.predicate
def pertenece_al_edificio(user, obj):
    return _mismo_edificio(user, obj)


@rules.predicate
def es_autor_incidencia(user, incidencia):
    return bool(incidencia and incidencia.reportado_por_id == user.id)


@rules.predicate
def es_tecnico_asignado(user, incidencia):
    if not incidencia or not incidencia.tecnico_asignado_id:
        return False
    return incidencia.tecnico_asignado.usuario_id == user.id


@rules.predicate
def es_edificio_asignado_tecnico(user, obj):
    if not hasattr(user, 'tecnico'):
        return False
    edificio_id = getattr(obj, 'edificio_id', None)
    if edificio_id is None:
        return user.tecnico.edificios_asignados.exists()
    return user.tecnico.edificios_asignados.filter(id=edificio_id).exists()


# --- Matriz de 8 Acciones (Permisos RBAC + ABAC) ---

# 1. Ver listado o detalle de incidencias del edificio
rules.add_perm(
    'incidencias.ver_incidencia',
    pertenece_al_edificio & (es_residente | es_admin_edificio | es_tecnico | es_auditor)
)

# 2. Crear nueva incidencia (Residente y Admin del edificio)
rules.add_perm(
    'incidencias.crear_incidencia',
    pertenece_al_edificio & (es_residente | es_admin_edificio)
)

# 3. Editar datos de una incidencia (Autor mientras esté PENDIENTE, o Admin del edificio)
rules.add_perm(
    'incidencias.editar_incidencia',
    pertenece_al_edificio & (es_admin_edificio | (es_residente & es_autor_incidencia))
)

# 4. Asignar o reasignar técnico (Solo Admin del edificio)
rules.add_perm(
    'incidencias.asignar_tecnico',
    pertenece_al_edificio & es_admin_edificio
)

# 5. Cambiar estado operativo (En proceso / Resuelta) (Admin del edificio o Técnico asignado)
rules.add_perm(
    'incidencias.cambiar_estado_tecnico',
    pertenece_al_edificio & (es_admin_edificio | (es_tecnico & es_tecnico_asignado))
)

# 6. Cerrar o reabrir incidencia definitivamente (Solo Admin del edificio)
rules.add_perm(
    'incidencias.cerrar_incidencia',
    pertenece_al_edificio & es_admin_edificio
)

# 7. Comentar en una incidencia (Todos excepto Auditor, que es solo lectura)
rules.add_perm(
    'incidencias.comentar_incidencia',
    pertenece_al_edificio & (es_residente | es_admin_edificio | es_tecnico)
)

# 8. Ver historial de eventos y registro de auditoría de accesos (Admin y Auditor)
rules.add_perm(
    'incidencias.ver_auditoria',
    pertenece_al_edificio & (es_admin_edificio | es_auditor)
)