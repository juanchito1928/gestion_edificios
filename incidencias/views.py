from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Q, Prefetch
from django.db.models.functions import Greatest
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank, TrigramSimilarity

from .models import Incidencia, Comentario, EventoIncidencia, Perfil, Unidad, Organizacion, Edificio
from . import use_cases


def _obtener_rol(user):
    perfil = getattr(user, 'perfil', None)
    return getattr(perfil, 'rol', None)


class IncidenciaListView(LoginRequiredMixin, ListView):
    model = Incidencia
    template_name = 'incidencias/incidencia_list.html'
    context_object_name = 'incidencias'
    paginate_by = 25  # Evita cargar 100 000 filas en memoria en una sola petición

    def get_queryset(self):
        user = self.request.user
        rol = _obtener_rol(user)

        # select_related elimina consultas N+1 al acceder a edificio, unidad, reportado_por y tecnico
        qs = Incidencia.objects.select_related(
            'edificio',
            'unidad',
            'reportado_por',
            'tecnico_asignado__usuario',
        )

        # Filtro por rol (RLS + PorEdificioManager ya aíslan el edificio activo)
        if not (user.is_staff or user.is_superuser or rol in ['ADMIN_EDIFICIO', 'ADMIN', 'TECNICO', 'AUDITOR']):
            qs = qs.filter(reportado_por=user)

        # Filtro opcional por estado
        estado = (self.request.GET.get('estado') or '').strip()
        if estado:
            qs = qs.filter(estado=estado)

        # Búsqueda avanzada: Full-Text Search (SearchVector) + Trigramas tolerantes a errores (pg_trgm)
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
        # Cero N+1 en el detalle: precarga comentarios con autor y eventos con usuario_actor
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