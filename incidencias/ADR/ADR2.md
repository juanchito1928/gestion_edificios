# ADR 2:

* **Estado:** Aceptado
* **Fecha:** 2026-11-10
* **Autores:** Juan Jimenez - Samuel Valencia

## Contexto
En la versión MVP, la ubicación de las incidencias se almacenaba como una cadena de texto libre (`edificio`) dentro del modelo `Perfil` de cada usuario. Esta estructura presentaba las siguientes deficiencias:
1. Inconsistencia de datos (ej. errores tipográficos en los nombres de los edificios).
2. Imposibilidad de vincular multiples usuarios o departamentos a un mismo espacio físico.
3. Incapacidad de aplicar aislamiento de datos por edificio.

## Decisión
Rediseñar el modelo de datos hacia un dominio rico compuesto por tres entidades fuertemente relacionadas:
1. `Organizacion`: Representa la entidad administradora principal.
2. `Edificio`: Pertenece a una organizacion y agrupa propiedades físicas.
3. `Unidad`: Representa el apartamento, local u oficina específica donde ocurre la incidencia.

Cada `Incidencia` pasa a estar relacionada obligatoriamente con una `Unidad` mediante una llave foranea (`ForeignKey`).

## Consecuencias
* **Positivas:**
  * Normalización completa de la base de datos a nivel físico.
  * Preparación de la estructura relacional para aplicar el modulo 2.
  * Trazabilidad precisa de incidencias por apartamento y por edificio.
* **Negativas:**
  * Se requirio ejecutar una migracion de datos para transformar las cadenas de texto del MVP a instancias de `Unidad`.