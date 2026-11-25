"""
Carga datos de ejemplo en las 4 bases de datos.

    docker compose exec web python manage.py cargar_datos_demo --reset

- PostgreSQL: usuarios, clientes, vehículos, averías, piezas y ~90 órdenes históricas.
- MongoDB:    los eventos de esas órdenes (con sus fechas reales) y algunas fichas.
- Neo4j:      el grafo de reparaciones, construido a partir de las órdenes cerradas.
- Redis:      se vacía (las cachés se rellenan solas al navegar).
Usa una semilla fija: siempre genera los mismos datos.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from taller.models import Averia, Cliente, LineaPieza, OrdenTrabajo, Perfil, Pieza, Vehiculo
from taller.servicios import mongo_service, neo4j_service, redis_service

PIEZAS = [
    # referencia, nombre, stock, mínimo, precio
    ("FRN-001", "Pastillas de freno delanteras", 14, 4, 38.50),
    ("FRN-002", "Discos de freno delanteros", 6, 2, 72.00),
    ("FRN-003", "Líquido de frenos DOT4 1L", 3, 3, 9.90),
    ("MOT-001", "Aceite motor 5W30 5L", 20, 5, 41.00),
    ("MOT-002", "Filtro de aceite", 18, 5, 8.75),
    ("MOT-003", "Filtro de aire", 9, 3, 14.20),
    ("MOT-004", "Filtro de habitáculo", 7, 3, 12.60),
    ("MOT-005", "Bujías (juego de 4)", 5, 2, 31.00),
    ("ELE-001", "Batería 12V 70Ah", 2, 2, 98.00),
    ("ELE-002", "Alternador", 1, 1, 189.00),
    ("ELE-003", "Correa auxiliar", 6, 2, 22.40),
    ("EMB-001", "Kit de embrague", 2, 1, 245.00),
    ("EMB-002", "Volante bimasa", 1, 1, 410.00),
    ("SUS-001", "Amortiguador delantero", 4, 2, 86.00),
    ("SUS-002", "Amortiguador trasero", 4, 2, 64.00),
    ("SUS-003", "Copela de amortiguador", 6, 2, 27.50),
    ("DIS-001", "Kit de distribución", 2, 1, 168.00),
    ("DIS-002", "Bomba de agua", 3, 1, 59.00),
    ("INY-001", "Inyector diésel", 2, 2, 215.00),
    ("INY-002", "Juntas de inyector", 10, 4, 6.80),
    ("REF-001", "Anticongelante 5L", 8, 3, 17.90),
]

# Avería -> lista de (referencia, probabilidad de usarla, cantidad)
RECETAS = {
    "Frenos desgastados": [("FRN-001", .95, 1), ("FRN-002", .45, 1), ("FRN-003", .30, 1)],
    "Revisión y cambio de aceite": [("MOT-001", 1, 1), ("MOT-002", 1, 1), ("MOT-003", .5, 1), ("MOT-004", .4, 1)],
    "Batería agotada": [("ELE-001", .9, 1)],
    "Fallo de carga / alternador": [("ELE-002", .7, 1), ("ELE-003", .6, 1), ("ELE-001", .2, 1)],
    "Embrague patina": [("EMB-001", .95, 1), ("EMB-002", .35, 1)],
    "Amortiguación en mal estado": [("SUS-001", .8, 2), ("SUS-002", .5, 2), ("SUS-003", .6, 2)],
    "Correa de distribución": [("DIS-001", 1, 1), ("DIS-002", .8, 1), ("REF-001", .7, 1)],
    "Fallo de inyección diésel": [("INY-001", .8, 1), ("INY-002", .9, 4)],
    "Fallo de encendido": [("MOT-005", .9, 1), ("ELE-001", .2, 1)],
}

MODELOS = [
    ("Seat", "Ibiza"), ("Seat", "León"), ("Volkswagen", "Golf"), ("Renault", "Clio"),
    ("Peugeot", "208"), ("Toyota", "Corolla"), ("Ford", "Focus"), ("Citroën", "C4"),
]

# Para que el grafo tenga "personalidad": algunas averías son típicas de ciertos modelos
AVERIAS_TIPICAS = {
    "Seat León": ["Embrague patina", "Fallo de inyección diésel"],
    "Volkswagen Golf": ["Fallo de inyección diésel", "Correa de distribución"],
    "Renault Clio": ["Fallo de carga / alternador", "Batería agotada"],
    "Ford Focus": ["Embrague patina", "Amortiguación en mal estado"],
    "Peugeot 208": ["Fallo de encendido"],
}

NOMBRES = ["Ana López", "Juan García", "María Fernández", "Pedro Sánchez", "Lucía Romero", "Carlos Ruiz",
           "Elena Díaz", "Javier Moreno", "Laura Muñoz", "Antonio Álvarez", "Sara Jiménez", "Miguel Torres",
           "Paula Navarro", "David Gil", "Carmen Serrano", "Raúl Molina"]


class Command(BaseCommand):
    help = "Carga datos de ejemplo en PostgreSQL, MongoDB, Neo4j y limpia Redis"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Borra antes los datos existentes")

    def handle(self, *args, **opts):
        random.seed(42)
        if opts["reset"]:
            self._reset()
        elif OrdenTrabajo.objects.exists():
            self.stdout.write(self.style.WARNING("Ya hay datos. Usa --reset para regenerarlos."))
            return

        with transaction.atomic():
            usuarios = self._usuarios()
            vehiculos = self._clientes_y_vehiculos()
            averias = {nombre: Averia.objects.create(nombre=nombre) for nombre in RECETAS}
            piezas = {ref: Pieza.objects.create(referencia=ref, nombre=n, stock=s, stock_minimo=m, precio=Decimal(str(p)))
                      for ref, n, s, m, p in PIEZAS}
            ordenes = self._ordenes(usuarios["mecanicos"], vehiculos, averias, piezas)

        self._mongo(ordenes, vehiculos)
        self._neo4j(ordenes)
        redis_service.get_redis().flushdb()

        self.stdout.write(self.style.SUCCESS(
            f"Listo: {User.objects.count()} usuarios, {Vehiculo.objects.count()} vehículos, "
            f"{Pieza.objects.count()} piezas, {OrdenTrabajo.objects.count()} órdenes."
        ))
        self.stdout.write("Usuarios: jefe/jefe1234 · mecanico1..3/taller123 · recepcion/recepcion123")

    # ------------------------------------------------------------------
    def _reset(self):
        self.stdout.write("Borrando datos anteriores...")
        LineaPieza.objects.all().delete()
        OrdenTrabajo.objects.all().delete()
        Vehiculo.objects.all().delete()
        Cliente.objects.all().delete()
        Pieza.objects.all().delete()
        Averia.objects.all().delete()
        User.objects.all().delete()
        db = mongo_service.get_db()
        db.eventos.delete_many({})
        db.fichas_revision.delete_many({})
        neo4j_service.borrar_grafo()
        redis_service.get_redis().flushdb()

    def _usuarios(self):
        jefe = User.objects.create_superuser("jefe", "jefe@tallerhub.test", "jefe1234", first_name="Rafael")
        Perfil.objects.create(usuario=jefe, rol=Perfil.Rol.JEFE)

        recepcion = User.objects.create_user("recepcion", password="recepcion123", first_name="Rocío", is_staff=True)
        Perfil.objects.create(usuario=recepcion, rol=Perfil.Rol.RECEPCION)
        # Recepción puede gestionar clientes y vehículos desde el admin
        recepcion.user_permissions.set(Permission.objects.filter(
            content_type__app_label="taller", content_type__model__in=["cliente", "vehiculo"]))

        mecanicos = []
        for i, nombre in enumerate(["Manolo", "Isabel", "Kike"], start=1):
            m = User.objects.create_user(f"mecanico{i}", password="taller123", first_name=nombre)
            Perfil.objects.create(usuario=m, rol=Perfil.Rol.MECANICO)
            mecanicos.append(m)
        return {"jefe": jefe, "recepcion": recepcion, "mecanicos": mecanicos}

    def _clientes_y_vehiculos(self):
        vehiculos = []
        letras = "BCDFGHJKLMNPRSTVWXYZ"
        for nombre in NOMBRES:
            cliente = Cliente.objects.create(
                nombre=nombre, telefono=f"6{random.randint(10_000_000, 99_999_999)}",
                email=nombre.lower().split()[0] + "@correo.test")
            for _ in range(random.choice([1, 1, 2])):
                marca, modelo = random.choice(MODELOS)
                matricula = f"{random.randint(1000, 9999)}{''.join(random.choices(letras, k=3))}"
                vehiculos.append(Vehiculo.objects.create(
                    cliente=cliente, matricula=matricula, marca=marca, modelo=modelo,
                    anio=random.randint(2008, 2023)))
        return vehiculos

    def _ordenes(self, mecanicos, vehiculos, averias, piezas):
        ahora = timezone.now()
        ordenes = []
        for i in range(90):
            vehiculo = random.choice(vehiculos)
            tipicas = AVERIAS_TIPICAS.get(vehiculo.modelo_completo, [])
            if tipicas and random.random() < 0.55:
                nombre_averia = random.choice(tipicas)
            else:
                nombre_averia = random.choice(list(RECETAS))
            apertura = ahora - timedelta(days=random.randint(1, 60), hours=random.randint(0, 8))
            abierta = i >= 86  # las 4 últimas quedan abiertas
            orden = OrdenTrabajo.objects.create(
                vehiculo=vehiculo, averia=averias[nombre_averia], mecanico=random.choice(mecanicos),
                estado=OrdenTrabajo.Estado.ABIERTA if abierta else OrdenTrabajo.Estado.CERRADA,
                horas=Decimal("0") if abierta else Decimal(str(random.choice([0.5, 1, 1.5, 2, 3, 4, 6]))),
                fecha_apertura=apertura if not abierta else ahora - timedelta(hours=random.randint(1, 5)),
                fecha_cierre=None if abierta else apertura + timedelta(hours=random.randint(2, 30)),
            )
            if not abierta:
                for ref, prob, cantidad in RECETAS[nombre_averia]:
                    if random.random() < prob:
                        LineaPieza.objects.create(orden=orden, pieza=piezas[ref], cantidad=cantidad)
            ordenes.append(orden)
        return ordenes

    def _mongo(self, ordenes, vehiculos):
        self.stdout.write("MongoDB: índices, eventos y fichas...")
        mongo_service.crear_indices()
        for o in ordenes:
            mongo_service.registrar_evento("orden_abierta", o.mecanico.username, {
                "orden_id": o.pk, "matricula": o.vehiculo.matricula, "averia": o.averia.nombre,
            }, fecha=o.fecha_apertura)
            for l in o.lineas.select_related("pieza"):
                mongo_service.registrar_evento("pieza_usada", o.mecanico.username, {
                    "orden_id": o.pk, "matricula": o.vehiculo.matricula, "pieza_ref": l.pieza.referencia,
                    "pieza": l.pieza.nombre, "cantidad": l.cantidad,
                }, fecha=o.fecha_apertura + timedelta(hours=1))
            if o.estado == OrdenTrabajo.Estado.CERRADA:
                mongo_service.registrar_evento("orden_cerrada", o.mecanico.username, {
                    "orden_id": o.pk, "matricula": o.vehiculo.matricula, "averia": o.averia.nombre,
                    "horas": float(o.horas),
                }, fecha=o.fecha_cierre)

        # Fichas con estructura distinta según el tipo de vehículo
        for v in vehiculos[:8]:
            campos = {"aceite": "cambiado 5W30", "filtro_aire": "OK",
                      "neumaticos_delanteros": f"{random.randint(2, 7)} mm", "luces": "OK"}
            if v.modelo_completo in ("Seat León", "Volkswagen Golf", "Citroën C4"):
                campos["filtro_particulas"] = random.choice(["limpio", "saturado 60%"])
                campos["adblue"] = "nivel correcto"
            if v.modelo_completo == "Toyota Corolla":
                campos["bateria_hibrida"] = f"{random.randint(85, 98)}% salud"
                campos["modo_ev"] = "funciona correctamente"
            mongo_service.crear_ficha(v.pk, v.matricula, "mecanico1", random.randint(20_000, 220_000), campos)

    def _neo4j(self, ordenes):
        self.stdout.write("Neo4j: construyendo el grafo...")
        neo4j_service.crear_restricciones()
        for o in ordenes:
            if o.estado == OrdenTrabajo.Estado.CERRADA:
                neo4j_service.sincronizar_orden(o)
