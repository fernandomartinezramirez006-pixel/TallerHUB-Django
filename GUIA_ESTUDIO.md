# Guía para entender TallerHub antes de la defensa

En la defensa no se puede usar IA y os van a preguntar por el código.
No hace falta saberse cada línea, pero sí poder explicar **qué hace cada parte y por qué está así**.

## 1. Orden de lectura (todos)

1. `tallerhub/settings.py`: cómo se conecta Django a cada BD.
2. `taller/models.py`: las tablas y el método `anadir_pieza` (transacción + `select_for_update`).
3. `taller/acciones.py`: **el fichero más importante para la defensa**. Muestra el orden:
   PostgreSQL primero → luego Redis (invalidar), MongoDB (evento) y Neo4j (grafo).
4. El servicio de "vuestra" base de datos dentro de `taller/servicios/`.
5. `taller/views.py`: buscad dónde se llama a vuestro servicio.

## 2. Reparto para estudiar

| Persona | Ficheros | Tiene que saber explicar |
|---|---|---|
| Fernando | `redis_service.py`, `neo4j_service.py`, `signals.py` | Claves, TTL, cache-aside, invalidación, OTP, bloqueo de login. Modelo del grafo y las 3 consultas Cypher. |
| Andrés | `models.py`, `views.py`, `urls.py`, `admin.py`, plantillas | Modelos y relaciones, transacción del stock, flujo de login en dos pasos, control por roles. |
| Manuel | `docker-compose.yml`, `Dockerfile`, `mongo_service.py`, `management/commands/`, `tests.py` | Servicios, volúmenes, healthchecks, `.env`. Colecciones, CRUD, agregaciones. Pruebas y medidas. |

## 3. Experimentos para hacer con las manos (aquí se aprende de verdad)

Haced cada uno al menos tres. Si os sale, lo entendéis:

- **Redis:** abrid un vehículo dos veces y mirad cómo cambia de POSTGRES a REDIS. Luego
  `redis-cli KEYS '*'` y `redis-cli TTL cache:historial:vehiculo:<id>`. Cambiad `TTL_CACHE_HISTORIAL` a 10 s y comprobadlo.
- **Redis:** fallad el login 5 veces y mirad `redis-cli GET login:intentos:jefe`. Borrad la clave y volved a entrar.
- **Invalidación:** con el historial en caché, añadid una pieza a una orden de ese coche y recargad: vuelve a salir de POSTGRES. ¿Por qué?
- **Transacción:** intentad usar más piezas de las que hay. Mirad en el admin que el stock no ha cambiado.
- **MongoDB:** en `mongosh`, `db.eventos.find().sort({fecha:-1}).limit(3)` y ejecutad a mano la agregación de `consumo_por_mecanico`.
- **MongoDB:** cread una ficha con campos inventados y miradla en `db.fichas_revision.find()`. Explicad por qué en SQL sería incómodo.
- **Neo4j:** en http://localhost:7474 ejecutad `MATCH (n) RETURN n LIMIT 80` para ver el grafo y luego la consulta `CYPHER_SUGERIR_PIEZAS` cambiando el modelo.
- **Neo4j:** `MATCH (n) DETACH DELETE n` para borrar el grafo y después `python manage.py sincronizar_grafo`. ¿Qué demuestra esto?
- **Código:** añadid un campo nuevo (p. ej. `kilometros` en `OrdenTrabajo`), haced `makemigrations` + `migrate` y mostradlo en la plantilla.

## 4. Preguntas probables en la defensa

**¿Por qué PostgreSQL es la base principal?**
Porque las operaciones de stock y órdenes necesitan integridad: descontar una pieza y añadirla a la orden
tiene que pasar entero o no pasar (transacción). `select_for_update` bloquea la fila para que dos mecánicos
no se lleven la última pieza a la vez.

**¿Qué es la fuente de verdad? ¿Qué pasa si se cae Mongo o Neo4j?**
PostgreSQL. Redis, Mongo y Neo4j guardan datos derivados. Si Mongo o Neo4j fallan, la operación se completa
igualmente (se captura la excepción) y el grafo se puede reconstruir con `sincronizar_grafo`.

**¿Qué estrategia de caché usáis?**
Cache-aside: miro Redis y, si no está, consulto PostgreSQL y guardo con TTL. Se invalida borrando la clave
cuando el dato cambia (`acciones.py` y `signals.py`). El TTL es una red de seguridad por si falla una invalidación.

**¿Por qué invalidáis a mano si ya tenéis signals?**
Porque `queryset.update()` (el que usamos para descontar stock con `F()`) no dispara `post_save`.

**¿Por qué el OTP en Redis y no en una tabla?**
Porque caduca solo con TTL, no hay que limpiar nada, y es de un solo uso (se borra al verificarlo).

**¿Por qué las fichas de revisión en Mongo?**
Porque cada vehículo tiene campos distintos (diésel: filtro de partículas; híbrido: batería). En SQL serían
columnas casi siempre vacías o una tabla clave-valor incómoda.

**¿Qué hace la consulta de sugerencias?**
Busca las reparaciones del mismo modelo con la misma avería y cuenta qué piezas se usaron en ellas.
Si no hay historial del modelo, generaliza a esa avería en cualquier modelo. Es una recomendación basada en
el historial (contenido). En SQL serían varios JOIN; en el grafo es seguir relaciones.

**¿Por qué existe el nodo `Reparacion` en vez de unir Modelo-Avería-Pieza directamente?**
Para no perder el contexto: si uniéramos Avería→Pieza directamente, no sabríamos en qué modelo se usó cada pieza.

**¿Cómo se comunican los contenedores?**
Por la red interna que crea Docker Compose, usando el nombre del servicio como host (`postgres`, `redis`,
`mongo`, `neo4j`). `depends_on` con `condition: service_healthy` hace que la web espere a que las BD estén listas.

**¿Qué persiste si hacéis `docker compose down`?**
Los datos de las 4 BD, porque están en volúmenes con nombre. Solo `down -v` los borra.

## 5. Cambios respecto a la propuesta inicial (para el apartado 3 de la memoria)

- **Añadido:** OTP en el login con Redis (lo pedía la lista de comprobación final).
- **Quitado o simplificado:** la reserva temporal de piezas en Redis (no implementada) y las "horas por mecánico",
  que se registran por orden y no hay un panel propio.
- **Simplificado:** el CRUD de clientes, vehículos y piezas se hace con el admin de Django y no con pantallas propias.
