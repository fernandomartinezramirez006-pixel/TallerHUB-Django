"""
Todo el uso de MongoDB de TallerHub está en este fichero (PyMongo).

Colecciones:
  eventos           -> registro de actividad: cada pieza usada, cada orden abierta/cerrada...
                       Alimenta el dashboard con agregaciones.
  fichas_revision   -> fichas de revisión con campos VARIABLES según el vehículo
                       (un diésel tiene filtro de partículas, un eléctrico batería...).
                       CRUD completo desde la web.

¿Por qué Mongo y no PostgreSQL? Los eventos crecen sin parar y las fichas
no tienen una estructura fija: en tablas habría que crear columnas vacías
o tablas clave-valor incómodas.
"""
from datetime import datetime, timedelta, timezone as dt_tz

from bson import ObjectId
from django.conf import settings
from pymongo import DESCENDING, MongoClient

_cliente = None


def get_db():
    global _cliente
    if _cliente is None:
        _cliente = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=3000)
    return _cliente[settings.MONGO_DB]


def crear_indices():
    db = get_db()
    db.eventos.create_index([("fecha", DESCENDING)])
    db.eventos.create_index("tipo")
    db.fichas_revision.create_index("vehiculo_id")


# ---------------------------------------------------------------------------
# EVENTOS (registro de actividad)
# ---------------------------------------------------------------------------
def registrar_evento(tipo, usuario, datos=None, fecha=None):
    """
    CREATE: inserta un evento. Ejemplo de documento:
    {
      "tipo": "pieza_usada",
      "usuario": "mecanico1",
      "fecha": ISODate(...),
      "datos": {"orden_id": 12, "pieza_ref": "FRN-001", "pieza": "Pastillas de freno",
                "cantidad": 2, "matricula": "1234ABC"}
    }
    No debe romper la app si Mongo falla: el dato bueno ya está en PostgreSQL.
    """
    try:
        get_db().eventos.insert_one({
            "tipo": tipo,
            "usuario": usuario,
            "fecha": fecha or datetime.now(dt_tz.utc),
            "datos": datos or {},
        })
    except Exception as e:  # noqa: BLE001
        print(f"[mongo] No se pudo registrar el evento: {e}")


def ultimos_eventos(limite=15):
    """READ: últimos eventos para el dashboard."""
    return list(get_db().eventos.find({}, {"_id": 0}).sort("fecha", DESCENDING).limit(limite))


# ---------------------------------------------------------------------------
# DASHBOARD (agregaciones)
# ---------------------------------------------------------------------------
def _renombrar_id(resultados):
    """Las plantillas de Django no pueden leer '_id': lo renombramos a 'id'."""
    salida = []
    for doc in resultados:
        doc["id"] = doc.pop("_id")
        salida.append(doc)
    return salida


def consumo_por_mecanico(dias=30):
    """Piezas usadas por cada mecánico en los últimos N días."""
    desde = datetime.now(dt_tz.utc) - timedelta(days=dias)
    pipeline = [
        {"$match": {"tipo": "pieza_usada", "fecha": {"$gte": desde}}},
        {"$group": {"_id": "$usuario", "piezas": {"$sum": "$datos.cantidad"}, "usos": {"$sum": 1}}},
        {"$sort": {"piezas": -1}},
    ]
    return _renombrar_id(get_db().eventos.aggregate(pipeline))


def piezas_mas_usadas(limite=5):
    pipeline = [
        {"$match": {"tipo": "pieza_usada"}},
        {"$group": {"_id": "$datos.pieza", "total": {"$sum": "$datos.cantidad"}}},
        {"$sort": {"total": -1}},
        {"$limit": limite},
    ]
    return _renombrar_id(get_db().eventos.aggregate(pipeline))


def ordenes_cerradas_por_dia(dias=14):
    desde = datetime.now(dt_tz.utc) - timedelta(days=dias)
    pipeline = [
        {"$match": {"tipo": "orden_cerrada", "fecha": {"$gte": desde}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$fecha", "timezone": "Europe/Madrid"}},
            "ordenes": {"$sum": 1},
            "horas": {"$sum": "$datos.horas"},
        }},
        {"$sort": {"_id": 1}},
    ]
    return _renombrar_id(get_db().eventos.aggregate(pipeline))


# ---------------------------------------------------------------------------
# FICHAS DE REVISIÓN (CRUD completo con PyMongo)
# ---------------------------------------------------------------------------
def crear_ficha(vehiculo_id, matricula, usuario, kilometros, campos):
    """CREATE. 'campos' es un dict libre: cada ficha puede tener campos distintos."""
    doc = {
        "vehiculo_id": vehiculo_id,
        "matricula": matricula,
        "usuario": usuario,
        "fecha": datetime.now(dt_tz.utc),
        "kilometros": kilometros,
        "campos": campos,
    }
    return get_db().fichas_revision.insert_one(doc).inserted_id


def fichas_de_vehiculo(vehiculo_id):
    """READ (varias)."""
    fichas = list(get_db().fichas_revision.find({"vehiculo_id": vehiculo_id}).sort("fecha", DESCENDING))
    for f in fichas:
        f["id"] = str(f.pop("_id"))  # las plantillas de Django no aceptan "_id"
    return fichas


def obtener_ficha(ficha_id):
    """READ (una)."""
    ficha = get_db().fichas_revision.find_one({"_id": ObjectId(ficha_id)})
    if ficha:
        ficha["id"] = str(ficha.pop("_id"))
    return ficha


def actualizar_ficha(ficha_id, kilometros, campos):
    """UPDATE."""
    return get_db().fichas_revision.update_one(
        {"_id": ObjectId(ficha_id)},
        {"$set": {"kilometros": kilometros, "campos": campos, "modificada": datetime.now(dt_tz.utc)}},
    ).modified_count


def borrar_ficha(ficha_id):
    """DELETE."""
    return get_db().fichas_revision.delete_one({"_id": ObjectId(ficha_id)}).deleted_count


def ping():
    return get_db().command("ping")
