"""
Modelos de PostgreSQL: los datos de NEGOCIO (fuente de verdad).

Todo lo que importa que sea correcto y consistente vive aquí:
usuarios y roles, clientes, vehículos, piezas/stock y órdenes de trabajo.
Redis, MongoDB y Neo4j guardan copias o datos derivados de esto.
"""
from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone


class Perfil(models.Model):
    """Rol del usuario dentro del taller (amplía el User de Django)."""

    class Rol(models.TextChoices):
        JEFE = "JEFE", "Jefe / Administración"
        MECANICO = "MECANICO", "Mecánico"
        RECEPCION = "RECEPCION", "Recepción"

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil")
    rol = models.CharField(max_length=10, choices=Rol.choices)

    def __str__(self):
        return f"{self.usuario.username} ({self.get_rol_display()})"


class Cliente(models.Model):
    nombre = models.CharField(max_length=120)
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.nombre


class Vehiculo(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="vehiculos")
    matricula = models.CharField(max_length=10, unique=True)
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    anio = models.PositiveIntegerField("año")

    @property
    def modelo_completo(self):
        """Clave del modelo que se usa en el grafo de Neo4j (p. ej. 'Seat Ibiza')."""
        return f"{self.marca} {self.modelo}"

    def __str__(self):
        return f"{self.matricula} - {self.modelo_completo}"


class Averia(models.Model):
    """Catálogo de tipos de avería (p. ej. 'Frenos desgastados')."""
    nombre = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nombre


class Pieza(models.Model):
    referencia = models.CharField(max_length=30, unique=True)
    nombre = models.CharField(max_length=120)
    stock = models.PositiveIntegerField(default=0)
    stock_minimo = models.PositiveIntegerField(default=2)
    precio = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    @property
    def bajo_minimo(self):
        return self.stock <= self.stock_minimo

    def __str__(self):
        return f"{self.referencia} - {self.nombre}"


class StockInsuficiente(Exception):
    pass


class OrdenTrabajo(models.Model):
    class Estado(models.TextChoices):
        ABIERTA = "ABIERTA", "Abierta"
        CERRADA = "CERRADA", "Cerrada"

    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name="ordenes")
    mecanico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ordenes")
    averia = models.ForeignKey(Averia, on_delete=models.PROTECT, related_name="ordenes")
    descripcion = models.TextField(blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.ABIERTA)
    horas = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    fecha_apertura = models.DateTimeField(default=timezone.now)
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha_apertura"]

    def __str__(self):
        return f"OT-{self.pk} {self.vehiculo.matricula} ({self.estado})"

    # ------------------------------------------------------------------
    # Operaciones de negocio. Son TRANSACCIONES: o se hace todo o nada.
    # Este es el motivo principal de usar una BD relacional como base.
    # ------------------------------------------------------------------
    def anadir_pieza(self, pieza_id, cantidad):
        """Descuenta stock y añade la línea a la orden de forma atómica."""
        with transaction.atomic():
            # select_for_update bloquea la fila: si dos mecánicos cogen la
            # última pieza a la vez, uno de los dos espera y luego falla.
            pieza = Pieza.objects.select_for_update().get(pk=pieza_id)
            if pieza.stock < cantidad:
                raise StockInsuficiente(f"Solo quedan {pieza.stock} uds. de {pieza.nombre}")
            Pieza.objects.filter(pk=pieza.pk).update(stock=F("stock") - cantidad)
            linea, creada = LineaPieza.objects.get_or_create(orden=self, pieza=pieza, defaults={"cantidad": 0})
            linea.cantidad = F("cantidad") + cantidad
            linea.save()
        pieza.refresh_from_db()
        return pieza

    def cerrar(self, horas):
        with transaction.atomic():
            self.estado = self.Estado.CERRADA
            self.horas = horas
            self.fecha_cierre = timezone.now()
            self.save()


class LineaPieza(models.Model):
    """Pieza usada en una orden (tabla intermedia orden-pieza)."""
    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="lineas")
    pieza = models.ForeignKey(Pieza, on_delete=models.PROTECT, related_name="lineas")
    cantidad = models.PositiveIntegerField()

    class Meta:
        unique_together = ("orden", "pieza")

    def __str__(self):
        return f"{self.cantidad} x {self.pieza.nombre}"
