# FMAT-Restaurant — API Gateway (Kong 3.4 DB-less)

Punto único de entrada (*Single Entry Point*) y perímetro de seguridad para todos los microservicios del ecosistema **FMAT-Restaurant**.

Este repositorio contiene la configuración declarativa de **Kong Gateway 3.4** en modo *DB-less* y el plugin personalizado **`auth-perimeter`** (escrito en Lua), encargado de validar tokens JWT, bloquear cuentas con contraseña temporal y propagar la identidad y permisos PBAC hacia cada microservicio interno.

---

## Tabla de Contenidos

1. [¿Qué hace el API Gateway por tu microservicio?](#1-qué-hace-el-api-gateway-por-tu-microservicio)
2. [Arquitectura y Flujo de una Petición](#2-arquitectura-y-flujo-de-una-petición)
3. [Inicio Rápido (Levantar el Gateway)](#3-inicio-rápido-levantar-el-gateway)
4. [Tabla Maestra de Enrutamiento por Microservicio](#4-tabla-maestra-de-enrutamiento-por-microservicio)
5. [Guía de Integración para Desarrolladores de Microservicios (Backend)](#5-guía-de-integración-para-desarrolladores-de-microservicios-backend)
   - [5.1. Conectar tu Docker Compose a la red del Gateway](#51-conectar-tu-docker-compose-a-la-red-del-gateway)
   - [5.2. Prefijos de ruta (`strip_path`)](#52-prefijos-de-ruta-strip_path)
   - [5.3. Cabeceras HTTP inyectadas por el Gateway](#53-cabeceras-http-inyectadas-por-el-gateway)
   - [5.4. Cómo autorizar acciones (PBAC) en tu microservicio](#54-cómo-autorizar-acciones-pbac-en-tu-microservicio)
   - [5.5. Catálogo Oficial de Permisos por Microservicio](#55-catálogo-oficial-de-permisos-por-microservicio)
6. [Guía para Desarrolladores de Frontend](#6-guía-para-desarrolladores-de-frontend)
7. [Modo de Desarrollo Local Híbrido (Microservicio fuera de Docker)](#7-modo-de-desarrollo-local-híbrido-microservicio-fuera-de-docker)
8. [Estructura del Repositorio y Modificación de Rutas](#8-estructura-del-repositorio-y-modificación-de-rutas)
9. [Solución de Problemas Comunes (Troubleshooting)](#9-solución-de-problemas-comunes-troubleshooting)
10. [Registro de Cambios](#10-registro-de-cambios)

---

## 1. ¿Qué hace el API Gateway por tu microservicio?

Como desarrollador de un microservicio (Menú, Órdenes/Cocina, Inventario, Pagos/Caja, Sala/Mesas o Auth), **no necesitas implementar validación criptográfica de JWT ni conectarte a la base de datos de usuarios**. El API Gateway realiza automáticamente:

1. **CORS Global:** Habilita peticiones desde cualquier origen para los métodos `GET, POST, PUT, PATCH, DELETE, OPTIONS`.
2. **Rate Limiting en Autenticación:** Protege las rutas públicas de login/registro contra ataques de fuerza bruta (`20 req/min` y `200 req/hora`).
3. **Verificación Criptográfica de JWT (`HS256`):** Verifica la firma del token usando el `JWT_SECRET` compartido, comprueba que el emisor (`iss`) sea `urn:fmat:restaurant:auth` y valida que el token no haya expirado (`exp`).
4. **Bloqueo Perimetral de Contraseñas Temporales (`auth-perimeter`):** Si un empleado inicia sesión con una contraseña temporal (`mustChangePassword: true`), el Gateway **bloquea con `403 Forbidden`** cualquier intento de consumir cualquier microservicio operativo hasta que cambie su contraseña.
5. **Anti-Spoofing e Inyección de Identidad (`auth-perimeter`):** Limpia cualquier cabecera falsificada enviada por el cliente e inyecta cabeceras seguras (`X-User-Id`, `X-Staff-Id`, `X-User-Roles`, `X-User-Permissions`) hacia tu microservicio.

---

## 2. Arquitectura y Flujo de una Petición

```
[ Cliente / Frontend ]
         │
         │  Authorization: Bearer <JWT>
         ▼
┌─────────────────────────────────────────────────────────────┐
│                API Gateway (Kong :8000)                     │
│                                                             │
│  1. ¿Ruta pública (/auth/login, /health, etc.)?             │
│     └── Sí ──► Aplica Rate Limiting ──► Pasa a Auth-Backend │
│                                                             │
│  2. ¿Ruta protegida (/api/v1/menu, /orders, /inventory...)? │
│     ├── Plugin JWT: Verifica firma HS256, iss y exp         │
│     │   (Si falla ──► 401 Unauthorized)                     │
│     │                                                       │
│     └── Plugin auth-perimeter:                              │
│         ├── Limpia headers X-User-* enviados por el cliente │
│         ├── ¿mustChangePassword == true?                    │
│         │   (Si no es ruta de cambio de clave ──► 403)      │
│         └── Inyecta headers hacia el microservicio:         │
│             • X-User-Id                                     │
│             • X-Staff-Id                                    │
│             • X-User-Roles                                  │
│             • X-User-Permissions                            │
└─────────────────────────────────────────────────────────────┘
         │
         │  Red interna Docker: restaurant-network
         ▼
┌─────────────────┬─────────────────┬──────────────────┬──────────────────┐
│  auth-backend   │  menu-backend   │  orders-backend  │ inventory-backend│
│     :3000       │     :8081       │      :8082       │      :3000       │
└─────────────────┴─────────────────┴──────────────────┴──────────────────┘
```
> El puerto interno es el que escucha el contenedor dentro de Docker, **no** el puerto publicado en el host. Cada servicio declara el suyo en su `docker-compose.yml` (`environment: PORT:`). El de `inventory-backend` es `3000` (su `.env` local declara `8083`, pero ese valor solo aplica cuando NestJS corre fuera de Docker).

---

## 3. Inicio Rápido (Levantar el Gateway)

### Prerrequisitos
- **Docker** y **Docker Compose** instalados.

### Pasos

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/FMAT-Restaurant/API-Gateway.git
   cd API-Gateway
   ```

2. **Configurar variables de entorno:**
   Copia el archivo `.env.example` a `.env`:
   ```bash
   cp .env.example .env
   ```
   Contenido de `.env`:
   ```env
   # Debe ser exactamente el mismo JWT_SECRET configurado en Auth-Backend
   JWT_SECRET=super_secret_jwt_key_restaurant_auth_2026!
   KONG_PROXY_PORT=8000
   KONG_ADMIN_PORT=8001
   ```
   > ⚠️ **Seguridad:** `.env` está en `.gitignore` (no se versiona), pero el secreto real aparece en **dos** archivos versionados: `.env.example` y el valor por defecto de `JWT_SECRET` en `docker-compose.yml` (`JWT_SECRET: ${JWT_SECRET:-super_secret_jwt_key_restaurant_auth_2026!}`). Antes de desplegar en un entorno real, genera un secreto nuevo (`openssl rand -base64 32`), actualiza el `.env` de **ambos** repositorios y deja en `.env.example` y en `docker-compose.yml` un valor de ejemplo (`JWT_SECRET=cambia-esto-en-tu-entorno`).

3. **Crear la red compartida (una sola vez por máquina):**
   ```bash
   docker network create restaurant-network
   ```
   > La red **`restaurant-network`** es **externa** y compartida por todos los microservicios del restaurante. Este repositorio la declara con `external: true` (igual que `Auth-Backend`), por lo que Docker Compose **no la crea ni la borra**: debe existir antes de levantar el Gateway y los demás contenedores se conectan a ella con `external: true`.

4. **Levantar el Gateway:**
   ```bash
   docker compose up -d
   ```
   > En el arranque, el contenedor renderiza `config/kong.yml` sustituyendo `${JWT_SECRET}` por el valor real de la variable de entorno `JWT_SECRET` (Kong 3.4 **no** interpola variables en la configuración declarativa) y carga el resultado desde `/tmp/kong.yml`. Si `JWT_SECRET` no está definida, el contenedor arranca y termina con un error explícito.

5. **Verificar que Kong está corriendo:**
   ```bash
   curl http://localhost:8001/status
   ```
   - **Puerto Proxy (Tráfico de clientes y frontends):** `http://localhost:8000`
   - **Puerto Admin de Kong (Diagnóstico local):** `http://localhost:8001`

---

## 4. Tabla Maestra de Enrutamiento por Microservicio

Todos los clientes o frontends consumen el Gateway en `http://localhost:8000`. Kong redirige el tráfico dentro de la red Docker `restaurant-network` según la siguiente tabla:

| Microservicio | Nombre en Kong | Prefijo Público (`:8000`) | Destino Interno en Docker (`host:puerto`) | `strip_path` | ¿Requiere JWT? |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Autenticación (Público)** | `auth-service` | `/api/v1/auth/login`<br>`/api/v1/auth/refresh`<br>`/api/v1/auth/setup-admin`<br>`/api/v1/auth/setup-status`<br>`/health` | `http://auth-backend:3000` | `false` | No *(Rate-Limited)* |
| **Autenticación, Personal y Roles** | `auth-service` | `/api/v1/auth/*`<br>`/api/v1/staff`<br>`/api/v1/roles` | `http://auth-backend:3000` | `false` | **Sí** |
| **Menú y Carta** | `menu-service` | `/api/v1/menu` | `http://menu-backend:8081` | `false` | **Sí** |
| **Órdenes y Cocina (POS / KDS)** | `orders-service` | `/api/v1/orders` | `http://orders-backend:8082` | `false` | **Sí** |
| **Inventario y Almacén** | `inventory-service` | `/api/v1/inventory` | `http://inventory-backend:3000` | **`true`** | **Sí** |
| **Pagos y Facturación (Caja)** | `payments-service` | `/api/v1/payments` | `http://payments-backend:8084` | `false` | **Sí** |
| **Sala y Mesas (Floor)** | `floor-service` | `/api/v1/floor` | `http://floor-backend:8085` | `false` | **Sí** |

> La columna `strip_path` determina **qué ruta recibe el microservicio** (ver [§5.2](#52-prefijos-de-ruta-strip_path)). `inventory-service` es hoy la única ruta con `strip_path: true`: el Gateway le entrega `/ingredients` en lugar de `/api/v1/inventory/ingredients`.

---

## 5. Guía de Integración para Desarrolladores de Microservicios (Backend)

Si eres responsable de uno de los microservicios del restaurante, sigue estos 4 puntos para integrarte con el API Gateway:

### 5.1. Conectar tu Docker Compose a la red del Gateway

Kong resuelve cada microservicio por su **alias de red en `restaurant-network`** y su **puerto interno**:
- `auth-backend` en el puerto interno `3000`
- `menu-backend` en el puerto interno `8081`
- `orders-backend` en el puerto interno `8082`
- `inventory-backend` en el puerto interno `3000`
- `payments-backend` en el puerto interno `8084`
- `floor-backend` en el puerto interno `8085`

En el `docker-compose.yml` de tu microservicio, asegúrate de que tu servicio esté conectado a la red externa `restaurant-network` y **resoluble con el alias exacto** que aparece arriba:

```yaml
services:
  # Ejemplo para el equipo de Menú (cambia el nombre y puerto según tu servicio)
  menu-backend:
    build: .
    environment:
      PORT: 8081
    ports:
      - "8081:8081" # Opcional para pruebas directas en host
    networks:
      - default
      - restaurant-network

networks:
  restaurant-network:
    external: true
```

> ⚠️ **El alias de red no es lo mismo que el nombre del servicio en Compose.** Docker registra en la red el *nombre del servicio* y los alias que declares, **no** el `container_name`. Si tu servicio se llama `app`, el Gateway **no** puede resolver `inventory-backend` aunque el contenedor exista, y toda petición devuelve `503 {"message":"name resolution failed"}`.
>
> Para exponer un alias adicional sin renombrar el servicio, usa la forma de mapa en `networks:`:
>
> ```yaml
>     networks:
>       restaurant-network:
>         aliases:
>           - inventory-backend
> ```
>
> Verifica siempre la resolución **desde dentro del contenedor de Kong** (no desde tu máquina):
> ```bash
> docker exec fmat-api-gateway getent hosts inventory-backend
> # inventory-backend   192.168.164.3
> ```
> Y comprueba el puerto interno real con `docker inspect <contenedor> --format '{{json .Config.Env}}' | grep PORT`.

> **Importante:** La red `restaurant-network` es externa y la crea el primer microservicio que se levanta; créala una sola vez con `docker network create restaurant-network` (después solo conectas tus contenedores a ella con `external: true`).

---

### 5.2. Prefijos de ruta (`strip_path`)

`strip_path` decide si Kong **conserva** o **elimina** el prefijo público antes de reenviar la petición a tu contenedor. Conviene alinear este valor con la forma en que tu microservicio declara sus rutas.

#### Modo `strip_path: false` — el microservicio sirve el prefijo completo

Es el modo usado por `auth-service`, `menu-service`, `orders-service`, `payments-service` y `floor-service`. Kong **conserva la ruta completa**:

- Si el cliente pide `GET http://localhost:8000/api/v1/menu/items/42`
- Tu microservicio recibirá `GET http://menu-backend:8081/api/v1/menu/items/42`

Por lo tanto, configura el prefijo base de tu servidor/controladores en `/api/v1/<tu-servicio>`.
*(`Auth-Backend` lo hace con `@Controller('api/v1/auth')`.)*

#### Modo `strip_path: true` — el microservicio sirve la ruta nativa

Es el modo usado por `inventory-service`. Kong **elimina** el prefijo público de la ruta antes de reenviarla:

- Si el cliente pide `GET http://localhost:8000/api/v1/inventory/ingredients`
- Tu microservicio recibirá `GET http://inventory-backend:3000/ingredients`

Con `Inventory-Backend`, los controladores se declaran sin prefijo (`@Controller('ingredients')`), por lo que `strip_path: true` hace que coincidan sin necesidad de tocar el backend.

#### Cómo elegir

| Tu microservicio declara sus rutas… | `strip_path` | Lo que recibe el contenedor |
| :--- | :---: | :--- |
| Con prefijo (`@Controller('api/v1/inventory')`) | `false` | `/api/v1/inventory/ingredients` |
| Sin prefijo (`@Controller('ingredients')`) | `true` | `/ingredients` |

> **Regla práctica:** el prefijo público y la ruta interna del contenedor **deben terminar en la misma URL**. Si no coinciden, el Gateway responde `404 Not Found` (no del Gateway, sino del microservicio). Para comprobar qué ruta está llegando realmente, pruébala desde la misma red del Gateway:
> ```bash
> docker run --rm --network restaurant-network curlimages/curl:latest \
>   -s -o /dev/null -w "%{http_code}\n" http://inventory-backend:3000/ingredients
> # 200  -> el contenedor sirve /ingredients (usa strip_path: true)
> ```
> *(La imagen `kong:3.4` no incluye `curl` ni `wget`, por eso se usa un contenedor efímero en lugar de `docker exec`.)*

---

### 5.3. Cabeceras HTTP inyectadas por el Gateway

Cuando una petición pasa por el Gateway con un JWT válido, el plugin `auth-perimeter` elimina cualquier cabecera previa con el mismo nombre y añade las siguientes **4 cabeceras HTTP** a la petición que llega a tu microservicio:

| Cabecera HTTP | Descripción | Ejemplo de Valor (Empleado) | Ejemplo de Valor (Admin) |
| :--- | :--- | :--- | :--- |
| `X-User-Id` | UUID único del usuario en el sistema (`sub` del JWT). | `b6e6f9c4-3a12-4d8e-9c01-8f22a1b4d5e6` | `a1b2c3d4-1111-2222-3333-444455556666` |
| `X-Staff-Id` | Matrícula operativa del colaborador o administrador. | `E000104` | `ADM000001` |
| `X-User-Roles` | Códigos de los roles asignados, separados por coma. | `MESERO,HOST` | `ADMINISTRADOR` |
| `X-User-Permissions` | Permisos granulares PBAC asignados, separados por coma. | `orders:view,orders:create,menu:view,sala:tables:view` | `*` |

> **Seguridad Anti-Spoofing:** Si un usuario externo intenta enviar manualmente un header `X-User-Permissions: *` desde Postman o el navegador, el plugin `auth-perimeter` lo borra al inicio de la petición (`kong.service.request.clear_header`) y lo sobrescribe exclusivamente con los claims firmados dentro del JWT.

---

### 5.4. Cómo autorizar acciones (PBAC) en tu microservicio

Nuestro sistema utiliza **PBAC (*Permission-Based Access Control*)** con roles dinámicos.
- **Regla de Oro:** Tu microservicio **no debe validar nombres de roles fijos** (como `if role == 'MESERO'`), porque el Administrador puede crear roles personalizados desde la interfaz (ej. `SUBGERENTE_NOCTURNO` o `CAJERO_EVENTOS`) con combinaciones específicas de permisos.
- En su lugar, tu microservicio debe validar **si el header `X-User-Permissions` incluye el permiso requerido para ese endpoint o el comodín `*`** (que representa acceso total de Administrador).

#### Ejemplo en Node.js / Express / NestJS
```typescript
function requirePermission(requiredPermission: string) {
  return (req, res, next) => {
    const rawPermissions = req.headers['x-user-permissions'] as string | undefined;
    if (!rawPermissions) {
      return res.status(401).json({ message: 'No autenticado: cabeceras de Gateway ausentes' });
    }

    const permissions = rawPermissions.split(',').map((p) => p.trim());

    // El Administrador tiene el comodín '*' que otorga todos los permisos
    if (permissions.includes('*') || permissions.includes(requiredPermission)) {
      return next();
    }

    return res.status(403).json({
      message: `Permiso insuficiente. Se requiere: ${requiredPermission}`,
    });
  };
}

// Uso en una ruta de Inventario:
// app.post('/api/v1/inventory/ingredients', requirePermission('inventory:ingredients:create'), controller);
```

#### Ejemplo en Python (FastAPI)
```python
from fastapi import Header, HTTPException, Depends

def require_permission(required_permission: str):
    def dependency(x_user_permissions: str | None = Header(default=None)):
        if not x_user_permissions:
            raise HTTPException(status_code=401, detail="Cabeceras de Gateway ausentes")
        permissions = [p.strip() for p in x_user_permissions.split(",")]
        if "*" not in permissions and required_permission not in permissions:
            raise HTTPException(
                status_code=403,
                detail=f"Permiso insuficiente. Se requiere: {required_permission}"
            )
    return Depends(dependency)

# Uso en un endpoint de Órdenes:
# @app.post("/api/v1/orders", dependencies=[require_permission("orders:create")])
```

---

### 5.5. Catálogo Oficial de Permisos por Microservicio

Estos son los códigos de permisos que emite `Auth-Backend` en el JWT y que llegan en `X-User-Permissions`:

| Microservicio / Dominio | Código de Permiso (`X-User-Permissions`) | Acción que autoriza |
| :--- | :--- | :--- |
| **Administrador Global** | `*` | Acceso total irrestricto a todos los microservicios y acciones. |
| **Inventario (`inventory-service`)** | `inventory:view` | Consultar existencias y stock de ingredientes. |
| | `inventory:ingredients:create` | Registrar nuevos insumos y productos en bodega. |
| | `inventory:stock:update_status` | Modificar cantidades, mermas y estados de stock. |
| | `inventory:ingredients:delete` | Dar de baja materias primas de la base de datos. |
| **Cocina (`orders-service` / KDS)** | `kitchen:kds:view` | Visualizar comandas en pantalla de cocina (KDS) y tiempos. |
| | `kitchen:order:start_preparation` | Marcar platillos como "en preparación / cocción". |
| | `kitchen:order:mark_ready` | Marcar que la orden está lista para servir. |
| **Pedidos / POS (`orders-service`)** | `orders:view` | Consultar órdenes en curso y detalle de comandas. |
| | `orders:create` | Abrir nuevas órdenes y capturar platillos. |
| | `orders:cancel` | Anular comandas o platillos. |
| **Menú (`menu-service`)** | `menu:view` | Consultar carta, platillos y catálogo de precios. |
| | `menu:edit` | Crear/editar platillos, precios, recetas y disponibilidad. |
| **Sala y Mesas (`floor-service`)** | `sala:tables:view` | Consultar mapa de mesas y estados (libre/ocupada). |
| | `sala:tables:assign_diner` | Asignar comensales a mesas disponibles. |
| | `sala:tables:assign_waiter` | Vincular mesero responsable a una mesa. |
| **Caja y Pagos (`payments-service`)** | `billing:invoices:create` | Procesar cobros, emitir tickets de pago y facturas. |
| | `billing:reports:view` | Consultar ingresos del turno y arqueo de caja. |
| **Personal y Roles (`auth-service`)** | `staff:view` | Consultar lista de colaboradores y perfiles. |
| | `staff:manage` | Crear/editar colaboradores, restablecer claves y gestionar roles. |

---

## 6. Guía para Desarrolladores de Frontend

1. **URL Base Única:**
   Configura tu variable de entorno para apuntar al puerto Proxy del Gateway (`8000`):
   ```env
   VITE_API_BASE_URL=http://localhost:8000/api/v1
   ```

2. **Envío del Token JWT:**
   `POST /api/v1/auth/login` **no devuelve un token suelto**, sino un objeto JSON. El token está en la propiedad **`accessToken`** (camelCase):

   ```json
   {
     "message": "Inicio de sesión exitoso",
     "mustChangePassword": false,
     "user": {
       "id": "b29ba2fc-4ac9-4ac9-af46-986a4089dbd5",
       "staffId": "ADM000001",
       "email": "admin@fmat.com",
       "roles": ["ADMINISTRADOR"],
       "permissions": ["*"]
     },
     "accessToken": "<JWT>",
     "refreshToken": "<refresh>",
     "tokenType": "Bearer",
     "expiresIn": 3600
   }
   ```

   En todas las rutas protegidas, envía **solo el valor de `accessToken`** mediante la cabecera estándar:
   ```http
   Authorization: Bearer <accessToken>
   ```
   > ⚠️ Si envías el JSON completo como si fuera el token, el Gateway responderá `401 Unauthorized`. El cuerpo de la petición no es un token válido.

   Ejemplo desde la línea de comandos:
   ```bash
   TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"identifier":"admin@fmat.com","password":"Admin123!"}' \
     | python3 -c 'import sys,json; print(json.load(sys.stdin)["accessToken"])')

   curl -s http://localhost:8000/api/v1/inventory/ingredients \
     -H "Authorization: Bearer $TOKEN"
   ```
   > `identifier` acepta el **correo** o la **matrícula de personal** (Staff ID). Si tienes `jq` instalado, puedes sustituir el `python3` por `jq -r '.accessToken'`.

3. **Códigos de Estado emitidos por el Gateway:**
   - **`401 Unauthorized`:** El token no fue enviado, la firma es inválida o el token expiró (`exp`). El frontend debe invocar `POST /api/v1/auth/refresh` para obtener un nuevo token.
   - **`403 Forbidden` con `code: "PASSWORD_CHANGE_REQUIRED"`:** El usuario tiene una contraseña temporal (`mustChangePassword: true`). El Gateway solo le permitirá llamar a:
     - `POST /api/v1/auth/change-initial-password`
     - `GET /api/v1/auth/me`
     - `POST /api/v1/auth/logout`
   - **`429 Too Many Requests`:** Se superó el límite de peticiones en rutas públicas de autenticación (máximo 20 por minuto).
   - **`503 Service Unavailable` con `{"message":"name resolution failed"}`:** El Gateway no pudo resolver el host del microservicio en `restaurant-network`. Es un problema de **topología de red o de alias**, no de autenticación (ver [§9](#9-solución-de-problemas-comunes-troubleshooting)).
   - **`404 Not Found`:** La ruta existe en el Gateway pero el prefijo no coincide con lo que sirve el microservicio (ver [§5.2](#52-prefijos-de-ruta-strip_path)).

---

## 7. Modo de Desarrollo Local Híbrido (Microservicio fuera de Docker)

Si estás desarrollando tu microservicio directamente en tu máquina (`npm run start:dev`, `uvicorn`, `go run`, etc.) en lugar de correrlo dentro de un contenedor Docker, Kong (que corre dentro de Docker) no encontrará el hostname `menu-backend` o `orders-backend`.

Para probar tu microservicio local a través del Gateway:
1. En `config/kong.yml`, cambia temporalmente el host de tu servicio por `host.docker.internal`:
   ```yaml
   - name: menu-service
     url: http://host.docker.internal:8081 # Apunta al puerto 8081 de tu máquina host
   ```
2. Reinicia el contenedor del Gateway para aplicar el cambio:
   ```bash
   docker compose restart kong
   ```
*(Recuerda no subir a `main` el cambio a `host.docker.internal` para mantener la compatibilidad entre contenedores).*

---

## 8. Estructura del Repositorio y Modificación de Rutas

```text
API-Gateway/
├── .env.example                        # Plantilla de variables de entorno
├── docker-compose.yml                  # Definición de Kong 3.4 DB-less y red externa restaurant-network
├── config/
│   └── kong.yml                        # PLANTILLA de la configuración declarativa (servicios, rutas, CORS, JWT).
│                                       # ${JWT_SECRET} se renderiza en el arranque del contenedor.
└── plugins/
    └── auth-perimeter/
        ├── handler.lua                 # Lógica de bloqueo de clave temporal e inyección de X-User-*
        └── schema.lua                  # Esquema del plugin para Kong
```

### ¿Cómo agregar un nuevo endpoint o ruta a un microservicio existente?
Si el nuevo endpoint está bajo el mismo prefijo (por ejemplo, `/api/v1/orders/kitchen-queue` dentro de `/api/v1/orders`), **no necesitas tocar el API Gateway**: Kong ya redirige automáticamente cualquier subruta que comience con `/api/v1/orders` hacia `http://orders-backend:8082`.

Si tu microservicio necesita exponer una **ruta pública sin JWT** (por ejemplo, un webhook o healthcheck), agrégala en `config/kong.yml` como una ruta separada sin los plugins `jwt` ni `auth-perimeter`, y ejecuta `docker compose restart kong`.

---

## 9. Solución de Problemas Comunes (Troubleshooting)

| Síntoma / Error | Causa Probable | Solución |
| :--- | :--- | :--- |
| **`503 Service Unavailable` con `{"message":"name resolution failed"}`** | Kong no puede resolver el host del microservicio en `restaurant-network`. Causas: (a) el contenedor no está conectado a esa red; (b) el alias no coincide con el `url` de `config/kong.yml` (Docker registra el **nombre del servicio** y los `aliases` declarados, **no** el `container_name`); (c) el servicio de Compose se llama distinto al esperado (p. ej. `app` en vez de `inventory-backend`). | Comprueba la resolución **desde el contenedor de Kong**: `docker exec fmat-api-gateway getent hosts inventory-backend`. Si no resuelve, declara el alias en el `docker-compose.yml` del microservicio con la forma de mapa (`networks: { restaurant-network: { aliases: [inventory-backend] } }`). Ver [§5.1](#51-conectar-tu-docker-compose-a-la-red-del-gateway). |
| **`502 Bad Gateway`** o **`503 Service Unavailable`** al llamar a `/api/v1/<servicio>` | El contenedor del microservicio destino está apagado o no está conectado a `restaurant-network`. | Verifica que tu contenedor esté corriendo (`docker ps`), que se llame igual que en `config/kong.yml` (ej. `orders-backend`) y que esté en la red `restaurant-network` (`docker network inspect restaurant-network`). |
| **`404 Not Found` (desde el microservicio, no desde Kong)** | El prefijo público y la ruta interna no coinciden: `strip_path` está mal configurado para ese servicio. | Verifica con `curl` directo al contenedor qué ruta sirve realmente y ajusta `strip_path` en `config/kong.yml` ([§5.2](#52-prefijos-de-ruta-strip_path)). Ej.: con `strip_path: true`, `/api/v1/inventory/ingredients` llega al contenedor como `/ingredients`. |
| **`401 Unauthorized` inmediatamente después de iniciar sesión** | Se envió el **cuerpo JSON completo** de la respuesta de login como si fuera el token, en lugar del valor de `accessToken`. | Extrae la propiedad: `... | python3 -c 'import sys,json; print(json.load(sys.stdin)["accessToken"])'` o `jq -r '.accessToken'`. Ver [§6](#6-guía-para-desarrolladores-de-frontend). |
| **`WARN a network with name restaurant-network exists but was not created by compose`** | La red existe pero fue creada fuera de Docker Compose (sin labels de Compose). | Es esperado: la red es externa y compartida. Crea la red con `docker network create restaurant-network` y usa `external: true` en todos los `docker-compose.yml` (ya está así en `API-Gateway` y `Auth-Backend`). |
| **`401 Unauthorized` (`Invalid signature`)** aunque el usuario acaba de iniciar sesión | Kong está comparando la firma contra un secreto distinto del que usa `Auth-Backend`. Causas habituales: (a) el `JWT_SECRET` del `.env` de `API-Gateway` difiere del de `Auth-Backend`; (b) la configuración declarativa quedó con el placeholder sin renderizar (`secret: "${JWT_SECRET}"` literal). | Asegúrate de que ambos `.env` usen exactamente el mismo valor y **recrea** el contenedor para que se re-renderice la plantilla: `docker compose up -d --force-recreate kong`. Verifica el render con `docker exec fmat-api-gateway grep -n "secret:" /tmp/kong.yml` (no debe mostrar `${JWT_SECRET}`). |
| **`401 Unauthorized` (`No credentials found for given 'iss'`)** | El JWT no incluye el claim `"iss": "urn:fmat:restaurant:auth"`. | Asegúrate de tener `Auth-Backend` actualizado a la última versión de `main`. |
| **`404 Not Found` (de Kong: `no Route matched with those values`)** | Estás llamando a una URL sin el prefijo `/api/v1/...`. | Todas las rutas de microservicios llevan el prefijo `/api/v1/` (ej. `http://localhost:8000/api/v1/menu`). |
| **El contenedor del microservicio se reinicia solo / el proceso Node termina** | Un `EventEmitter` de una librería externa (p. ej. `amqplib`) emitió un evento `'error'` sin listener; Node lanza la excepción y termina el proceso. | Registra listeners de `'error'` y `'close'` en el emitter y añade guardas `process.on('uncaughtException')` / `process.on('unhandledRejection')` en el `main.ts` del microservicio. Ver el §10 de este documento. |
| **El microservicio responde `500` y los logs muestran `MongoServerSelectionError: getaddrinfo ENOTFOUND <db>`** | La base de datos no está en la red compartida, o su servicio de Compose no declara `networks:` (y queda en la red por defecto del proyecto). | Declara `networks: [restaurant-network]` en **todos** los servicios del `docker-compose.yml`, incluidos los de base de datos, y recrea los contenedores: `docker compose up -d --force-recreate`. |

---

## 10. Registro de Cambios

### 2026-10-21 — Habilitado el flujo `login` → `/api/v1/inventory/ingredients`

La petición autenticada contra inventario fallaba con `503 {"message":"name resolution failed"}`. La causa eran **cinco faults independientes** acumulados entre el Gateway y el microservicio.

**Cambios en este repositorio (`API-Gateway`)**

| Archivo | Cambio | Motivo |
| :--- | :--- | :--- |
| `config/kong.yml` | `inventory-service`: `url` de `http://inventory-backend:8083` → `http://inventory-backend:3000` | El contenedor escucha en `3000` (`environment: PORT: 3000`). El `8083` del `.env` de `Inventory-Backend` solo aplica cuando NestJS corre en el host. |
| `config/kong.yml` | `inventory-routes`: `strip_path: false` → `strip_path: true` | El backend sirve `/ingredients` (sin prefijo global). Kong ahora entrega `/ingredients` en vez de `/api/v1/inventory/ingredients`, que devolvía `404`. |
| `README.md` | Documentados el modo `strip_path: true`, la respuesta real de login y los nuevos errores de troubleshooting. | — |

**Cambios en `Inventory-Backend` (repositorio hermano)**

| Archivo | Cambio | Motivo |
| :--- | :--- | :--- |
| `compose.yaml` | El servicio `app` declara `networks.restaurant-network.aliases: [inventory-backend]` | El servicio de Compose se llama `app`, así que `inventory-backend` no resolvía en la red compartida y Kong devolvía `503`. |
| `compose.yaml` | El servicio `db` ahora declara `networks: [restaurant-network]` | No declaraba red, por lo que quedaba en la red por defecto del proyecto y el app no podía resolver `db` (`MongoServerSelectionError`). |
| `src/broker/event-publisher.service.ts`<br>`src/broker/event-customer.service.ts` | Listeners de `'error'` y `'close'` en `connection` y `channel`. | `amqplib` emitía un `'error'` sin listener al caerse el broker; Node terminaba el proceso y el contenedor quedaba `unhealthy` sin servir tráfico. |
| `src/main.ts` | Guardas `process.on('uncaughtException')` y `process.on('unhandledRejection')`. | Red de seguridad para que un error no capturado en un `EventEmitter` no tumbe el servicio. |
| `src/database/database.module.ts` | `retryAttempts: 10`, `retryDelay: 3000`, `serverSelectionTimeoutMS: 15000`. | Tras un reinicio de Mongo la conexión lazy quedaba en estado fallido y el servicio respondía `500` hasta reiniciarse a mano. |

**Verificación**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"identifier":"admin@fmat.com","password":"Admin123!"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["accessToken"])')

curl -s http://localhost:8000/api/v1/inventory/ingredients -H "Authorization: Bearer $TOKEN"
```

| Escenario | Resultado esperado |
| :--- | :--- |
| Token válido | `200` con el listado de ingredientes |
| Sin cabecera `Authorization` | `401` |
| Cuerpo JSON de login completo como token | `401` |
| `GET /api/v1/inventory` (raíz) | `200` |
| `POST /api/v1/inventory/ingredients` | `201` |
| `DELETE /api/v1/inventory/ingredients/:id` | `200` |

> **Pendiente:** los microservicios `menu`, `orders`, `payments` y `floor` todavía **no existen** en el ecosistema, por lo que sus rutas responden `503`. Sus entradas en `config/kong.yml` quedan preparadas con `strip_path: false` (conservan el prefijo `/api/v1/<servicio>`), de forma coherente con `Auth-Backend`. Cuando se creen, deben declarar su alias de red y su `PORT` interno según la [tabla maestra](#4-tabla-maestra-de-enrutamiento-por-microservicio).
>
> **Pendiente:** `Inventory-Backend` todavía **no** valida el header `X-User-Permissions`, por lo que el control PBAC descrito en [§5.4](#54-cómo-autorizar-acciones-pbac-en-tu-microservicio) no se aplica dentro del servicio: hoy solo el `jwt` del Gateway filtra las peticiones.
