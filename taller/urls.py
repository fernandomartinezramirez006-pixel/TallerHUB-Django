from django.urls import path

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("login/", views.login_view, name="login"),
    path("login/otp/", views.login_otp, name="login_otp"),
    path("logout/", views.logout_view, name="logout"),

    path("vehiculos/", views.vehiculos, name="vehiculos"),
    path("vehiculos/<int:pk>/", views.vehiculo_detalle, name="vehiculo_detalle"),
    path("vehiculos/<int:vehiculo_id>/orden/", views.orden_nueva, name="orden_nueva"),
    path("vehiculos/<int:vehiculo_id>/ficha/", views.ficha_nueva, name="ficha_nueva"),

    path("stock/", views.stock, name="stock"),

    path("ordenes/", views.ordenes, name="ordenes"),
    path("ordenes/<int:pk>/", views.orden_detalle, name="orden_detalle"),
    path("ordenes/<int:pk>/pieza/", views.orden_usar_pieza, name="orden_usar_pieza"),
    path("ordenes/<int:pk>/cerrar/", views.orden_cerrar, name="orden_cerrar"),

    path("fichas/<str:ficha_id>/editar/", views.ficha_editar, name="ficha_editar"),
    path("fichas/<str:ficha_id>/borrar/", views.ficha_borrar, name="ficha_borrar"),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("salud/", views.salud, name="salud"),
]
