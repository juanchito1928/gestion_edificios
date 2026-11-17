# ADR 1:

* **Estado:** Aceptado
* **Fecha:** 2026-11-10
* **Autores:** Juan Jimenez - Samuel Valencia

## Contexto
En la arquitectura inicial (MVP), las vistas de Django (`views.py`) manipulaban directamente las entidades en la base de datos y gestionaban las validaciones de estado de las incidencias. Esto provocaba:
1. Acoplamiento entre el protocolo HTTP y la logica del negocio.
2. Imposibilidad de garantizar que una incidencia no saltara a estados invalidos desde otros puntos del sistema.
3. Falta de trazabilidad sobre quien, cuando y por que cambio el estado de un reporte.

## Decisión
1. **Casos de Uso:** Se extrajeron todas las operaciones de modificación fuera de `views.py` hacia `incidencias/use_cases.py` (`crear_incidencia`, `cambiar_estado`, `asignar_tecnico`, `reabrir_incidencia`).
2. **Maquina de Estados:** Se definio una matriz de transiciones permitidas en la capa de aplicacion. Cualquier intento de cambio invalido lanza una excepcion `ValidationError`.
3. **Evento:** Se creó el modelo `EventoIncidencia`. Cada mutacion registra un evento inmutable con los desgloses `datos_previos` y `datos_nuevos` en formato JSON sin modificar registros.

## Consecuencias
* **Positivas:**
  * Cohesion alta: Las vistas solo reciben peticiones HTTP y renderizan respuestas.
  * Testeabilidad: Se puede probar la logica de negocio en `tests.py` sin simular peticiones HTTP.
  * Auditoria completa e inalterable exigida por el dominio.
* **Negativas:**
  * Ligero incremento en el tiempo de desarrollo por cada nueva funcion.
  * Mayor volumen de almacenamiento en base de datos al guardar un registro por cada evento.