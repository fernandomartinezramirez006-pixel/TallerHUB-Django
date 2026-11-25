"""
Vistas de TallerHub (plantillas Django, sin frontend aparte).

Mapa rápido de qué BD toca cada vista:
  login / login_otp      -> PostgreSQL (usuario) + Redis (intentos, OTP, sesión)
  vehiculo_detalle       -> Redis (caché historial) + PostgreSQL + MongoDB (fichas) + Neo4j (averías frecuentes)
  stock                  -> Redis (caché) + PostgreSQL
  orden_detalle          -> PostgreSQL + Neo4j (sugerencias) ; acciones -> Redis + MongoDB
  dashboard              -> MongoDB (agregaciones)
  fichas (crear/editar/borrar) -> MongoDB (CRUD con PyMongo)
  salud                  -> ping a las 4 BD
"""
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import acciones
from .models import Averia, OrdenTrabajo, Perfil, Pieza, StockInsuficiente, Vehiculo
from .servicios import mongo_service, neo4j_service, redis_service as rs

User = get_user_model()


# ---------------------------------------------------------------------------
# Control de acceso por rol
# ---------------------------------------------------------------------------
def rol_de(user):
    if user.is_superuser:
        return Perfil.Rol.JEFE
    perfil = getattr(user, "perfil", None)
    return perfil.rol if perfil else None


def rol_requerido(*roles):
    def decorador(vista):
        @wraps(vista)
        @login_required
        def envoltura(request, *args, **kwargs):
            if rol_de(request.user) not in roles:
                messages.error(request, "No tienes permiso para acceder a esa sección.")
                return redirect("inicio")
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador


TODOS = (Perfil.Rol.JEFE, Perfil.Rol.MECANICO, Perfil.Rol.RECEPCION)
TALLER = (Perfil.Rol.JEFE, Perfil.Rol.MECANICO)


# ---------------------------------------------------------------------------
# LOGIN EN DOS PASOS: contraseña + OTP (Redis)
# ---------------------------------------------------------------------------
def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if rs.login_bloqueado(username):
            messages.error(request, "Demasiados intentos fallidos. Usuario bloqueado 15 minutos.")
            return render(request, "registration/login.html")

        user = authenticate(request, username=username, password=password)
        if user is None:
            intentos = rs.registrar_fallo_login(username)
            restantes = max(settings.MAX_INTENTOS_LOGIN - intentos, 0)
            messages.error(request, f"Usuario o contraseña incorrectos. Intentos restantes: {restantes}")
            return render(request, "registration/login.html")

        rs.limpiar_intentos(username)
        codigo = rs.generar_otp(user.pk)
        request.session["otp_usuario_id"] = user.pk
        # En un sistema real se enviaría por SMS/email. Aquí lo simulamos:
        print(f"[OTP] Código para {user.username}: {codigo}")
        messages.info(request, f"(Simulación de SMS) Tu código es {codigo}. Caduca en {settings.TTL_OTP // 60} min.")
        return redirect("login_otp")

    return render(request, "registration/login.html")


def login_otp(request):
    usuario_id = request.session.get("otp_usuario_id")
    if not usuario_id:
        return redirect("login")

    if request.method == "POST":
        codigo = request.POST.get("codigo", "")
        if rs.verificar_otp(usuario_id, codigo):
            user = get_object_or_404(User, pk=usuario_id)
            login(request, user)          # la sesión se guarda en Redis
            request.session.pop("otp_usuario_id", None)
            mongo_service.registrar_evento("login", user.username)
            return redirect("inicio")
        messages.error(request, "Código incorrecto o caducado.")

    return render(request, "registration/login_otp.html", {"ttl": rs.ttl_otp(usuario_id)})


def logout_view(request):
    logout(request)
    return redirect("login")


# ---------------------------------------------------------------------------
# INICIO
# ---------------------------------------------------------------------------
@login_required
def inicio(request):
    # stock <= stock_minimo: F() compara dos columnas de la misma fila en SQL
    piezas_alerta = Pieza.objects.filter(stock__lte=F("stock_minimo")).order_by("stock")
    ordenes_abiertas = OrdenTrabajo.objects.filter(estado=OrdenTrabajo.Estado.ABIERTA)
    if rol_de(request.user) == Perfil.Rol.MECANICO:
        ordenes_abiertas = ordenes_abiertas.filter(mecanico=request.user)
    return render(request, "taller/inicio.html", {
        "rol": rol_de(request.user),
        "piezas_alerta": piezas_alerta,
        "ordenes_abiertas": ordenes_abiertas.select_related("vehiculo", "averia")[:10],
    })


# ---------------------------------------------------------------------------
# VEHÍCULOS E HISTORIAL (caché en Redis)
# ---------------------------------------------------------------------------
@rol_requerido(*TODOS)
def vehiculos(request):
    q = request.GET.get("q", "").strip()
    lista = Vehiculo.objects.select_related("cliente").order_by("matricula")
    if q:
        lista = lista.filter(matricula__icontains=q) | lista.filter(modelo__icontains=q) | \
                lista.filter(cliente__nombre__icontains=q)
    return render(request, "taller/vehiculos.html", {"vehiculos": lista[:50], "q": q})


def consultar_historial(vehiculo_id):
    """Consulta 'cara' a PostgreSQL: todas las órdenes del vehículo con sus piezas."""
    ordenes = (OrdenTrabajo.objects.filter(vehiculo_id=vehiculo_id)
               .select_related("averia", "mecanico")
               .prefetch_related("lineas__pieza"))
    return [{
        "id": o.pk,
        "fecha": o.fecha_apertura.strftime("%d/%m/%Y"),
        "averia": o.averia.nombre,
        "mecanico": o.mecanico.username,
        "estado": o.estado,
        "horas": float(o.horas),
        "piezas": [f"{l.cantidad} x {l.pieza.nombre}" for l in o.lineas.all()],
    } for o in ordenes]


@rol_requerido(*TODOS)
def vehiculo_detalle(request, pk):
    vehiculo = get_object_or_404(Vehiculo.objects.select_related("cliente"), pk=pk)
    historial, origen, ms = rs.obtener_con_cache(
        rs.clave_historial(pk), settings.TTL_CACHE_HISTORIAL, lambda: consultar_historial(pk)
    )
    return render(request, "taller/vehiculo_detalle.html", {
        "v": vehiculo,
        "historial": historial,
        "origen": origen,
        "ms": ms,
        "fichas": mongo_service.fichas_de_vehiculo(pk),
        "averias_frecuentes": neo4j_service.averias_frecuentes(vehiculo.modelo_completo),
        "averias": Averia.objects.order_by("nombre"),
        "puede_abrir": rol_de(request.user) in TALLER,
    })


# ---------------------------------------------------------------------------
# STOCK (caché en Redis + alertas de mínimo)
# ---------------------------------------------------------------------------
def consultar_stock():
    return [{
        "id": p.pk, "ref": p.referencia, "nombre": p.nombre, "stock": p.stock,
        "minimo": p.stock_minimo, "precio": float(p.precio), "alerta": p.bajo_minimo,
    } for p in Pieza.objects.order_by("referencia")]


@rol_requerido(*TODOS)
def stock(request):
    piezas, origen, ms = rs.obtener_con_cache(rs.CLAVE_STOCK, settings.TTL_CACHE_STOCK, consultar_stock)
    return render(request, "taller/stock.html", {
        "piezas": piezas, "origen": origen, "ms": ms,
        "n_alertas": sum(1 for p in piezas if p["alerta"]),
    })


# ---------------------------------------------------------------------------
# ÓRDENES DE TRABAJO
# ---------------------------------------------------------------------------
@rol_requerido(*TALLER)
def ordenes(request):
    estado = request.GET.get("estado", "ABIERTA")
    lista = OrdenTrabajo.objects.select_related("vehiculo", "averia", "mecanico")
    if estado in OrdenTrabajo.Estado.values:
        lista = lista.filter(estado=estado)
    if rol_de(request.user) == Perfil.Rol.MECANICO:
        lista = lista.filter(mecanico=request.user)
    return render(request, "taller/ordenes.html", {"ordenes": lista[:100], "estado": estado})


@rol_requerido(*TALLER)
@require_POST
def orden_nueva(request, vehiculo_id):
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id)
    averia = get_object_or_404(Averia, pk=request.POST.get("averia"))
    orden = acciones.abrir_orden(vehiculo, averia, request.user, request.POST.get("descripcion", ""))
    messages.success(request, f"Orden OT-{orden.pk} abierta.")
    return redirect("orden_detalle", pk=orden.pk)


@rol_requerido(*TALLER)
def orden_detalle(request, pk):
    orden = get_object_or_404(OrdenTrabajo.objects.select_related("vehiculo", "averia", "mecanico"), pk=pk)
    sugerencias, criterio = neo4j_service.sugerir_piezas(orden.vehiculo.modelo_completo, orden.averia.nombre)
    # Añadimos el stock actual (PostgreSQL) a cada sugerencia del grafo
    stock_por_ref = {p.referencia: p for p in Pieza.objects.filter(referencia__in=[s["ref"] for s in sugerencias])}
    for s in sugerencias:
        p = stock_por_ref.get(s["ref"])
        s["id"] = p.pk if p else None
        s["stock"] = p.stock if p else 0
    return render(request, "taller/orden_detalle.html", {
        "orden": orden,
        "lineas": orden.lineas.select_related("pieza"),
        "piezas": Pieza.objects.order_by("nombre"),
        "sugerencias": sugerencias,
        "criterio": criterio,
    })


@rol_requerido(*TALLER)
@require_POST
def orden_usar_pieza(request, pk):
    orden = get_object_or_404(OrdenTrabajo, pk=pk)
    if orden.estado != OrdenTrabajo.Estado.ABIERTA:
        messages.error(request, "La orden ya está cerrada.")
        return redirect("orden_detalle", pk=pk)
    try:
        cantidad = max(int(request.POST.get("cantidad", 1)), 1)
        pieza = acciones.usar_pieza(orden, int(request.POST["pieza"]), cantidad, request.user)
        messages.success(request, f"Añadidas {cantidad} uds. de {pieza.nombre}. Stock restante: {pieza.stock}")
        if pieza.bajo_minimo:
            messages.warning(request, f"⚠ {pieza.nombre} está bajo mínimo ({pieza.stock} uds.)")
    except StockInsuficiente as e:
        messages.error(request, str(e))
    except (ValueError, KeyError, Pieza.DoesNotExist):
        messages.error(request, "Datos de pieza no válidos.")
    return redirect("orden_detalle", pk=pk)


@rol_requerido(*TALLER)
@require_POST
def orden_cerrar(request, pk):
    orden = get_object_or_404(OrdenTrabajo, pk=pk)
    try:
        horas = Decimal(request.POST.get("horas", "0").replace(",", "."))
    except InvalidOperation:
        horas = Decimal("0")
    acciones.cerrar_orden(orden, horas, request.user)
    messages.success(request, f"OT-{orden.pk} cerrada y añadida al grafo de sugerencias.")
    return redirect("vehiculo_detalle", pk=orden.vehiculo_id)


# ---------------------------------------------------------------------------
# DASHBOARD (MongoDB)
# ---------------------------------------------------------------------------
@rol_requerido(Perfil.Rol.JEFE)
def dashboard(request):
    consumo = mongo_service.consumo_por_mecanico()
    top = mongo_service.piezas_mas_usadas()
    por_dia = mongo_service.ordenes_cerradas_por_dia()
    max_consumo = max([c["piezas"] for c in consumo], default=1) or 1
    max_top = max([t["total"] for t in top], default=1) or 1
    for c in consumo:
        c["pct"] = round(100 * c["piezas"] / max_consumo)
    for t in top:
        t["pct"] = round(100 * t["total"] / max_top)
    return render(request, "taller/dashboard.html", {
        "consumo": consumo, "top": top, "por_dia": por_dia,
        "eventos": mongo_service.ultimos_eventos(),
    })


# ---------------------------------------------------------------------------
# FICHAS DE REVISIÓN (CRUD MongoDB)
# ---------------------------------------------------------------------------
def _leer_campos(texto):
    """Convierte líneas 'clave: valor' en un diccionario (estructura libre)."""
    campos = {}
    for linea in texto.splitlines():
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            if clave.strip():
                campos[clave.strip()] = valor.strip()
    return campos


def _campos_a_texto(campos):
    return "\n".join(f"{k}: {v}" for k, v in campos.items())


def _km(request):
    try:
        return int(request.POST.get("kilometros", 0))
    except ValueError:
        return 0


@rol_requerido(*TALLER)
def ficha_nueva(request, vehiculo_id):
    vehiculo = get_object_or_404(Vehiculo, pk=vehiculo_id)
    if request.method == "POST":
        mongo_service.crear_ficha(vehiculo.pk, vehiculo.matricula, request.user.username,
                                  _km(request), _leer_campos(request.POST.get("campos", "")))
        messages.success(request, "Ficha de revisión guardada en MongoDB.")
        return redirect("vehiculo_detalle", pk=vehiculo.pk)
    return render(request, "taller/ficha_form.html", {"v": vehiculo, "ficha": None, "texto": ""})


@rol_requerido(*TALLER)
def ficha_editar(request, ficha_id):
    ficha = mongo_service.obtener_ficha(ficha_id)
    if not ficha:
        messages.error(request, "Ficha no encontrada.")
        return redirect("vehiculos")
    vehiculo = get_object_or_404(Vehiculo, pk=ficha["vehiculo_id"])
    if request.method == "POST":
        mongo_service.actualizar_ficha(ficha_id, _km(request), _leer_campos(request.POST.get("campos", "")))
        messages.success(request, "Ficha actualizada.")
        return redirect("vehiculo_detalle", pk=vehiculo.pk)
    return render(request, "taller/ficha_form.html", {
        "v": vehiculo, "ficha": ficha, "texto": _campos_a_texto(ficha.get("campos", {})),
    })


@rol_requerido(*TALLER)
@require_POST
def ficha_borrar(request, ficha_id):
    ficha = mongo_service.obtener_ficha(ficha_id)
    mongo_service.borrar_ficha(ficha_id)
    messages.success(request, "Ficha eliminada.")
    return redirect("vehiculo_detalle", pk=ficha["vehiculo_id"]) if ficha else redirect("vehiculos")


# ---------------------------------------------------------------------------
# SALUD: comprueba las 4 bases de datos (útil para la defensa y para Docker)
# ---------------------------------------------------------------------------
def salud(request):
    estado = {}
    try:
        Pieza.objects.exists()
        estado["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        estado["postgres"] = f"error: {e}"
    for nombre, servicio in (("redis", rs), ("mongo", mongo_service), ("neo4j", neo4j_service)):
        try:
            servicio.ping()
            estado[nombre] = "ok"
        except Exception as e:  # noqa: BLE001
            estado[nombre] = f"error: {e}"
    todo_ok = all(v == "ok" for v in estado.values())
    return JsonResponse(estado, status=200 if todo_ok else 503)
