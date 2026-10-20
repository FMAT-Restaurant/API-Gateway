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
   - [5.2. Prefijos de ruta (`strip_path: false`)](#52-prefijos-de-ruta-strip_path-false)
   - [5.3. Cabeceras HTTP inyectadas por el Gateway](#53-cabeceras-http-inyectadas-por-el-gateway)
   - [5.4. Cómo autorizar acciones (PBAC) en tu microservicio](#54-cómo-autorizar-acciones-pbac-en-tu-microservicio)
   - [5.5. Catálogo Oficial de Permisos por Microservicio](#55-catálogo-oficial-de-permisos-por-microservicio)
6. [Guía para Desarrolladores de Frontend](#6-guía-para-desarrolladores-de-frontend)
7. [Modo de Desarrollo Local Híbrido (Microservicio fuera de Docker)](#7-modo-de-desarrollo-local-híbrido-microservicio-fuera-de-docker)
8. [Estructura del Repositorio y Modificación de Rutas](#8-estructura-del-repositorio-y-modificación-de-rutas)
9. [Solución de Problemas Comunes (Troubleshooting)](#9-solución-de-problemas-comunes-troubleshooting)

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
│  auth-backend   │  menu-backend   │  orders-backend  │ inventory / etc. │
│     :3000       │     :8081       │      :8082       │   :8083 - :8085  │
└─────────────────┴─────────────────┴──────────────────┴──────────────────┘
```

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

3. **Levantar el Gateway:**
   ```bash
   docker compose up -d
   ```
   > Al iniciar, este `docker-compose.yml` crea automáticamente la red puente llamada **`restaurant-network`**, a la cual deben unirse los contenedores de los demás microservicios.

4. **Verificar que Kong está corriendo:**
   ```bash
   curl http://localhost:8001/status
   ```
   - **Puerto Proxy (Tráfico de clientes y frontends):** `http://localhost:8000`
   - **Puerto Admin de Kong (Diagnóstico local):** `http://localhost:8001`

---

## 4. Tabla Maestra de Enrutamiento por Microservicio

Todos los clientes o frontends consumen el Gateway en `http://localhost:8000`. Kong redirige el tráfico dentro de la red Docker `restaurant-network` según la siguiente tabla:

| Microservicio | Nombre en Kong | Prefijo Público (`:8000`) | Destino Interno en Docker (`host:puerto`) | ¿Requiere JWT? |
| :--- | :--- | :--- | :--- | :---: |
| **Autenticación (Público)** | `auth-service` | `/api/v1/auth/login`<br>`/api/v1/auth/refresh`<br>`/api/v1/auth/setup-admin`<br>`/api/v1/auth/setup-status`<br>`/health` | `http://auth-backend:3000` | No *(Rate-Limited)* |
| **Autenticación, Personal y Roles** | `auth-service` | `/api/v1/auth/*`<br>`/api/v1/staff`<br>`/api/v1/roles` | `http://auth-backend:3000` | **Sí** |
| **Menú y Carta** | `menu-service` | `/api/v1/menu` | `http://menu-backend:8081` | **Sí** |
| **Órdenes y Cocina (POS / KDS)** | `orders-service` | `/api/v1/orders` | `http://orders-backend:8082` | **Sí** |
| **Inventario y Almacén** | `inventory-service` | `/api/v1/inventory` | `http://inventory-backend:8083` | **Sí** |
| **Pagos y Facturación (Caja)** | `payments-service` | `/api/v1/payments` | `http://payments-backend:8084` | **Sí** |
| **Sala y Mesas (Floor)** | `floor-service` | `/api/v1/floor` | `http://floor-backend:8085` | **Sí** |

---

## 5. Guía de Integración para Desarrolladores de Microservicios (Backend)

Si eres responsable de uno de los microservicios del restaurante, sigue estos 4 puntos para integrarte con el API Gateway:

### 5.1. Conectar tu Docker Compose a la red del Gateway

Kong resuelve cada microservicio por su **nombre de servicio / alias en la red Docker `restaurant-network`** y su **puerto interno**:
- `auth-backend` en el puerto interno `3000`
- `menu-backend` en el puerto interno `8081`
- `orders-backend` en el puerto interno `8082`
- `inventory-backend` en el puerto interno `8083`
- `payments-backend` en el puerto interno `8084`
- `floor-backend` en el puerto interno `8085`

En el `docker-compose.yml` de tu microservicio, asegúrate de nombrar tu servicio exactamente como aparece arriba y conectarlo a la red externa `restaurant-network`:

```yaml
services:
  # Ejemplo para el equipo de Menú (cambia el nombre y puerto según tu servicio)
  menu-backend:
    build: .
    container_name: fmat-menu-backend
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

> **Importante:** Levanta primero el `API-Gateway` (`docker compose up -d`) para que la red `restaurant-network` ya exista cuando levantes tu microservicio, o créala manualmente una sola vez con `docker network create restaurant-network`.

---

### 5.2. Prefijos de ruta (`strip_path: false`)

Todas las rutas en `config/kong.yml` tienen configurado **`strip_path: false`**.
Esto significa que Kong **conserva la ruta completa** al reenviar la petición a tu contenedor:

- Si el cliente pide `GET http://localhost:8000/api/v1/menu/items/42`
- Tu microservicio recibirá `GET http://menu-backend:8081/api/v1/menu/items/42`

Por lo tanto, configura el prefijo base de tu servidor/controladores en `/api/v1/<tu-servicio>`.

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
   En todas las rutas protegidas, envía el `accessToken` obtenido en `/api/v1/auth/login` mediante la cabecera estándar:
   ```http
   Authorization: Bearer <accessToken>
   ```

3. **Códigos de Estado emitidos por el Gateway:**
   - **`401 Unauthorized`:** El token no fue enviado, la firma es inválida o el token expiró (`exp`). El frontend debe invocar `POST /api/v1/auth/refresh` para obtener un nuevo token.
   - **`403 Forbidden` con `code: "PASSWORD_CHANGE_REQUIRED"`:** El usuario tiene una contraseña temporal (`mustChangePassword: true`). El Gateway solo le permitirá llamar a:
     - `POST /api/v1/auth/change-initial-password`
     - `GET /api/v1/auth/me`
     - `POST /api/v1/auth/logout`
   - **`429 Too Many Requests`:** Se superó el límite de peticiones en rutas públicas de autenticación (máximo 20 por minuto).

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
├── docker-compose.yml                  # Definición de Kong 3.4 DB-less y red restaurant-network
├── config/
│   └── kong.yml                        # Configuración declarativa de servicios, rutas, CORS y JWT
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
| **`502 Bad Gateway`** o **`503 Service Unavailable`** al llamar a `/api/v1/<servicio>` | El contenedor del microservicio destino está apagado o no está conectado a `restaurant-network`. | Verifica que tu contenedor esté corriendo (`docker ps`), que se llame igual que en `config/kong.yml` (ej. `orders-backend`) y que esté en la red `restaurant-network` (`docker network inspect restaurant-network`). |
| **`401 Unauthorized` (`Invalid signature`)** aunque el usuario acaba de iniciar sesión | El `JWT_SECRET` del `.env` en `API-Gateway` no coincide con el `JWT_SECRET` de `Auth-Backend`. | Asegúrate de que ambos usen exactamente el mismo valor (`super_secret_jwt_key_restaurant_auth_2026!`) y reinicia Kong (`docker compose restart kong`). |
| **`401 Unauthorized` (`No credentials found for given 'iss'`)** | El JWT no incluye el claim `"iss": "urn:fmat:restaurant:auth"`. | Asegúrate de tener `Auth-Backend` actualizado a la última versión de `main`. |
| **`404 Not Found` (de Kong: `no Route matched with those values`)** | Estás llamando a una URL sin el prefijo `/api/v1/...`. | Todas las rutas de microservicios llevan el prefijo `/api/v1/` (ej. `http://localhost:8000/api/v1/menu`). |
