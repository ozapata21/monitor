# NOC Python Monitor

Monitoreo de dispositivos de red (ICMP, RTSP, SNMPv3, Syslog) con API REST, RBAC, correlación de alertas y dashboard.

## 1. Configuración

El archivo `.env` define los secretos. Si no existe:

```bash
cp .env.example .env
```

Completa `APP_SECRET_KEY`, `JWT_SECRET_KEY`, `FIRST_ADMIN_PASSWORD` y `DB_PASSWORD` (los comandos para generar las claves de la aplicación están en `.env.example`). No compartas las credenciales.

La aplicación usa un servidor MySQL externo; Compose **no inicia un contenedor MySQL**. En `.env`, configura `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`. Para Docker en Linux, `DB_HOST_DOCKER=host.docker.internal` permite que el contenedor de la API alcance el MySQL instalado en la máquina anfitriona. Si MySQL está en otro servidor, define `DB_HOST_DOCKER` con su IP o nombre DNS. Sin Docker, la aplicación usa `DB_HOST` directamente (por ejemplo, `localhost`). El usuario MySQL debe tener permisos sobre la base para crear y usar las tablas.

El esquema se crea al iniciar la API si faltan tablas. El cambio de SQLite a MySQL **no copia automáticamente los datos existentes**; respalda y migra los datos antes de cambiar una instalación con información que deba conservarse.

La contraseña del administrador inicial se consulta con:

```bash
grep FIRST_ADMIN .env
```

Si cambias `APP_SECRET_KEY` después de registrar equipos, sus credenciales cifradas dejan de poder descifrarse.

## 2. Tests (sin Docker)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

Deben pasar 20 tests.

## 3. Levantar con Docker

```bash
docker compose up -d --build
```

Si el puerto 8000 está ocupado: `API_PORT=18000 docker compose up -d --build`. También se pueden cambiar `DASHBOARD_PORT` y `SYSLOG_HOST_PORT`.

| Servicio | URL |
|---|---|
| API y Swagger | http://localhost:8000/docs |
| Dashboard | http://localhost:8501 |

```bash
docker compose logs -f api   # logs
docker compose down          # detener
```

## 4. Probar en Swagger

1. **Authorize** con `admin` y la contraseña de `.env`.
2. `POST /users`: crear un usuario `OPERATOR` y otro `VIEWER`.
3. `POST /devices`: registrar un switch (por ejemplo `10.0.0.1`, tipo `SWITCH`) y copiar su `id`.
4. `POST /devices`: registrar una cámara con `parent_device_id` igual al `id` del switch (puede llevar `rtsp_url`).
5. Permisos: con el token `VIEWER`, `POST /devices` devuelve 403. Con `OPERATOR`, `DELETE` devuelve 403.
6. `GET /audit-logs` (admin): muestra los registros de lo anterior.

| Endpoint | Viewer | Operator | Admin |
|---|---|---|---|
| `GET /devices`, `/devices/{id}`, `/devices/{id}/metrics`, `/alerts` | sí | sí | sí |
| `POST`/`PATCH /devices` | no | sí | sí |
| `DELETE /devices/{id}` | no | no | sí |
| `POST /users`, `GET /audit-logs` | no | no | sí |

## 5. Ver el monitoreo

- El sondeo corre cada 30 s (`POLL_INTERVAL`). Para ver resultados rápido, agrega `POLL_INTERVAL=5` a `.env` y reinicia.
- Registra equipos con IPs reales de tu red. Los dispositivos nuevos entran al sondeo en un máximo de 60 s (`DEVICE_REFRESH_INTERVAL`).
- El dashboard muestra estado, métricas y alertas con el mismo usuario de la API.

## 6. Probar la correlación

1. Registra un switch padre con una IP que no responda (por ejemplo `10.255.255.1`) y una cámara hija con otra IP sin respuesta.
2. Espera uno o dos ciclos de sondeo.
3. `GET /alerts` debe mostrar solo la alerta `DOWN` del padre.

La prueba automática equivalente está en `tests/test_stage4.py`.

## 7. Probar syslog

```bash
echo "<11>link down puerto 3" | nc -u -w1 localhost 5514
```

Solo se guarda si la IP de origen coincide con un dispositivo registrado. Desde tu máquina el origen puede ser `127.0.0.1` o la IP del puente de Docker.

## 8. Alertas externas (opcional)

Define `WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`, o la configuración SMTP siguiente en `.env`. Reinicia con `docker compose up -d` para aplicar los cambios.

Para correo con SMTP y STARTTLS (por ejemplo, Gmail con contraseña de aplicación):

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=tu-correo@gmail.com
SMTP_PASSWORD=tu-contraseña-de-aplicación
SMTP_FROM=tu-correo@gmail.com
ALERT_EMAIL_TO=destinatario@ejemplo.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
```

Para SMTP implícito SSL, normalmente en el puerto 465, usa `SMTP_USE_SSL=true` y `SMTP_USE_TLS=false`. El correo se envía para cada transición de alerta (caída, recuperación y flapping); si una caída de un dispositivo hijo queda suprimida por la correlación con su padre, no se envía una alerta separada para ese hijo.

Los intentos quedan registrados en `email_notifications.log`. Con Docker, el archivo persistente está en el volumen de datos y se puede seguir con:

```bash
docker compose exec api tail -f /data/email_notifications.log
```

Sin Docker, la ruta predeterminada es `logs/email_notifications.log` (o la indicada en `EMAIL_LOG_FILE`). `ACCEPTED_BY_SMTP` significa que el servidor SMTP aceptó el mensaje, no confirma su entrega a la bandeja. Los fallos registran el tipo y la respuesta de error, sin guardar la contraseña SMTP ni el contenido del correo. El archivo rota a 5 MB y conserva tres respaldos.

## Desarrollo sin Docker

```bash
.venv/bin/uvicorn main:app --reload
.venv/bin/streamlit run dashboard/app.py
```

`create_all` crea tablas nuevas, pero no modifica tablas existentes. Para cambios de esquema futuros se requiere una migración explícita.

## comandos en mysql

CREATE USER 'monitorti'@'172.18.%' IDENTIFIED BY 'andro470';

GRANT ALL PRIVILEGES ON monitor.* TO 'monitorti'@'172.18.%';

SHOW GRANTS FOR 'monitorti'@'172.18.%';

## cambios en /etc/mysql/mysql.conf.d/mysqld.cnf
bind-address            = 172.17.0.1
