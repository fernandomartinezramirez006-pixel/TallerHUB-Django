"""
Invalidación de caché cuando los datos se cambian desde el ADMIN de Django
(p. ej. recepción da de alta un vehículo o el jefe repone stock).

post_save / post_delete se disparan al guardar o borrar con el ORM.
OJO: un queryset.update() NO dispara señales; por eso en acciones.py
se invalida también a mano después de descontar stock.
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import LineaPieza, OrdenTrabajo, Pieza, Vehiculo
from .servicios import redis_service as rs


@receiver([post_save, post_delete], sender=Pieza)
def invalidar_stock(sender, **kwargs):
    rs.invalidar(rs.CLAVE_STOCK)


@receiver([post_save, post_delete], sender=OrdenTrabajo)
def invalidar_historial_por_orden(sender, instance, **kwargs):
    rs.invalidar(rs.clave_historial(instance.vehiculo_id))


@receiver([post_save, post_delete], sender=LineaPieza)
def invalidar_historial_por_linea(sender, instance, **kwargs):
    rs.invalidar(rs.clave_historial(instance.orden.vehiculo_id), rs.CLAVE_STOCK)


@receiver([post_save, post_delete], sender=Vehiculo)
def invalidar_historial_vehiculo(sender, instance, **kwargs):
    rs.invalidar(rs.clave_historial(instance.pk))
