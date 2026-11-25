def rol(request):
    """Pone 'rol_usuario' en todas las plantillas (para mostrar u ocultar el menú)."""
    if not request.user.is_authenticated:
        return {}
    from .views import rol_de
    return {"rol_usuario": rol_de(request.user)}
