"""
El admin de Django nos da el CRUD de PostgreSQL gratis:
recepción da de alta clientes y vehículos, el jefe gestiona piezas y stock.
"""
from django.contrib import admin

from .models import Averia, Cliente, LineaPieza, OrdenTrabajo, Perfil, Pieza, Vehiculo


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("usuario", "rol")
    list_filter = ("rol",)


class VehiculoInline(admin.TabularInline):
    model = Vehiculo
    extra = 0


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "telefono", "email")
    search_fields = ("nombre", "telefono")
    inlines = [VehiculoInline]


@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    list_display = ("matricula", "marca", "modelo", "anio", "cliente")
    search_fields = ("matricula", "marca", "modelo")
    list_filter = ("marca",)


@admin.register(Averia)
class AveriaAdmin(admin.ModelAdmin):
    search_fields = ("nombre",)


@admin.register(Pieza)
class PiezaAdmin(admin.ModelAdmin):
    list_display = ("referencia", "nombre", "stock", "stock_minimo", "precio", "bajo_minimo")
    search_fields = ("referencia", "nombre")
    list_editable = ("stock",)

    @admin.display(boolean=True, description="Bajo mínimo")
    def bajo_minimo(self, obj):
        return obj.bajo_minimo


class LineaPiezaInline(admin.TabularInline):
    model = LineaPieza
    extra = 0


@admin.register(OrdenTrabajo)
class OrdenTrabajoAdmin(admin.ModelAdmin):
    list_display = ("id", "vehiculo", "averia", "mecanico", "estado", "horas", "fecha_apertura")
    list_filter = ("estado", "averia")
    search_fields = ("vehiculo__matricula",)
    inlines = [LineaPiezaInline]
