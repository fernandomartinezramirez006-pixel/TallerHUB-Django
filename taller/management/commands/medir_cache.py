"""
Mide el tiempo de respuesta con y sin caché de Redis (para la tabla 11 de la memoria).

    docker compose exec web python manage.py medir_cache --repeticiones 200

Sin caché: se borra la clave antes de cada consulta (siempre MISS -> PostgreSQL).
Con caché: la clave ya está en Redis (siempre HIT).
"""
import statistics

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count

from taller.models import Vehiculo
from taller.servicios import redis_service as rs
from taller.views import consultar_historial, consultar_stock


class Command(BaseCommand):
    help = "Compara tiempos de respuesta sin caché (PostgreSQL) y con caché (Redis)"

    def add_arguments(self, parser):
        parser.add_argument("--repeticiones", type=int, default=200)

    def handle(self, *args, **opts):
        n = opts["repeticiones"]
        vehiculo = Vehiculo.objects.annotate(n=Count("ordenes")).order_by("-n").first()
        if not vehiculo:
            self.stdout.write(self.style.ERROR("No hay datos. Ejecuta antes cargar_datos_demo."))
            return

        casos = [
            (f"Historial del vehículo {vehiculo.matricula} ({vehiculo.n} órdenes)",
             rs.clave_historial(vehiculo.pk), settings.TTL_CACHE_HISTORIAL,
             lambda: consultar_historial(vehiculo.pk)),
            ("Listado de stock", rs.CLAVE_STOCK, settings.TTL_CACHE_STOCK, consultar_stock),
        ]

        self.stdout.write(f"\n{n} repeticiones por caso\n")
        self.stdout.write("| Consulta | Sin caché: media (ms) | Sin caché: p95 | Con caché: media (ms) | Con caché: p95 | Mejora |")
        self.stdout.write("|---|---|---|---|---|---|")
        for nombre, clave, ttl, consulta in casos:
            sin = []
            for _ in range(n):
                rs.invalidar(clave)                                    # fuerza MISS
                _, origen, ms = rs.obtener_con_cache(clave, ttl, consulta)
                assert origen == "postgres"
                sin.append(ms)
            con = []
            for _ in range(n):
                _, origen, ms = rs.obtener_con_cache(clave, ttl, consulta)  # siempre HIT
                assert origen == "redis"
                con.append(ms)
            media_sin, media_con = statistics.mean(sin), statistics.mean(con)
            self.stdout.write(
                f"| {nombre} | {media_sin:.2f} | {self._p95(sin):.2f} | {media_con:.2f} | "
                f"{self._p95(con):.2f} | x{media_sin / media_con:.1f} |"
            )
        self.stdout.write("")

    @staticmethod
    def _p95(valores):
        return sorted(valores)[int(len(valores) * 0.95) - 1]
