"""
Reconstruye el grafo de Neo4j desde cero a partir de PostgreSQL.

    docker compose exec web python manage.py sincronizar_grafo

Demuestra que PostgreSQL es la fuente de verdad: el grafo es un dato
derivado y, si se pierde o se desincroniza, se regenera entero.
"""
from django.core.management.base import BaseCommand

from taller.models import OrdenTrabajo
from taller.servicios import neo4j_service


class Command(BaseCommand):
    help = "Borra y reconstruye el grafo de Neo4j desde PostgreSQL"

    def handle(self, *args, **opts):
        neo4j_service.borrar_grafo()
        neo4j_service.crear_restricciones()
        cerradas = (OrdenTrabajo.objects.filter(estado=OrdenTrabajo.Estado.CERRADA)
                    .select_related("vehiculo", "averia"))
        for o in cerradas:
            neo4j_service.sincronizar_orden(o)
        with neo4j_service.get_driver().session() as s:
            nodos = s.run("MATCH (n) RETURN labels(n)[0] AS tipo, count(*) AS n ORDER BY tipo").data()
        self.stdout.write(self.style.SUCCESS(f"{cerradas.count()} reparaciones sincronizadas."))
        for fila in nodos:
            self.stdout.write(f"  {fila['tipo']}: {fila['n']} nodos")
