# API Gateway del restaurante

Gateway Kong 3.4 en modo **DB-less**. Las rutas, los destinos y los plugins se declaran en `config/kong.yml`. Este repositorio ejecuta únicamente el gateway: los seis backends se levantan por separado.

## Inicio

Requisitos: Docker Engine con Docker Compose v2 y los backends que se quieran consumir.

1. Copia `.env.example` a `.env`.
2. Define `JWT_SECRET` con un secreto aleatorio de al menos 32 bytes, idéntico al utilizado por Auth-Backend para firmar los access tokens HS256. No lo incluyas en Git ni en variables del frontend. Puedes generarlo con `python -c "import secrets; print(secrets.token_hex(32))"`.
3. Ajusta `CORS_ORIGINS` a los orígenes reales del frontend, separados por comas y sin rutas ni barra final.
4. Ejecuta:

```sh
docker compose up -d
docker compose logs -f kong
```

| Variable | Uso |
| --- | --- |
| `JWT_SECRET` | Obligatoria, sin valor predeterminado; mínimo 32 bytes. |
| `CORS_ORIGINS` | Por defecto `http://localhost:5173,http://localhost:3000`. Orígenes HTTP/HTTPS explícitos con hostname o IPv4 y puerto opcional; sin comodines ni expresiones regulares. |
| `KONG_PROXY_PORT` | Puerto del gateway para los clientes; por defecto `8000`. |
| `KONG_ADMIN_PORT` | Puerto administrativo local; por defecto `8001`, publicado únicamente en `127.0.0.1`. |

Compose crea la red `restaurant-network`. Arranca el gateway antes de levantar otros proyectos que declaren esa red como externa. No ejecutes `docker compose down` del gateway mientras otros contenedores dependan de su red; para detenerlo conservándola usa `docker compose stop`.

Al iniciar, `config/render.lua` genera la configuración de Kong en `/tmp/kong.yml` a partir de la plantilla y las variables de entorno. No montes la plantilla directamente como configuración final.

## Configuración del frontend

La URL base debe apuntar al **proxy**, por ejemplo `http://localhost:8000` en desarrollo o `https://api.example.com` en un despliegue con TLS. `localhost` se refiere a la computadora del navegador; los nombres Docker de los backends no son direcciones públicas.

Ejemplo para Vite:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

Para otro framework usa su mecanismo de configuración pública equivalente. El puerto debe coincidir con `KONG_PROXY_PORT`. Si incluyes `/api/v1` en tu URL base, no lo repitas al construir las rutas.

```js
const baseURL = import.meta.env.VITE_API_BASE_URL;

// accessToken es el access token entregado por Auth-Backend.
// Este repositorio no define el nombre del campo en la respuesta del login.
export async function loadMenu(accessToken) {
  const response = await fetch(`${baseURL}/api/v1/menu`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) throw new Error(`API: ${response.status}`);
  return response.json();
}
```

- Realiza el login mediante `/api/v1/auth/login` usando el cuerpo que exija Auth-Backend. El gateway no define los DTO ni transforma las respuestas.
- En rutas protegidas envía `Authorization: Bearer <access-token>`. No envíes el JWT en la URL, parámetros de consulta o cookies: el plugin JWT solo lee ese encabezado.
- Configura el origen del frontend en `CORS_ORIGINS`; esquema, host y puerto forman parte del origen. `localhost` y `127.0.0.1` son orígenes distintos.
- Se admiten por CORS `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS` y los encabezados `Accept`, `Authorization`, `Content-Type`. Kong responde al preflight del navegador antes de autenticarlo.
- La configuración actual usa `credentials: false`. Si Auth-Backend utiliza cookies para refresh, hay que adaptar CORS, el cliente (`credentials: "include"`) y los atributos de la cookie/CSRF al contrato real del backend; ese flujo no está configurado aquí. `cookie_names: []` solo controla de dónde se extrae el access token, no elimina cookies reenviadas al backend.
- Un `401` puede indicar un token ausente, inválido, vencido o claims de identidad inválidos. Un `403` con `code: PASSWORD_CHANGE_REQUIRED` requiere llevar al usuario al cambio de contraseña inicial. No reintentes indefinidamente ni renueves ante cualquier `403`.
- El frontend no configura `JWT_SECRET`, no firma tokens y no envía `X-User-*` ni `X-Staff-Id`: Kong elimina esos encabezados y los reconstruye desde el token validado.

## Rutas y destinos actuales

| Servicio | Destino dentro de Docker | Ruta pública del gateway | Ruta enviada al backend | JWT |
| --- | --- | --- | --- | --- |
| Auth | `http://auth-backend:3000` | `/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/setup-admin`, `/api/v1/auth/setup-status`, `/health` | Sin cambios | No |
| Auth | `http://auth-backend:3000` | `/api/v1/auth`, `/api/v1/staff`, `/api/v1/roles` y descendientes, salvo las excepciones anteriores | Sin cambios | Sí |
| Menú | `http://menu-backend:8080` | `/api/v1/menu` y descendientes, incluido `/api/v1/menu/categories` | Sin cambios | Sí |
| Órdenes | `http://orders-backend:8082` | `/api/v1/orders` y descendientes | Sin cambios | Sí |
| Inventario | `http://inventory-backend:3000` | `/api/v1/inventory` y descendientes | Se elimina `/api/v1/inventory` | Sí |
| Pagos | `http://payments-backend:8084` | `/api/v1/payments` y descendientes | Sin cambios | Sí |
| Piso | `http://floor-backend:8085` | `/api/v1/floor` y descendientes | Sin cambios | Sí |

Inventario conserva su contrato particular: `/api/v1/inventory/items?limit=10` llega como `/items?limit=10`. En los demás servicios `strip_path: false` conserva el prefijo público completo. Los puertos son los puertos **internos** donde escuchan las aplicaciones, independientemente de cualquier publicación en el host.

Las rutas públicas aceptan una barra final opcional y no incluyen subrutas. Los prefijos protegidos incluyen sus descendientes. El backend valida el método HTTP de cada endpoint.

Las rutas públicas de Auth comparten rate limiting de 20 solicitudes/minuto y 200/hora por IP, con política local. Los contadores no se comparten entre réplicas y `fault_tolerant: true` permite continuar si falla el contador. Si hay un proxy anterior, configura correctamente las IP confiables de Kong para contar al cliente real, sin confiar indiscriminadamente en `X-Forwarded-For`.

## Configuración de un backend

**No existe registro automático ni endpoint de registro.** En modo DB-less se agrega un `service` y sus `routes` al archivo declarativo y se recrea el contenedor del gateway.

### Conectar un backend existente

El proceso debe escuchar en `0.0.0.0:<puerto-interno>` y estar en `restaurant-network` con el nombre DNS o alias declarado en la tabla. Ejemplo de Compose en el repositorio de menú:

```yaml
services:
  menu-backend:
    build: .
    expose:
      - "8080"
    networks:
      restaurant-network:
        aliases:
          - menu-backend

networks:
  restaurant-network:
    external: true
    name: restaurant-network
```

`expose` documenta el puerto interno; no es necesario publicar `ports` para que Kong lo alcance. Evita publicar los backends directamente si confían en los encabezados de identidad del gateway. La red compartida tampoco impide que otros contenedores de esa red contacten directamente al servicio: solo deben participar componentes confiables o debe añadirse aislamiento/autenticación entre servicios.

### Agregar un servicio nuevo

Añade un elemento a `services` en `config/kong.yml`, ajustando DNS, puerto y prefijo:

```yaml
  - name: reports-service
    url: http://reports-backend:8086
    routes:
      - name: reports-routes
        paths:
          - ~/api/v1/reports(/|$)
        strip_path: false
        plugins:
          - name: jwt
            config:
              key_claim_name: iss
              claims_to_verify:
                - exp
              header_names: [Authorization]
              uri_param_names: []
              cookie_names: []
          - name: auth-perimeter
```

Mantén **ambos plugins** en cada ruta protegida. `jwt` valida firma y expiración; `auth-perimeter`, cuya configuración predeterminada exige JWT, aplica el contrato de identidad y el bloqueo por contraseña temporal. La instancia global de `auth-perimeter` solo limpia encabezados de peticiones públicas; por sí sola no protege un servicio nuevo.

Tras modificar configuración o variables:

```sh
docker compose up -d --force-recreate kong
```

No uses operaciones CRUD de la Admin API para registrar servicios en esta configuración DB-less. El archivo declarativo es la fuente persistente de configuración.

## Contrato de Auth-Backend y autorización

Auth-Backend debe firmar access tokens con **HS256**, con el mismo secreto literal que Kong, sin decodificación base64 del secreto, y emitir estos claims:

| Claim | Requisito |
| --- | --- |
| `iss` | Obligatorio: `urn:fmat:restaurant:auth`, coincidente con la credencial JWT y el emisor esperado por el plugin. |
| `exp` | Obligatorio: fecha de expiración como número de segundos Unix, validada por Kong. |
| `sub` | Obligatorio: identificador del usuario como cadena no vacía. |
| `staffId` | Opcional: cadena no vacía o número entero. |
| `roles` | Opcional: arreglo de cadenas no vacías. |
| `permissions` | Opcional: arreglo de cadenas no vacías. |
| `mustChangePassword` | Opcional: booleano; cuando es `true`, restringe las rutas protegidas. |

Los valores propagados como identidad no admiten caracteres de control ni comas; roles y permisos se separan por comas. Un claim inválido produce `401`.

Ejemplo de payload, con `exp` calculado al emitir el token:

```js
const claims = {
  iss: "urn:fmat:restaurant:auth",
  sub: String(user.id),
  staffId: String(staff.id),
  roles: ["waiter"],
  permissions: ["orders:read"],
  mustChangePassword: false,
  exp: Math.floor(Date.now() / 1000) + 900,
};
```

Kong propaga `sub` como `X-User-Id`, `staffId` como `X-Staff-Id`, y los arreglos como `X-User-Roles` y `X-User-Permissions`. Los campos opcionales ausentes no generan encabezado. El consumer `fmat-auth-service` identifica la credencial del emisor; no representa al usuario final.

Con `mustChangePassword: true`, únicamente se permite acceder a estas rutas protegidas (también con barra final):

- `POST /api/v1/auth/change-initial-password`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

El resto devuelve `403` con `code: PASSWORD_CHANGE_REQUIRED`. Las rutas públicas permanecen públicas. Después del cambio, Auth-Backend debe emitir un nuevo token con el estado actualizado; Kong no consulta la base de datos de usuarios.

Cada backend debe comprobar permisos, roles, pertenencia y acceso a recursos. El gateway **no implementa autorización por endpoint**, revocación de tokens, audiencia (`aud`) ni consulta de sesiones. Un logout no invalida por sí solo un access token ya emitido. No uses refresh tokens intercambiables con access tokens: utiliza tokens opacos o una credencial de firma distinta no aceptada por el gateway y valida el refresh en Auth-Backend. Los servicios distintos de Auth no necesitan conocer el secreto si usan exclusivamente la identidad del perímetro confiable.

`setup-admin` está expuesto sin JWT por diseño de la ruta. Auth-Backend debe permitir la inicialización solo una vez y de forma atómica; el rate limiting no garantiza esa condición. El cuerpo de login/refresh, el almacenamiento de tokens y esa lógica de inicialización pertenecen a Auth-Backend y no están implementados en este repositorio.

## Verificación y diagnóstico

Pruebas locales del plugin y del renderizador, ejecutadas con Lua 5.1 mediante Lupa y un PDK de Kong simulado:

```sh
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
```

Con Docker disponible, valida la configuración renderizada y el esquema de Kong:

```sh
docker compose exec kong kong config parse /tmp/kong.yml
docker compose exec kong kong health
```

`config parse` puede imprimir configuración sensible: no compartas su salida ni la guardes en logs públicos. Prueba también estos escenarios con tus backends activos:

```sh
# Salud de Auth-Backend a través del gateway; no es la salud interna de Kong.
curl -i http://localhost:8000/health

# Debe rechazar el acceso protegido sin token.
curl -i http://localhost:8000/api/v1/menu

# Preflight: debe responder con el origen y encabezados CORS permitidos.
curl -i -X OPTIONS http://localhost:8000/api/v1/menu -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: Authorization"
```

Comprueba además acceso con un token válido, rechazo de tokens vencidos/firma incorrecta, bloqueo con contraseña temporal y que el backend reciba identidad del token aunque el cliente envíe encabezados falsificados.

- `404`: no coincide una ruta del gateway, o el backend no implementa la ruta recibida.
- `401`: token o identidad inválida/ausente en una ruta protegida.
- `403` con `PASSWORD_CHANGE_REQUIRED`: contraseña temporal pendiente.
- `429`: límite de solicitudes alcanzado en una ruta pública.
- `502`/`503`: revisa DNS Docker, red, puerto interno, proceso y disponibilidad del backend.
- Error CORS del navegador: verifica el origen exacto, los métodos/encabezados y que la petición llegue al gateway.

El proxy de este Compose escucha HTTP en `8000`; para producción configura TLS en Kong o en un proxy frontal. La Admin API sigue accesible desde la red interna Docker y desde el host local: no la publiques en Internet. El ciclo de vida de la imagen Kong y su versión de parche deben gestionarse y verificarse antes de desplegar.
