# TorreOps — Sistema de Gestión Operativa de Edificios

**TorreOps** (`gestion_edificios`) es una aplicación web progresiva (PWA) desarrollada en **Django** y **PostgreSQL** para la administración de incidencias residenciales, asignación de técnicos, control de acceso por roles y monitoreo operativo en tiempo real.

---

## Tabla de Contenidos
1. [Evolución por Módulos (M1 – M10+)](#evolución-por-módulos-m1--m10)
2. [Arquitectura y Stack Tecnológico](#arquitectura-y-stack-tecnológico)
3. [Roles y Control de Permisos](#roles-y-control-de-permisos)
4. [Instalación y Ejecución Local](#instalación-y-ejecución-local)
5. [Ejecución con Docker](#ejecución-con-docker)
6. [Pruebas Automatizadas](#pruebas-automatizadas)
7. [Autores](#autores)

---

## Evolución por Módulos (M1 – M10+)

* **Módulo 1 — Configuración Inicial y Modelado Base:** Estructura del proyecto Django (`vecinosapp`), configuración de entornos y definición de modelos principales: `Organizacion`, `Edificio`, `Unidad` (incluyendo áreas comunes), `Perfil`, `Tecnico`, `Incidencia`, `Comentario` y `EventoIncidencia`.
* **Módulo 2 — Gestión de Incidencias y Reglas de Negocio (`use_cases.py`):** Creación de reportes con evidencia fotográfica, categorías (`AGUA`, `ELECTRICIDAD`, `ASCENSORES`, `LOCATIVO`, `ASEO`, `SEGURIDAD`, `OTRO`), validación de transiciones de estado (`PENDIENTE` → `EN_PROCESO` → `RESUELTA` → `CERRADA`) y prevención de doble asignación a técnicos ocupados.
* **Módulo 3 — Autenticación, Registro y Control de Acceso (RBAC):** Flujo de inicio de sesión, registro guiado de residentes con selección de edificio, torre (`Torre A`, `Torre B`) y apartamento, aislamiento de consultas por rol y soporte de autenticación en dos pasos (OTP).
* **Módulo 4 — API REST y Validación Basada en Propiedades:** Endpoints RESTful con Django REST Framework (`api/`), serializadores, permisos por rol y pruebas automatizadas de contratos de API (Schemathesis).
* **Módulo 5 — Comunicación en Tiempo Real y Mensajería (`mensajeria`):** Integración de Django Channels y WebSockets (`/ws/incidencias/<id>/`) para actualizar en vivo estados, asignación de técnicos, tiempos estimados e instrucciones sin recargar la página.
* **Módulo 6 — Búsqueda Avanzada en PostgreSQL:** Búsqueda de texto completo (`SearchVector`, `SearchQuery`, `SearchRank`) en español combinada con similitud de trigramas (`TrigramSimilarity`) para tolerancia a errores tipográficos en títulos y descripciones.
* **Módulo 7 — Panel de Indicadores Operativos (KPIs):** Dashboard analítico (`/panel-indicadores/`) con métricas de casos totales, casos abiertos, **MTTR** (Tiempo Medio de Resolución), cumplimiento de **SLA** (< 24h), tasa de reapertura y carga por técnico con filtros dinámicos.
* **Módulo 8 — Contenerización y Despliegue:** Configuración de `Dockerfile`, `.dockerignore` y plantilla de variables de entorno (`.env.example`) para despliegue reproducible.
* **Módulo 9 — Aplicación Web Progresiva (PWA) y Modo Offline:** Incorporación de `manifest.json` y Service Worker (`sw.js`), indicador visual de estado de red (`En línea` / `Sin conexión`) y cola local (`localStorage`) con sincronización automática de comentarios al recuperar conexión.
* **Módulo 10 — Identidad TorreOps, UI GitHub Dark y Refinamiento de Seguridad:**
  * Nueva identidad visual **TorreOps** con logo vectorial SVG en barra de navegación (`base.html`), pantalla de inicio de sesión (`login.html`) y manifiesto PWA.
  * Estética **GitHub Dark** (`#0d1117`, `#161b22`, `#21262d`, `#30363d`) con alto contraste en tarjetas, formularios, alertas y etiquetas de estado.
  * Bloqueo en frontend (`incidencia_detail.html`) y backend (`agregar_comentario` y `_puede_cambiar_estado`) para impedir que los residentes modifiquen el estado de las incidencias.

---

## Arquitectura y Stack Tecnológico

* **Backend:** Python 3.13, Django 6.0, Django REST Framework, Django Channels (ASGI/WebSockets).
* **Base de Datos:** PostgreSQL (con búsqueda de texto completo y `pg_trgm`).
* **Frontend:** HTML5, CSS3 personalizado (GitHub Dark Theme + SVG), Bootstrap 5.3, JavaScript Vanilla (WebSockets + Offline Sync).
* **Infraestructura & Calidad:** Docker, Service Workers (PWA), Django TestCase / Schemathesis.

---

## Roles y Control de Permisos

| Rol | Visualización | Crear / Comentar | Asignar Técnico | Cambiar Estado | Panel KPIs |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Residente** | Solo sus reportes | ✅ | ❌ | ❌ | ❌ |
| **Técnico** | Solo incidencias asignadas | ✅ | ❌ | ✅ | ✅ |
| **Admin Edificio / Admin** | Todas las incidencias | ✅ | ✅ | ✅ | ✅ |
| **Auditor** | Todas (solo lectura) | ❌ | ❌ | ❌ | ✅ |

---

## Instalación y Ejecución Local

1. **Clonar el repositorio:**
   git clone 
   [https://github.com/juanchito1928/gestion_edificios.git]
   (https://github.com/juanchito1928/gestion_edificios.git)
   cd gestion_edificios

2. **Crear y activar el entorno virtual:**
   python -m venv venv
   # En Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # En Linux / macOS:
   source venv/bin/activate

3. **Instalar dependencias:**
    pip install -r requirements.txt

4. **Aplicar migraciones y crear superusuario:**
    python manage.py migrate
    python manage.py createsuperuser

5. **Iniciar el servidor local:**
    python manage.py runserver

6. **Ejecucion con Docker:**
    docker build -t torreops .
    docker run --env-file .env -p 8000:8000 torreops

7. **Pruebas Automatizadas:**
    python manage.py test

## Autores:
- Juan Jose Jimenez Lopez
- Samuel Andres Valencia Ramirez