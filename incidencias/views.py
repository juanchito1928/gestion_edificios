import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector, TrigramSimilarity
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Prefetch, Q
from django.db.models.functions import Greatest
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from . import use_cases
from .models import Comentario, Edificio, EventoIncidencia, Incidencia, Organizacion, Perfil, Tecnico, Unidad

ROLES_PANEL = {'ADMIN_EDIFICIO', 'ADMIN', 'AUDITOR', 'TECNICO'}


def _obtener_rol(user):
    perfil = getattr(user, 'perfil', None)
    return getattr(perfil, 'rol', None)


def _verificar_acceso_panel(user):
    if not (user.is_staff or user.is_superuser or _obtener_rol(user) in ROLES_PANEL):
        raise PermissionDenied("No tienes permisos para acceder al panel de indicadores operativos.")


class IncidenciaListView(LoginRequiredMixin, ListView):
    model = Incidencia
    template_name = 'incidencias/incidencia_list.html'
    context_object_name = 'incidencias'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        rol = _obtener_rol(user)

        qs = Incidencia.objects.select_related(
            'edificio',
            'unidad',
            'reportado_por',
            'tecnico_asignado__usuario',
        )

        if not (user.is_staff or user.is_superuser or rol in ['ADMIN_EDIFICIO', 'ADMIN', 'TECNICO', 'AUDITOR']):
            qs = qs.filter(reportado_por=user)

        estado = (self.request.GET.get('estado') or '').strip()
        if estado:
            qs = qs.filter(estado=estado)

        q = (self.request.GET.get('q') or '').strip()
        if q:
            vector = SearchVector('titulo', weight='A', config='spanish') + SearchVector('descripcion', weight='B', config='spanish')
            query = SearchQuery(q, config='spanish')
            qs = (
                qs.annotate(
                    rank=SearchRank(vector, query),
                    similitud=Greatest(
                        TrigramSimilarity('titulo', q),
                        TrigramSimilarity('descripcion', q),
                    ),
                )
                .filter(
                    Q(rank__gte=0.05)
                    | Q(titulo__trigram_similar=q)
                    | Q(descripcion__trigram_similar=q)
                    | Q(titulo__icontains=q)
                )
                .order_by('-rank', '-similitud', '-fecha_creacion')
            )
            return qs

        return qs.order_by('-fecha_creacion')


class IncidenciaDetailView(LoginRequiredMixin, DetailView):
    model = Incidencia
    template_name = 'incidencias/incidencia_detail.html'
    context_object_name = 'incidencia'

    def get_queryset(self):
        return Incidencia.objects.select_related(
            'edificio',
            'unidad',
            'reportado_por',
            'tecnico_asignado__usuario',
        ).prefetch_related(
            Prefetch(
                'comentarios',
                queryset=Comentario.objects.select_related('autor').order_by('fecha_creacion'),
            ),
            Prefetch(
                'eventos',
                queryset=EventoIncidencia.objects.select_related('usuario_actor').order_by('-fecha_evento'),
            ),
        )


@login_required
def crear_incidencia_view(request):
    if _obtener_rol(request.user) == 'AUDITOR':
        raise PermissionDenied("El rol Auditor tiene acceso estricto de solo lectura.")

    unidades = Unidad.objects.select_related('edificio').all()

    if request.method == 'POST':
        titulo = request.POST.get('titulo')
        descripcion = request.POST.get('descripcion')
        unidad_id = request.POST.get('unidad')
        foto = request.FILES.get('foto')

        if not unidad_id:
            messages.error(request, "Debes seleccionar una unidad.")
            return render(request, 'incidencias/incidencia_form.html', {'unidades': unidades})

        try:
            use_cases.crear_incidencia(
                usuario=request.user,
                titulo=titulo,
                descripcion=descripcion,
                unidad_id=unidad_id,
                foto=foto
            )
            messages.success(request, "Incidencia creada correctamente.")
            return redirect('incidencias:lista_incidencias')
        except Exception as e:
            messages.error(request, f"Error al crear la incidencia: {e}")
            return render(request, 'incidencias/incidencia_form.html', {'unidades': unidades})

    return render(request, 'incidencias/incidencia_form.html', {'unidades': unidades})


@login_required
def agregar_comentario(request, pk):
    if _obtener_rol(request.user) == 'AUDITOR':
        raise PermissionDenied("El rol Auditor no puede comentar ni modificar incidencias.")

    incidencia = get_object_or_404(Incidencia, pk=pk)

    if request.method == 'POST':
        texto = (request.POST.get('texto') or '').strip()
        nuevo_estado = request.POST.get('estado') or request.POST.get('nuevo_estado')

        hubo_cambios = False

        if texto:
            Comentario.objects.create(
                incidencia=incidencia,
                autor=request.user,
                texto=texto
            )
            messages.success(request, "Comentario registrado con éxito.")
            hubo_cambios = True

        if nuevo_estado and nuevo_estado != incidencia.estado:
            try:
                use_cases.cambiar_estado(
                    incidencia_id=pk,
                    nuevo_estado=nuevo_estado,
                    usuario_actor=request.user
                )
                messages.success(request, f"Estado actualizado correctamente a '{nuevo_estado}'.")
                hubo_cambios = True
            except (ValidationError, PermissionDenied) as e:
                error_msg = e.messages[0] if hasattr(e, 'messages') else str(e)
                messages.error(request, f"Transición rechazada: {error_msg}")
                hubo_cambios = True

        if not hubo_cambios:
            messages.info(request, "No se realizó ninguna acción (el comentario estaba vacío y el estado no cambió).")

    return redirect('incidencias:detalle_incidencia', pk=pk)

@login_required
@require_POST
def eliminar_incidencia(request, pk):
    rol = _obtener_rol(request.user)
    if rol == 'AUDITOR':
        raise PermissionDenied("El rol Auditor tiene acceso estricto de solo lectura.")

    incidencia = get_object_or_404(Incidencia, pk=pk)

    es_admin = request.user.is_staff or request.user.is_superuser or rol in ['ADMIN_EDIFICIO', 'ADMIN']
    es_autor_pendiente = (incidencia.reportado_por == request.user and incidencia.estado == 'PENDIENTE')

    if not (es_admin or es_autor_pendiente):
        raise PermissionDenied("No tienes permisos para eliminar esta incidencia.")

    titulo = incidencia.titulo
    incidencia.delete()
    messages.success(request, f"Incidencia '{titulo}' eliminada correctamente.")
    return redirect('incidencias:lista_incidencias')

def registro_usuario(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            nombre_edificio = (request.POST.get('edificio') or 'Edificio Principal').strip()
            piso_puerta = request.POST.get('piso_puerta', 'Sin especificar')

            org, _ = Organizacion.objects.get_or_create(nombre="Organización Principal")
            edificio_obj, _ = Edificio.objects.get_or_create(
                nombre=nombre_edificio,
                defaults={'organizacion': org}
            )

            Perfil.objects.create(
                usuario=user,
                edificio=edificio_obj,
                piso_puerta=piso_puerta
            )

            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('incidencias:lista_incidencias')
    else:
        form = UserCreationForm()

    return render(request, 'registration/registro.html', {'form': form})


# ==============================================================================
# MÓDULO 6: PANEL DE INDICADORES, SINCRONIZACIÓN OFFLINE Y PWA
# ==============================================================================

def _calcular_kpis(request):
    """Calcula los 4 KPIs operativos mediante agregaciones en PostgreSQL con filtros."""
    qs = Incidencia.objects.select_related('edificio', 'tecnico_asignado__usuario')

    edificio_id = (request.GET.get('edificio') or '').strip()
    tecnico_id = (request.GET.get('tecnico') or '').strip()
    fecha_inicio = parse_date(request.GET.get('fecha_inicio') or '')
    fecha_fin = parse_date(request.GET.get('fecha_fin') or '')

    if edificio_id:
        qs = qs.filter(edificio_id=edificio_id)
    if tecnico_id:
        qs = qs.filter(tecnico_asignado_id=tecnico_id)
    if fecha_inicio:
        qs = qs.filter(fecha_creacion__date__gte=fecha_inicio)
    if fecha_fin:
        qs = qs.filter(fecha_creacion__date__lte=fecha_fin)

    total = qs.count()
    abiertos = qs.filter(estado__in=['PENDIENTE', 'EN_PROCESO']).count()
    resueltos_qs = qs.filter(estado__in=['RESUELTA', 'CERRADA'])
    resueltos_count = resueltos_qs.count()

    # 1. Tiempo medio de resolución (MTTR en horas)
    duracion_expr = ExpressionWrapper(
        F('fecha_actualizacion') - F('fecha_creacion'),
        output_field=DurationField(),
    )
    mttr_agg = resueltos_qs.aggregate(promedio=Avg(duracion_expr))['promedio']
    mttr_horas = round(mttr_agg.total_seconds() / 3600, 1) if mttr_agg else 0.0

    # 2. Cumplimiento de SLA (% de casos resueltos en <= 24h)
    dentro_sla = resueltos_qs.annotate(duracion=duracion_expr).filter(
        duracion__lte=timedelta(hours=24)
    ).count()
    cumplimiento_sla = round((dentro_sla / resueltos_count) * 100, 1) if resueltos_count else 100.0

    # 3. Tasa de reapertura (% de incidencias que tuvieron evento de reapertura a PENDIENTE)
    reabiertas = (
        EventoIncidencia.objects.filter(
            incidencia__in=qs,
            tipo_evento='ESTADO_CAMBIADO',
            datos_previos__estado__in=['RESUELTA', 'CERRADA'],
            datos_nuevos__estado='PENDIENTE',
        )
        .values('incidencia_id')
        .distinct()
        .count()
    )
    tasa_reapertura = round((reabiertas / total) * 100, 1) if total else 0.0

    # Distribución por estado para Chart.js
    por_estado_raw = qs.values('estado').annotate(cantidad=Count('id'))
    por_estado = {item['estado']: item['cantidad'] for item in por_estado_raw}

    # Distribución por técnico para Chart.js
    por_tecnico_raw = (
        qs.filter(tecnico_asignado__isnull=False)
        .values('tecnico_asignado__usuario__username')
        .annotate(cantidad=Count('id'))
        .order_by('-cantidad')[:10]
    )
    por_tecnico = {
        item['tecnico_asignado__usuario__username']: item['cantidad']
        for item in por_tecnico_raw
    }

    return {
        'total': total,
        'casos_abiertos': abiertos,
        'mttr_horas': mttr_horas,
        'cumplimiento_sla': cumplimiento_sla,
        'tasa_reapertura': tasa_reapertura,
        'por_estado': por_estado,
        'por_tecnico': por_tecnico,
    }


@login_required
def panel_indicadores(request):
    """Vista del Dashboard operativo con filtros y Chart.js."""
    _verificar_acceso_panel(request.user)
    kpis = _calcular_kpis(request)
    edificios = Edificio.objects.all()
    tecnicos = Tecnico.objects.select_related('usuario').all()

    return render(request, 'incidencias/panel_indicadores.html', {
        'kpis': kpis,
        'kpis_json': json.dumps(kpis),
        'edificios': edificios,
        'tecnicos': tecnicos,
        'filtros': {
            'edificio': request.GET.get('edificio', ''),
            'tecnico': request.GET.get('tecnico', ''),
            'fecha_inicio': request.GET.get('fecha_inicio', ''),
            'fecha_fin': request.GET.get('fecha_fin', ''),
        },
    })


@login_required
def api_indicadores_json(request):
    """Endpoint JSON para actualizar Chart.js dinámicamente al filtrar."""
    _verificar_acceso_panel(request.user)
    return JsonResponse(_calcular_kpis(request))


@login_required
@require_POST
def sincronizar_comentario_offline(request, pk):
    """
    RETO AVANZADO: Recibe comentarios guardados en la cola local del técnico
    cuando estuvo sin conexión y los persiste al volver la red.
    """
    if _obtener_rol(request.user) == 'AUDITOR':
        return JsonResponse({'error': 'Solo lectura'}, status=403)

    incidencia = get_object_or_404(Incidencia, pk=pk)
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    texto = (data.get('texto') or '').strip()
    creado_offline_en = data.get('creado_en', '')
    if not texto:
        return JsonResponse({'error': 'Texto vacío'}, status=400)

    comentario = Comentario.objects.create(
        incidencia=incidencia,
        autor=request.user,
        texto=f"{texto} [Sincronizado offline {creado_offline_en}]".strip(),
    )
    return JsonResponse({
        'id': comentario.id,
        'autor': request.user.username,
        'texto': comentario.texto,
        'fecha': comentario.fecha_creacion.strftime('%d/%m/%Y %H:%M'),
    }, status=201)


def pwa_manifest(request):
    """Manifiesto PWA para instalar VecinosApp en móvil/escritorio del técnico."""
    manifest = {
        "name": "VecinosApp Técnicos",
        "short_name": "VecinosApp",
        "start_url": "/incidencias/",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#2563eb",
        "icons": [
            {
                "src": "https://cdn-icons-png.flaticon.com/512/1048/1048953.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }
    return JsonResponse(manifest, content_type='application/manifest+json')


def pwa_service_worker(request):
    """Service Worker mínimo para caché offline de activos y vistas críticas del técnico."""
    sw_code = """
const CACHE_NAME = 'vecinosapp-tecnico-v1';
const ASSETS_TO_CACHE = ['/incidencias/', '/manifest.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS_TO_CACHE)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
"""
    return HttpResponse(sw_code.strip(), content_type='application/javascript')