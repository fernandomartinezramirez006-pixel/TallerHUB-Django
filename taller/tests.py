"""
Pruebas automáticas (sirven de evidencia para la sección 10 de la memoria).

    docker compose exec web python manage.py test taller -v 2

Necesitan PostgreSQL y Redis levantados (Django crea una BD de test aparte).
"""
import time

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from . import acciones
from .models import Averia, Cliente, OrdenTrabajo, Perfil, Pieza, StockInsuficiente, Vehiculo
from .servicios import redis_service as rs


class BaseTaller(TestCase):
    def setUp(self):
        rs.get_redis().flushdb()
        self.mecanico = User.objects.create_user("mec_test", password="clave123")
        Perfil.objects.create(usuario=self.mecanico, rol=Perfil.Rol.MECANICO)
        cliente = Cliente.objects.create(nombre="Cliente Test")
        self.vehiculo = Vehiculo.objects.create(cliente=cliente, matricula="0000TST", marca="Seat",
                                                modelo="Ibiza", anio=2018)
        self.averia = Averia.objects.create(nombre="Frenos desgastados")
        self.pieza = Pieza.objects.create(referencia="T-001", nombre="Pastillas test", stock=3, stock_minimo=1)


class PruebasRedis(BaseTaller):
    def test_P1_segunda_consulta_sale_de_redis(self):
        """P1. Caché: la primera consulta va a PostgreSQL, la segunda a Redis."""
        clave = rs.clave_historial(self.vehiculo.pk)
        _, origen1, _ = rs.obtener_con_cache(clave, 60, lambda: ["dato"])
        _, origen2, _ = rs.obtener_con_cache(clave, 60, lambda: ["dato"])
        self.assertEqual(origen1, "postgres")
        self.assertEqual(origen2, "redis")
        self.assertGreater(rs.get_redis().ttl(clave), 0)

    def test_P1b_invalidacion_al_cambiar_stock(self):
        """Al modificar una pieza (signal post_save) se borra la caché del stock."""
        rs.get_redis().set(rs.CLAVE_STOCK, "[]")
        self.pieza.stock = 10
        self.pieza.save()
        self.assertIsNone(rs.get_redis().get(rs.CLAVE_STOCK))

    @override_settings(TTL_OTP=1)
    def test_P2_otp_caduca(self):
        """P2. OTP: el código deja de valer cuando se agota el TTL."""
        codigo = rs.generar_otp(self.mecanico.pk)
        time.sleep(1.5)
        self.assertFalse(rs.verificar_otp(self.mecanico.pk, codigo))

    def test_P2b_otp_es_de_un_solo_uso(self):
        codigo = rs.generar_otp(self.mecanico.pk)
        self.assertTrue(rs.verificar_otp(self.mecanico.pk, codigo))
        self.assertFalse(rs.verificar_otp(self.mecanico.pk, codigo))

    def test_bloqueo_tras_5_fallos(self):
        for _ in range(5):
            self.client.post("/login/", {"username": "mec_test", "password": "mala"})
        self.assertTrue(rs.login_bloqueado("mec_test"))
        # Aunque ahora la contraseña sea correcta, sigue bloqueado
        r = self.client.post("/login/", {"username": "mec_test", "password": "clave123"})
        self.assertContains(r, "bloqueado")


class PruebasPostgres(BaseTaller):
    def test_descuento_de_stock(self):
        orden = OrdenTrabajo.objects.create(vehiculo=self.vehiculo, mecanico=self.mecanico, averia=self.averia)
        acciones.usar_pieza(orden, self.pieza.pk, 2, self.mecanico)
        self.pieza.refresh_from_db()
        self.assertEqual(self.pieza.stock, 1)

    def test_no_se_puede_usar_mas_stock_del_que_hay(self):
        """La transacción se deshace: ni se descuenta stock ni se crea la línea."""
        orden = OrdenTrabajo.objects.create(vehiculo=self.vehiculo, mecanico=self.mecanico, averia=self.averia)
        with self.assertRaises(StockInsuficiente):
            acciones.usar_pieza(orden, self.pieza.pk, 99, self.mecanico)
        self.pieza.refresh_from_db()
        self.assertEqual(self.pieza.stock, 3)
        self.assertFalse(orden.lineas.exists())


class PruebasLogin(BaseTaller):
    def test_login_en_dos_pasos(self):
        r = self.client.post("/login/", {"username": "mec_test", "password": "clave123"})
        self.assertRedirects(r, "/login/otp/")
        codigo = rs.get_redis().get(f"otp:usuario:{self.mecanico.pk}")
        r = self.client.post("/login/otp/", {"codigo": codigo})
        self.assertRedirects(r, "/")
