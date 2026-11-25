"""
Acciones de negocio: aquí se ve cómo colaboran las 4 bases de datos.

Regla de oro del proyecto:
  1. Primero se escribe en PostgreSQL (fuente de verdad), dentro de una transacción.
  2. Solo si la transacción se confirma (transaction.on_commit) se actualiza lo derivado:
       - Redis   -> se invalidan las cachés afectadas
       - MongoDB -> se registra el evento
       - Neo4j   -> se sincroniza el grafo (solo al cerrar la orden)
  Si Mongo o Neo4j fallan, el dato correcto sigue en PostgreSQL y se puede reconstruir.
"""
from django.db import transaction

from .models import OrdenTrabajo
from .servicios import mongo_service, neo4j_service, redis_service as rs


def abrir_orden(vehiculo, averia, mecanico, descripcion=""):
    with transaction.atomic():
        orden = OrdenTrabajo.objects.create(
            vehiculo=vehiculo, averia=averia, mecanico=mecanico, descripcion=descripcion
        )
        transaction.on_commit(lambda: _tras_abrir(orden))
    return orden


def _tras_abrir(orden):
    rs.invalidar(rs.clave_historial(orden.vehiculo_id))
    mongo_service.registrar_evento("orden_abierta", orden.mecanico.username, {
        "orden_id": orden.pk,
        "matricula": orden.vehiculo.matricula,
        "averia": orden.averia.nombre,
    })


def usar_pieza(orden, pieza_id, cantidad, usuario):
    """Descuenta stock (atómico en PostgreSQL) y deja rastro en Mongo."""
    pieza = orden.anadir_pieza(pieza_id, cantidad)   # puede lanzar StockInsuficiente
    rs.invalidar(rs.CLAVE_STOCK, rs.clave_historial(orden.vehiculo_id))
    mongo_service.registrar_evento("pieza_usada", usuario.username, {
        "orden_id": orden.pk,
        "matricula": orden.vehiculo.matricula,
        "pieza_ref": pieza.referencia,
        "pieza": pieza.nombre,
        "cantidad": cantidad,
    })
    if pieza.bajo_minimo:
        mongo_service.registrar_evento("alerta_stock", usuario.username, {
            "pieza_ref": pieza.referencia, "pieza": pieza.nombre, "stock": pieza.stock,
        })
    return pieza


def cerrar_orden(orden, horas, usuario):
    orden.cerrar(horas)
    rs.invalidar(rs.clave_historial(orden.vehiculo_id))
    mongo_service.registrar_evento("orden_cerrada", usuario.username, {
        "orden_id": orden.pk,
        "matricula": orden.vehiculo.matricula,
        "averia": orden.averia.nombre,
        "horas": float(horas),
    })
    neo4j_service.sincronizar_orden(orden)
