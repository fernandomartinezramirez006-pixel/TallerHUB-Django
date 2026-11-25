#!/bin/sh
# Se ejecuta al arrancar el contenedor "web".
set -e

echo ">> Aplicando migraciones en PostgreSQL..."
python manage.py migrate --noinput

echo ">> Arrancando Django en http://localhost:8000"
python manage.py runserver 0.0.0.0:8000
