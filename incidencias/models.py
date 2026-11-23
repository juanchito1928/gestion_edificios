from django.db import models
from django.db.models import Q, CheckConstraint, UniqueConstraint, Index
from django.contrib.auth.models import User
from django.contrib.postgres.indexes import GinIndex
from .tenant import PorEdificioManager, TodosLosEdificiosManager


class Organizacion(models.Model):
    nombre = models.CharField(max_length=150)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre


class Edificio(models.Model):
    organizacion = models.ForeignKey(Organizacion, on_delete=models.CASCADE, related_name='edificios')
    nombre = models.CharField(max_length=150)
    direccion = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.organizacion.nombre})"


class Unidad(models.Model):
    edificio = models.ForeignKey(Edificio, on_delete=models.CASCADE, related_name='unidades')
    torre = models.CharField(max_length=80, default='Torre Principal')
    numero = models.CharField(max_length=50)
    es_area_comun = models.BooleanField(default=False)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=['edificio', 'torre', 'numero'],
                name='uq_unidad_edificio_torre_numero'
            )
        ]

    def __str__(self):
        if self.es_area_comun:
            return f"Área Común - {self.numero} ({self.edificio.nombre})"
        return f"{self.torre} - {self.numero} ({self.edificio.nombre})"


class RolUsuario(models.TextChoices):
    RESIDENTE = 'RESIDENTE', 'Residente'
    ADMIN_EDIFICIO = 'ADMIN_EDIFICIO', 'Administrador de edificio'
    TECNICO = 'TECNICO', 'Técnico'
    AUDITOR = 'AUDITOR', 'Auditor'


class Perfil(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    edificio = models.ForeignKey(
        Edificio,
        on_delete=models.PROTECT,
        related_name='perfiles',
        null=True,
        blank=True,
    )
    unidad = models.ForeignKey(
        Unidad,
        on_delete=models.SET_NULL,
        related_name='perfiles',
        null=True,
        blank=True,
    )
    rol = models.CharField(
        max_length=20,
        choices=RolUsuario.choices,
        default=RolUsuario.RESIDENTE,
    )
    edificio_texto = models.CharField(max_length=100, default='Edificio Principal', blank=True)
    piso_puerta = models.CharField(max_length=100, default='Sin especificar')

    def __str__(self):
        nombre_edificio = self.edificio.nombre if self.edificio else self.edificio_texto
        return f"Perfil de {self.usuario.username} [{self.get_rol_display()}] - {nombre_edificio}"


class Tecnico(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='tecnico')
    especialidad = models.CharField(max_length=100, blank=True, null=True)
    edificios_asignados = models.ManyToManyField(Edificio, related_name='tecnicos', blank=True)

    def __str__(self):
        return self.usuario.username


class Incidencia(models.Model):
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('EN_PROCESO', 'En Proceso'),
        ('RESUELTA', 'Resuelta'),
        ('CERRADA', 'Cerrada'),
    ]

    edificio = models.ForeignKey(
        Edificio,
        on_delete=models.CASCADE,
        related_name='incidencias',
        null=True,
        blank=True,
    )
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField()
    categoria = models.CharField(max_length=100, blank=True, null=True)
    prioridad = models.CharField(max_length=50, blank=True, null=True)
    foto = models.ImageField(upload_to='incidencias/', blank=True, null=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')

    tiempo_estimado = models.CharField(max_length=100, blank=True, null=True)
    instrucciones_tecnico = models.TextField(blank=True, null=True)
    fecha_asignacion = models.DateTimeField(null=True, blank=True)

    version = models.PositiveIntegerField(default=1)

    unidad = models.ForeignKey(Unidad, on_delete=models.CASCADE, related_name='incidencias', null=True, blank=True)
    reportado_por = models.ForeignKey(User, on_delete=models.CASCADE, related_name='incidencias_reportadas')
    tecnico_asignado = models.ForeignKey(Tecnico, on_delete=models.SET_NULL, null=True, blank=True, related_name='incidencias_asignadas')

    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    objects = PorEdificioManager()
    sin_filtro = TodosLosEdificiosManager()

    class Meta:
        indexes = [
            Index(fields=['edificio', '-fecha_creacion'], name='idx_inc_edif_fecha'),
            Index(fields=['edificio', 'estado', '-fecha_creacion'], name='idx_inc_edif_est_fecha'),
            Index(
                fields=['edificio', 'tecnico_asignado', 'fecha_creacion'],
                name='idx_inc_abiertas_parcial',
                condition=Q(estado__in=['PENDIENTE', 'EN_PROCESO']),
            ),
            GinIndex(
                name='idx_inc_titulo_trgm',
                fields=['titulo'],
                opclasses=['gin_trgm_ops'],
            ),
            GinIndex(
                name='idx_inc_desc_trgm',
                fields=['descripcion'],
                opclasses=['gin_trgm_ops'],
            ),
        ]
        constraints = [
            CheckConstraint(
                condition=Q(estado__in=['PENDIENTE', 'EN_PROCESO', 'RESUELTA', 'CERRADA']),
                name='chk_incidencia_estado_valido',
            ),
            CheckConstraint(
                condition=Q(version__gte=1),
                name='chk_incidencia_version_positiva',
            ),
            UniqueConstraint(
                fields=['unidad', 'titulo'],
                condition=Q(estado__in=['PENDIENTE', 'EN_PROCESO']),
                name='uq_incidencia_abierta_unidad_titulo',
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.edificio_id:
            if self.unidad_id and self.unidad.edificio_id:
                self.edificio_id = self.unidad.edificio_id
            elif hasattr(self.reportado_por, 'perfil') and self.reportado_por.perfil.edificio_id:
                self.edificio_id = self.reportado_por.perfil.edificio_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.estado}] {self.titulo}"


class Comentario(models.Model):
    edificio = models.ForeignKey(
        Edificio,
        on_delete=models.CASCADE,
        related_name='comentarios',
        null=True,
        blank=True,
    )
    incidencia = models.ForeignKey(Incidencia, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(User, on_delete=models.CASCADE)
    texto = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    objects = PorEdificioManager()
    sin_filtro = TodosLosEdificiosManager()

    class Meta:
        indexes = [
            Index(fields=['incidencia', 'fecha_creacion'], name='idx_com_incidencia_fecha'),
        ]

    def save(self, *args, **kwargs):
        if not self.edificio_id and self.incidencia_id:
            self.edificio_id = self.incidencia.edificio_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Comentario de {self.autor.username} en {self.incidencia}"


class EventoIncidencia(models.Model):
    incidencia = models.ForeignKey(Incidencia, on_delete=models.CASCADE, related_name='eventos')
    tipo_evento = models.CharField(max_length=100)
    datos_previos = models.JSONField(null=True, blank=True)
    datos_nuevos = models.JSONField(null=True, blank=True)
    usuario_actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    fecha_evento = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            Index(fields=['incidencia', 'fecha_evento'], name='idx_evt_incidencia_fecha'),
        ]

    def __str__(self):
        return f"{self.tipo_evento} Incidencia {self.incidencia_id} ({self.fecha_evento})"


class RegistroAcceso(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    edificio = models.ForeignKey(Edificio, on_delete=models.SET_NULL, null=True, blank=True)
    ruta = models.CharField(max_length=255)
    metodo = models.CharField(max_length=10)
    codigo_estado = models.PositiveSmallIntegerField()
    ip_origen = models.GenericIPAddressField(null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f"[{self.fecha}] {self.usuario} -> {self.metodo} {self.ruta} ({self.codigo_estado})"