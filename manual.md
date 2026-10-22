# Manual de usuario – NOC Python Monitor

## 1. ¿Qué es?

NOC Python Monitor vigila el estado de tus equipos de red (cámaras, switches, routers y enlaces). Revisa cada equipo de forma automática, muestra su estado en un panel y genera alertas cuando algo falla o se recupera.

Se usa de dos formas:

- **Dashboard** (panel web): para consultar el estado, las métricas y las alertas.
- **API / Swagger**: para registrar y administrar dispositivos y usuarios.

Las direcciones las proporciona tu administrador. Por defecto:

| Servicio | Dirección |
|---|---|
| Dashboard | `http://<servidor>:8501` |
| API y Swagger | `http://<servidor>:8000/docs` |

## 2. Roles y permisos

| Acción | Viewer | Operator | Admin |
|---|:-:|:-:|:-:|
| Ver dispositivos, métricas y alertas | Sí | Sí | Sí |
| Registrar y modificar dispositivos | No | Sí | Sí |
| Eliminar dispositivos | No | No | Sí |
| Crear usuarios | No | No | Sí |
| Ver registro de auditoría | No | No | Sí |

Si intentas una acción sin permiso, la API responde **403**.

## 3. Entrar al dashboard

1. Abre `http://<servidor>:8501`.
2. Escribe tu **usuario** y **contraseña**, y pulsa **Ingresar**.
3. Para salir, usa **Cerrar sesión** en el menú lateral.

Si ves «Usuario o contraseña incorrectos», verifica tus datos. Si ves «No se pudo contactar la API», avisa al administrador.

## 4. Usar el dashboard

El panel se actualiza solo cada 30 segundos.

### 4.1 Estado general
Cuatro contadores con el número de equipos por estado:

| Estado | Significado |
|---|---|
| **UP** | El equipo responde con normalidad |
| **DEGRADED** | Responde, pero con problemas |
| **DOWN** | No responde |
| **UNKNOWN** | Aún no hay datos (equipo recién registrado) |

### 4.2 Dispositivos
Tabla con nombre, IP, tipo, sitio, estado y última actualización. Usa el selector **Sitio** para filtrar por sucursal.

### 4.3 Métricas
1. Elige un **dispositivo**.
2. Elige la **métrica**:
   - `ICMP_RTT`: tiempo de respuesta del ping.
   - `ICMP_LOSS`: porcentaje de paquetes perdidos.
   - `RTSP`: disponibilidad del flujo de video (cámaras).
   - `SNMP_UPTIME`: tiempo encendido del equipo (SNMP).
3. Se muestra la gráfica. «Sin datos todavía» indica que aún no hay mediciones.

### 4.4 Alertas recientes
Muestra las últimas 50 alertas con fecha, equipo, tipo y mensaje.

| Tipo de alerta | Significado |
|---|---|
| `DOWN` | El equipo dejó de responder |
| `RECOVERY` | El equipo volvió a responder |
| `FLAPPING` | El equipo cambia de estado repetidamente (inestable) |
| `FLAPPING_RESOLVED` | El equipo se estabilizó |

**Supresión por dependencia:** si un equipo «padre» (por ejemplo, un switch) cae, no se generan alertas separadas para los equipos que dependen de él (por ejemplo, sus cámaras). Así se identifica la causa raíz.

## 5. Usar la API (Swagger)

### 5.1 Autenticarse
1. Abre `http://<servidor>:8000/docs`.
2. Pulsa **Authorize**.
3. Escribe usuario y contraseña, y confirma.

### 5.2 Tipos de dispositivo
`CAMERA`, `SWITCH`, `ROUTER`, `LINK`.

### 5.3 Registrar un dispositivo (Operator o Admin)
Endpoint `POST /devices`. Ejemplo para un switch:

```json
{
  "hostname": "SW-Principal",
  "ip_address": "10.0.0.1",
  "device_type": "SWITCH",
  "site_id": "oficina-central"
}
```

Campos:

| Campo | Obligatorio | Descripción |
|---|:-:|---|
| `hostname` | Sí | Nombre (1 a 100 caracteres) |
| `ip_address` | Sí | IP válida (IPv4 o IPv6) |
| `device_type` | Sí | Uno de los tipos de la sección 5.2 |
| `site_id` | Sí | Sitio o sucursal (hasta 50 caracteres) |
| `parent_device_id` | No | `id` del equipo del que depende |
| `rtsp_url` | No | URL RTSP, para cámaras |
| `snmp_community` | No | Comunidad SNMP |
| `snmp_v3` | No | Objeto con `user`, `auth_key` y `priv_key` (mínimo 8 caracteres cada clave) |

Las credenciales se guardan cifradas. La respuesta incluye el `id` del equipo; cópialo si vas a registrar equipos dependientes.

Ejemplo de una cámara conectada al switch anterior:

```json
{
  "hostname": "Camara-Entrada",
  "ip_address": "10.0.0.20",
  "device_type": "CAMERA",
  "site_id": "oficina-central",
  "parent_device_id": "<id-del-switch>",
  "rtsp_url": "rtsp://usuario:clave@10.0.0.20/stream1"
}
```

Un equipo nuevo entra al monitoreo en un máximo de 60 segundos. El servidor debe tener acceso de red a su IP; para equipos que solo se verifican por ping (ICMP), el equipo debe responder a ping (en Windows, el firewall lo bloquea por defecto).

### 5.4 Consultar y modificar

| Acción | Endpoint | Rol mínimo |
|---|---|---|
| Listar dispositivos (filtros: `site_id`, `device_type`, `status_`, `limit`, `offset`) | `GET /devices` | Viewer |
| Ver un dispositivo | `GET /devices/{id}` | Viewer |
| Ver métricas (filtros: `metric_type`, `limit`) | `GET /devices/{id}/metrics` | Viewer |
| Modificar un dispositivo | `PATCH /devices/{id}` | Operator |
| Eliminar un dispositivo | `DELETE /devices/{id}` | Admin |
| Ver alertas (filtros: `device_id`, `limit`, `offset`) | `GET /alerts` | Viewer |
| Ver mi usuario | `GET /auth/me` | Cualquiera |

Notas:
- `PATCH` solo cambia los campos que envías.
- No puedes eliminar un equipo que tenga dependientes (responde **409**). Elimina o reasigna primero los equipos hijos.
- La eliminación puede fallar si el equipo ya tiene alertas o métricas registradas. Consulta al administrador.

### 5.5 Crear usuarios (Admin)
Endpoint `POST /users`:

```json
{
  "username": "operador1",
  "password": "ContraseñaSegura1",
  "role": "OPERATOR"
}
```

- `username`: de 3 a 50 caracteres.
- `password`: de 8 a 72 caracteres.
- `role`: `VIEWER`, `OPERATOR` o `ADMIN`.

### 5.6 Auditoría (Admin)
`GET /audit-logs` muestra quién registró, modificó o eliminó equipos y quién creó usuarios.

## 6. Notificaciones

Si el administrador las configuró, las alertas también se envían por correo, webhook o Telegram. Se notifica cada caída, recuperación y flapping. Las caídas de equipos hijos suprimidas por la correlación no generan aviso separado.

## 7. Syslog

Los equipos pueden enviar mensajes syslog al servidor (puerto UDP 5514 por defecto). Solo se guardan los mensajes cuyo origen coincide con la IP de un dispositivo registrado.

## 8. Preguntas frecuentes

**Registré un equipo y aparece UNKNOWN.**
Espera de uno a dos ciclos de sondeo (hasta 60 segundos). Si sigue igual, revisa que el servidor alcance su IP.

**Un equipo aparece DOWN pero está encendido.**
Verifica que responda a ping y que ningún firewall bloquee el tráfico entre el servidor y el equipo.

**Recibo 403 al registrar un equipo.**
Tu usuario es Viewer. Pide un rol Operator o Admin.

**Recibo 401 o el dashboard me regresa al login.**
La sesión expiró. Vuelve a iniciar sesión.

**No llegan correos de alertas.**
Avisa al administrador para revisar la configuración SMTP y el log `email_notifications.log`.

## 9. Buenas prácticas

- Registra los switches y routers antes que los equipos que dependen de ellos, y enlázalos con `parent_device_id`.
- Usa un `site_id` consistente (por ejemplo, `oficina-central`) para poder filtrar.
- Cambia la contraseña inicial del administrador y no compartas tus credenciales.
