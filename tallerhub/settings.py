"""
Configuración de TallerHub.

Todas las conexiones se leen de variables de entorno (fichero .env),
así el mismo código funciona en Docker y en otro equipo.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "solo-para-desarrollo")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "taller",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "tallerhub.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "taller.context_processors.rol",
            ],
        },
    },
]

WSGI_APPLICATION = "tallerhub.wsgi.application"

# ---------------------------------------------------------------------------
# 1) PostgreSQL: base de datos PRINCIPAL (fuente de verdad), vía el ORM.
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "tallerhub"),
        "USER": os.getenv("POSTGRES_USER", "tallerhub"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "tallerhub"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

# ---------------------------------------------------------------------------
# 2) Redis: sesiones de usuario (a través de la caché de Django).
#    La caché de consultas, OTP e intentos de login usan redis-py
#    directamente en taller/servicios/redis_service.py (claves explícitas).
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.cache"   # sesiones en Redis
SESSION_COOKIE_AGE = 60 * 60 * 8                            # 8 horas (una jornada)

# ---------------------------------------------------------------------------
# 3) MongoDB: eventos de actividad, fichas de revisión y dashboard (PyMongo).
# ---------------------------------------------------------------------------
MONGO_URI = "mongodb://{u}:{p}@{h}:{port}/?authSource=admin".format(
    u=os.getenv("MONGO_USER", "tallerhub"),
    p=os.getenv("MONGO_PASSWORD", "tallerhub"),
    h=os.getenv("MONGO_HOST", "localhost"),
    port=os.getenv("MONGO_PORT", "27017"),
)
MONGO_DB = os.getenv("MONGO_DB", "tallerhub")

# ---------------------------------------------------------------------------
# 4) Neo4j: grafo Modelo - Avería - Pieza para sugerencias (driver oficial).
# ---------------------------------------------------------------------------
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "tallerhub123")

# ---------------------------------------------------------------------------
# Parámetros de negocio relacionados con Redis
# ---------------------------------------------------------------------------
TTL_CACHE_HISTORIAL = 300        # 5 min: historial de un vehículo
TTL_CACHE_STOCK = 120            # 2 min: listado de stock
TTL_OTP = 300                    # 5 min: validez del código OTP
MAX_INTENTOS_LOGIN = 5           # intentos fallidos antes de bloquear
TTL_BLOQUEO_LOGIN = 900          # 15 min de bloqueo

AUTH_PASSWORD_VALIDATORS = []    # proyecto académico: contraseñas de prueba simples

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "es-es"
TIME_ZONE = "Europe/Madrid"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
