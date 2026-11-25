"""
Todo el uso de Redis de TallerHub está en este fichero.

Claves que usamos:
  cache:historial:vehiculo:<id>   STRING (JSON)  TTL 300 s   caché del historial de un vehículo
  cache:stock                     STRING (JSON)  TTL 120 s   caché del listado de stock
  otp:usuario:<id>                STRING         TTL 300 s   código OTP de 6 dígitos del login
  login:intentos:<username>       STRING (int)   TTL 900 s   contador de intentos fallidos
  (+ sesiones de Django, que se guardan solas vía SESSION_ENGINE)

Estrategia de caché: "cache-aside"
  1. Busco la clave en Redis -> si está (HIT), la devuelvo.
  2. Si no está (MISS), consulto PostgreSQL, guardo el resultado con TTL y lo devuelvo.
  3. Cuando el dato cambia en PostgreSQL, BORRO la clave (invalidación) -> ver signals.py.
"""
import json
import secrets
import time

import redis
from django.conf import settings

_cliente = None


def get_redis():
    """Una única conexión reutilizable (redis-py gestiona un pool por dentro)."""
    global _cliente
    if _cliente is None:
        _cliente = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _cliente


# ---------------------------------------------------------------------------
# 1) CACHÉ DE CONSULTAS
# ---------------------------------------------------------------------------
def clave_historial(vehiculo_id):
    return f"cache:historial:vehiculo:{vehiculo_id}"


CLAVE_STOCK = "cache:stock"


def obtener_con_cache(clave, ttl, funcion_consulta):
    """
    Cache-aside genérico.
    Devuelve (datos, origen, milisegundos) donde origen es 'redis' o 'postgres'.
    """
    inicio = time.perf_counter()
    r = get_redis()
    guardado = r.get(clave)
    if guardado is not None:                       # HIT
        datos = json.loads(guardado)
        origen = "redis"
    else:                                          # MISS
        datos = funcion_consulta()
        r.set(clave, json.dumps(datos, default=str), ex=ttl)
        origen = "postgres"
    ms = (time.perf_counter() - inicio) * 1000
    return datos, origen, round(ms, 2)


def invalidar(*claves):
    if claves:
        get_redis().delete(*claves)


# ---------------------------------------------------------------------------
# 2) CÓDIGOS OTP (segundo paso del login)
# ---------------------------------------------------------------------------
def generar_otp(usuario_id):
    """Genera un código de 6 dígitos y lo guarda con caducidad automática."""
    codigo = f"{secrets.randbelow(1_000_000):06d}"
    get_redis().set(f"otp:usuario:{usuario_id}", codigo, ex=settings.TTL_OTP)
    return codigo


def verificar_otp(usuario_id, codigo):
    """True si el código es correcto. Se borra al usarlo (un solo uso)."""
    r = get_redis()
    clave = f"otp:usuario:{usuario_id}"
    guardado = r.get(clave)
    if guardado is not None and secrets.compare_digest(guardado, codigo.strip()):
        r.delete(clave)
        return True
    return False


def ttl_otp(usuario_id):
    """Segundos que le quedan al OTP (-2 si ya no existe)."""
    return get_redis().ttl(f"otp:usuario:{usuario_id}")


# ---------------------------------------------------------------------------
# 3) LIMITAR INTENTOS DE LOGIN (anti fuerza bruta)
# ---------------------------------------------------------------------------
def _clave_intentos(username):
    return f"login:intentos:{username.lower()}"


def login_bloqueado(username):
    intentos = get_redis().get(_clave_intentos(username))
    return intentos is not None and int(intentos) >= settings.MAX_INTENTOS_LOGIN


def registrar_fallo_login(username):
    """INCR es atómico; el TTL hace que el bloqueo se quite solo."""
    r = get_redis()
    clave = _clave_intentos(username)
    intentos = r.incr(clave)
    if intentos == 1:
        r.expire(clave, settings.TTL_BLOQUEO_LOGIN)
    return intentos


def limpiar_intentos(username):
    get_redis().delete(_clave_intentos(username))


def ping():
    return get_redis().ping()
