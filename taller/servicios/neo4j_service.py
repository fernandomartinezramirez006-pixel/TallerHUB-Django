"""
Todo el uso de Neo4j de TallerHub está en este fichero.

Modelo de grafo:
  (:Modelo {nombre})       p. ej. "Seat Ibiza"
  (:Averia {nombre})       p. ej. "Frenos desgastados"
  (:Pieza  {ref, nombre})  p. ej. "FRN-001 Pastillas de freno"
  (:Reparacion {orden_id}) una orden de trabajo cerrada

  (:Reparacion)-[:EN_MODELO]->(:Modelo)
  (:Reparacion)-[:POR_AVERIA]->(:Averia)
  (:Reparacion)-[:USO {cantidad}]->(:Pieza)

Sincronización: cuando se cierra una orden en PostgreSQL, se crea su
(:Reparacion) en el grafo con MERGE (idempotente: repetirlo no duplica).
Si el grafo se pierde, se reconstruye entero con:
    python manage.py sincronizar_grafo

Recomendación (basada en contenido/historial): "para este MODELO con esta
AVERÍA, ¿qué piezas se usaron en reparaciones parecidas?". Si no hay
historial de ese modelo, se cae a la avería en cualquier modelo.
"""
from django.conf import settings
from neo4j import GraphDatabase

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
    return _driver


def crear_restricciones():
    """Claves únicas en el grafo (también crean índice)."""
    consultas = [
        "CREATE CONSTRAINT modelo_nombre IF NOT EXISTS FOR (m:Modelo) REQUIRE m.nombre IS UNIQUE",
        "CREATE CONSTRAINT averia_nombre IF NOT EXISTS FOR (a:Averia) REQUIRE a.nombre IS UNIQUE",
        "CREATE CONSTRAINT pieza_ref IF NOT EXISTS FOR (p:Pieza) REQUIRE p.ref IS UNIQUE",
        "CREATE CONSTRAINT reparacion_id IF NOT EXISTS FOR (r:Reparacion) REQUIRE r.orden_id IS UNIQUE",
    ]
    with get_driver().session() as s:
        for c in consultas:
            s.run(c)


CYPHER_SINCRONIZAR_ORDEN = """
MERGE (m:Modelo {nombre: $modelo})
MERGE (a:Averia {nombre: $averia})
MERGE (r:Reparacion {orden_id: $orden_id})
MERGE (r)-[:EN_MODELO]->(m)
MERGE (r)-[:POR_AVERIA]->(a)
WITH r
UNWIND $piezas AS p
  MERGE (pz:Pieza {ref: p.ref})
    SET pz.nombre = p.nombre
  MERGE (r)-[u:USO]->(pz)
    SET u.cantidad = p.cantidad
"""


def sincronizar_orden(orden):
    """Lleva una orden CERRADA de PostgreSQL al grafo."""
    piezas = [
        {"ref": l.pieza.referencia, "nombre": l.pieza.nombre, "cantidad": l.cantidad}
        for l in orden.lineas.select_related("pieza")
    ]
    try:
        with get_driver().session() as s:
            s.run(
                CYPHER_SINCRONIZAR_ORDEN,
                modelo=orden.vehiculo.modelo_completo,
                averia=orden.averia.nombre,
                orden_id=orden.pk,
                piezas=piezas,
            )
    except Exception as e:  # noqa: BLE001
        # El grafo es un dato DERIVADO: si falla, se puede reconstruir después.
        print(f"[neo4j] No se pudo sincronizar la orden {orden.pk}: {e}")


CYPHER_SUGERIR_PIEZAS = """
MATCH (:Modelo {nombre: $modelo})<-[:EN_MODELO]-(r:Reparacion)-[:POR_AVERIA]->(:Averia {nombre: $averia})
MATCH (r)-[u:USO]->(p:Pieza)
RETURN p.ref AS ref, p.nombre AS nombre,
       count(DISTINCT r) AS veces, sum(u.cantidad) AS unidades
ORDER BY veces DESC, unidades DESC
LIMIT 5
"""

CYPHER_SUGERIR_PIEZAS_GENERAL = """
MATCH (r:Reparacion)-[:POR_AVERIA]->(:Averia {nombre: $averia})
MATCH (r)-[u:USO]->(p:Pieza)
RETURN p.ref AS ref, p.nombre AS nombre,
       count(DISTINCT r) AS veces, sum(u.cantidad) AS unidades
ORDER BY veces DESC, unidades DESC
LIMIT 5
"""


def sugerir_piezas(modelo, averia):
    """
    Devuelve (lista_de_sugerencias, criterio).
    criterio = 'mismo modelo' o 'cualquier modelo' (si no hay historial del modelo).
    """
    try:
        with get_driver().session() as s:
            filas = s.run(CYPHER_SUGERIR_PIEZAS, modelo=modelo, averia=averia).data()
            if filas:
                return filas, "mismo modelo y avería"
            filas = s.run(CYPHER_SUGERIR_PIEZAS_GENERAL, averia=averia).data()
            return filas, "misma avería en cualquier modelo"
    except Exception as e:  # noqa: BLE001
        print(f"[neo4j] Error al sugerir piezas: {e}")
        return [], "Neo4j no disponible"


CYPHER_AVERIAS_FRECUENTES = """
MATCH (:Modelo {nombre: $modelo})<-[:EN_MODELO]-(r:Reparacion)-[:POR_AVERIA]->(a:Averia)
RETURN a.nombre AS averia, count(r) AS veces
ORDER BY veces DESC
LIMIT 5
"""


def averias_frecuentes(modelo):
    """Averías más repetidas en un modelo (se muestran en la ficha del vehículo)."""
    try:
        with get_driver().session() as s:
            return s.run(CYPHER_AVERIAS_FRECUENTES, modelo=modelo).data()
    except Exception as e:  # noqa: BLE001
        print(f"[neo4j] Error: {e}")
        return []


def borrar_grafo():
    with get_driver().session() as s:
        s.run("MATCH (n) DETACH DELETE n")


def ping():
    get_driver().verify_connectivity()
    return True
