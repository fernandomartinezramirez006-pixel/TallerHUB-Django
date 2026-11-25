# TallerHub

Intranet de gestión para talleres mecánicos: stock de piezas con alertas, historial de vehículos,
órdenes de trabajo, consumo por mecánico y sugerencias de piezas.

**Ampliación de Bases de Datos · Universidad Loyola · 2026-27**
Fernando Martínez · Andrés Jiménez · Manuel Vázquez

| Base de datos | Para qué la usamos |
|---|---|
| **PostgreSQL** | Fuente de verdad: usuarios y roles, clientes, vehículos, piezas/stock, órdenes. Transacciones. |
| **Redis** | Sesiones, caché del historial y del stock (TTL + invalidación), OTP del login, intentos de login. |
| **MongoDB** | Eventos de actividad (dashboard con agregaciones) y fichas de revisión de estructura variable (CRUD). |
| **Neo4j** | Grafo Modelo–Avería–Pieza: sugerencias de piezas y averías frecuentes por modelo. |

## Arranque

Requisitos: Docker y Docker Compose.

```bash
git clone <url-del-repo>
cd tallerhub
cp .env.example .env
docker compose up --build -d
docker compose ps                                              # los 5 servicios "healthy"/"running"
docker compose exec web python manage.py cargar_datos_demo --reset
```

Abrir http://localhost:8000. El **código OTP** aparece en pantalla (simula un SMS) y también en
`docker compose logs web`.

| Usuario | Contraseña | Rol |
|---|---|---|
| jefe | jefe1234 | Jefe (todo + dashboard + admin) |
| mecanico1, mecanico2, mecanico3 | taller123 | Mecánico |
| recepcion | recepcion123 | Recepción (alta de clientes y vehículos en el admin) |

| Servicio | URL |
|---|---|
| Aplicación | http://localhost:8000 |
| Administración Django | http://localhost:8000/admin |
| Estado de las 4 BD | http://localhost:8000/salud/ |
| Neo4j Browser | http://localhost:7474 (neo4j / tallerhub123) |

## Comandos útiles

```bash
docker compose exec web python manage.py test taller -v 2          # pruebas automáticas
docker compose exec web python manage.py medir_cache               # tabla sin caché vs con caché
docker compose exec web python manage.py sincronizar_grafo         # reconstruye Neo4j desde PostgreSQL
docker compose exec redis redis-cli KEYS '*'                       # ver claves de Redis
docker compose exec redis redis-cli TTL otp:usuario:1              # tiempo restante de un OTP
docker compose exec mongo mongosh -u tallerhub -p tallerhub --authenticationDatabase admin tallerhub
docker compose down        # parar   (docker compose down -v borra también los datos)
```

## Estructura

```
tallerhub/
├── docker-compose.yml, Dockerfile, entrypoint.sh, .env.example
├── tallerhub/settings.py            # conexiones a las 4 BD (leídas del .env)
└── taller/
    ├── models.py                    # PostgreSQL: modelos y transacciones de stock
    ├── acciones.py                  # orquesta las 4 BD en cada operación de negocio
    ├── signals.py                   # invalidación de caché al editar desde el admin
    ├── servicios/
    │   ├── redis_service.py         # caché, OTP, intentos de login
    │   ├── mongo_service.py         # eventos, dashboard, CRUD de fichas
    │   └── neo4j_service.py         # sincronización del grafo y consultas Cypher
    ├── views.py, urls.py, templates/
    ├── management/commands/         # cargar_datos_demo, sincronizar_grafo, medir_cache
    └── tests.py
```
