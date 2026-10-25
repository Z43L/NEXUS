# NEXUS × Atenhea — Hito H0

Integración en un solo equipo según la spec v0.1 (§11, H0): Router mínimo +
Atenhea real + ledger local + recibos firmados. Sin red externa, sin cadena.

## Piezas

| Fichero | Qué hace |
|---|---|
| `router.py` | Router + ledger SQLite (`nexus_h0.db`): cola de trabajos, registro de nodos, verificación de recibos firmados, resumen de liquidación y gateway de chat |
| `worker_agent.py` | Sidecar del nodo: pide trabajos al Router y los ejecuta contra el **motor** de Atenhea (`:11436`), nunca contra el proxy de agentes (`:11434`) → los trabajos H0 no tocan la memoria CHL ni herramientas locales |
| `nexus_common.py` | Recibos canónicos Ed25519, precios de referencia y reparto (spec §8.1/§8.4) |
| `dogfood_client.py` | Envía el lote, espera y escribe `h0_report.json` con la puerta H0 evaluada |
| `gen_jobs.py` | Genera `jobs.jsonl`: 100 trabajos tipo fábrica de novelas + 1 sonda con `tools` que debe ser **rechazada** |
| `mock_atenea.py` | Motor falso determinista para probar todo sin el Mac |
| `test_h0.py` | Test E2E contra el mock (lote, gateway, SDK, UI loopback, firmas, failover, aliases de modelo y workers H1 paralelos) |
| `run_h0_mac.sh` | Arranque completo en el Mac de David en un solo comando |

Desviación H0 respecto a la spec: el precio se contabiliza en micro-USD al
precio de referencia de la spec §8.4, sin token todavía (eso es H1, testnet).

El router escucha únicamente en `127.0.0.1`; esta implementación H0 no debe
exponerse a Internet ni usarse como servicio multiusuario. Los nodos deben
estar registrados y solo reciben trabajos para modelos que anuncian. Los
recibos se rechazan si no verifican firma, identidad, hash de salida, precio,
reparto o discrepancia de medición.

El Router firma JWT Ed25519 de vida corta (30 min), limitados a un nodo y un
trabajo. El worker valida firma, audiencia, emisor, destinatario, trabajo y
expiración antes de ejecutar. La clave privada del router se guarda en
`router_key.pem` dentro del directorio de datos, con permisos restrictivos.
El registro, heartbeats, polling y entrega de resultados firman método, ruta,
timestamp, nonce y cuerpo con la clave de nodo. El router rechaza firmas
repetidas o caducadas. Cada asignación tiene un lease de 30 minutos; si expira,
se reencola hasta tres intentos y después se marca como fallida.
El worker también puede pedir `status: retry` tras un fallo transitorio de
Atenhea; el Router valida la firma y JWT de la asignación y reencola
inmediatamente, sin recibo. Cada despacho cuenta como intento; al alcanzar
tres intentos, el retry termina el job como `failed`. Solo errores de transporte,
timeouts, HTTP 429 y HTTP 5xx son transitorios; otros errores son terminales.
No hay backoff adicional en H0: la reejecución comienza en el siguiente poll
del worker.

El modo de red privada es separado y se activa solo con `--mode remote`. Exige
HTTPS, certificado/key, ficheros de token `0600`, y bind a loopback o una IPv4
RFC1918 literal. Rechaza `0.0.0.0`, IPs públicas, configuración parcial y
opciones TLS en modo local. El worker H1 usa `--router-ca` para validar la CA y
hostname/SAN; el alta de claves nuevas exige el token de enrolamiento. Chat,
modelos, jobs, ledger y métricas requieren bearer auth. Sigue sin ser un
despliegue público; ver `nexus-h1-node/README_MAC_NODE.md` para el procedimiento
privado y la custodia de ficheros.

El contenido de los trabajos se conserva 30 días por defecto. Al expirar, el
Router borra `payload` y `result_text`, conserva recibos y metadatos, marca como
fallidos trabajos todavía en cola o con lease, y devuelve
`content_expired: true`/`output_text: null` en el endpoint de estado. La purga
se ejecuta al arrancar, periódicamente y durante las peticiones. Cambia el
plazo con `--content-retention-days` (1–3650). Las bases existentes se migran
calculando la expiración desde `created_at`; el contenido antiguo que ya pasó
el plazo se elimina al iniciar.

## API de inferencia local

El router implementa `POST /v1/chat/completions` para peticiones de texto no
streaming. Acepta `model`, `messages`, `temperature`, `max_tokens` y el
parámetro local `timeout_s` (1–1800). La respuesta sigue la forma básica de
Chat Completions y contiene `choices[0].message.content` y `usage`. Streaming,
tools y mensajes multimodales no forman parte de H0. Las peticiones largas
pueden devolver `504` con el identificador del trabajo, que continúa
consultable en `GET /jobs/{job_id}`.
`GET /v1/models` enumera los modelos que anuncian los workers registrados.
Cada worker selecciona el modelo pedido entre los IDs anunciados (admite el
alias `:latest`); si no está disponible, rechaza el job. El Router comprueba
que el modelo firmado en el recibo corresponde al solicitado antes de aceptar
el resultado.
`GET /health` comprueba que el proceso responde, `/ready` comprueba acceso a
SQLite y `/metrics` publica métricas Prometheus del router local.

El Router limita sus handlers totales con `--max-threads` (2–512, por defecto
64) y reserva al menos un handler para polling/resultados de workers: las
peticiones síncronas de chat se limitan a `max_threads - min(8, max(1,
max_threads // 8))`. Si se alcanza ese límite, una petición de chat nueva recibe
`503 server_busy` con `Retry-After: 1`. Si se agota también la capacidad total,
el servidor responde `503` sin bloquear el accept loop. Esta reserva protege el
camino de workers frente a chats largos; otros endpoints no-chat siguen
compartiendo el límite total y pueden recibir `503` durante una saturación
general.

### Fachada FastAPI opcional

La fachada compatible del backend Python está en
`nexus/api/core/api_server.py`. Expone `/v1/chat/completions`, `/v1/models`,
`/cognitive/query`, `/cognitive/infer`, `/health` y `/ready`, y reenvía la
inferencia al Router H0. Arranca primero Router y worker con `./run_h0_local.sh`;
en otra terminal, desde `NEXUS/nexus/h0`, ejecuta:

```sh
../api/run_h0_api.sh
```

La primera ejecución crea `nexus/api/.venv` e instala solo FastAPI y Uvicorn.
La API escucha en `127.0.0.1:8000`; valida que el Router configurado mediante
`NEXUS_H0_ROUTER_URL` también use loopback. `NEXUS_API_PYTHON` permite usar un
Python ya preparado y `NEXUS_API_PORT` cambia el puerto local. La verificación
`GET http://127.0.0.1:8000/ready` comprueba que el Router responde. Esta
fachada no inicializa el stack legado de Weaviate/AGE/ReAct, y no soporta
streaming, tools ni contenido multimodal.

La consola web local opcional está en `NEXUS/nexus-web/h0_local.py`; arráncala
con el Router activo y abre <http://127.0.0.1:18081>. Solo sirve el HTML y
reenvía modelos, chat y consultas limitadas `GET /jobs/job_N` al Router de
loopback. Si el Router devuelve HTTP 504 con un ID, la UI consulta el trabajo
hasta cinco minutos y conserva el texto en el campo si sigue pendiente.

Para iniciar Atenhea si hace falta, Router, worker y consola en un solo
comando, ejecuta `./run_h0_local.sh` desde este directorio. El script espera a
que haya un modelo anunciado y deja Atenhea activa al salir con Ctrl-C; Router,
worker y consola se cierran. Los logs quedan en `logs/` dentro del directorio de
datos H0, junto con el ledger y las claves; el launcher los crea con umask 077.
La primera ejecución crea `.venv` e instala `cryptography==50.0.2`; para usar un Python
ya preparado, define `NEXUS_PYTHON` con la ruta de su ejecutable.
El ledger y las claves quedan fuera del checkout por defecto: en macOS,
`~/Library/Application Support/NEXUS/H0`; en Linux y otros Unix,
`$XDG_STATE_HOME/nexus-h0` (o `~/.local/state/nexus-h0`). Define
`NEXUS_H0_DATA_DIR` para elegir otra ruta. Con la ruta predeterminada, el
launcher fija el directorio dedicado en modo 0700. Para una ruta personalizada
imprime una advertencia y respeta sus permisos existentes; asegúrate de que sea
privada y dedicada antes de usarla. No cambia permisos recursivamente. Respalda
las claves aparte del ledger.
El launcher instala [`requirements-h0.txt`](requirements-h0.txt), que fija
`cryptography==50.0.2`. Es un pin directo reproducible, sin hashes ni lock
transitivo de `cffi`/`pycparser`; una instalación nueva necesita acceso al
índice de paquetes. Si se define `NEXUS_PYTHON`, ese Python debe tener la misma
versión instalada.
La puerta real limitada ejecutada en este entorno está resumida en
`docs/evidence/h0-real-2026-10-25.json` desde la raíz del repositorio.

## Chat en navegador

La interfaz mínima local usa ese mismo contrato, sin depender de los endpoints
del API server antiguo. Con Router y worker activos, ejecuta
`python3 NEXUS/nexus-web/h0_local.py` desde la raíz del repo y abre
<http://127.0.0.1:18081>. La guía y límites están en
[`nexus-web/README_H0.md`](../../nexus-web/README_H0.md). El SDK TypeScript
compila con `cd NEXUS/nexus-sdk-js && npm ci && npm run build`.

## En el Mac (un comando)

```sh
cd ~/Desktop/NEXUS/NEXUS/nexus/h0 && ./run_h0_mac.sh
```

El script: crea `.venv` (instala `cryptography==50.0.2` desde el pin H0), arranca Atenhea desde
el checkout integrado `NEXUS/atenhea` si no está en marcha, levanta Router y worker, ejecuta los
100 trabajos + la sonda y deja el informe en `h0_report.json`. Si encuentra
una base de datos o informe previo, los mueve a un respaldo con marca de
tiempo. Al terminar apaga Router y worker; Atenhea queda encendida. La primera vez la descarga e
instalación de la dependencia H0 tarda ~1 min; el lote de 100 trabajos es batch
y puede tardar (el informe registra tokens/s reales del E2B).

## Puerta H0 (en `h0_report.json` → `gate`)

- `100_jobs_done`: los 100 trabajos terminan.
- `all_receipts_verified`: todos los recibos Ed25519 verifican en el Router.
- `discrepancy_le_1pct`: conteo del ledger vs conteo del motor ≤ 1 %.
- `tools_probe_rejected`: la sonda con herramientas es rechazada por el worker.

## Probar sin Mac (en cualquier máquina)

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-h0.txt
.venv/bin/python test_h0.py
.venv/bin/python test_secure_remote.py
```

La puerta ejecuta 100 trabajos de inferencia en el mock y comprueba 100
recibos, discrepancia ≤1%, rechazo de tools, firma manipulada, fallback de
conteo y entrega de una respuesta por el gateway. El test también inicia dos
workers H1 en paralelo para comprobar reparto, autenticación y recibos. El mock
valida el flujo de integración; no mide el rendimiento del modelo real.
El test seguro crea certificados temporales y usa únicamente loopback; no abre
un socket en la red privada ni prueba un despliegue remoto.

## Copia y restauración del ledger

Detén Router y workers antes de copiar el ledger para obtener una copia SQLite
consistente. Usa la API de backup de SQLite:

```sh
cd NEXUS/nexus/h0
sqlite3 nexus_h0.db ".backup 'nexus_h0.db.backup'"
```

Para restaurar, conserva aparte el archivo actual y coloca la copia en su lugar
con Router detenido:

```sh
cp nexus_h0.db.backup nexus_h0.db
```

El ledger incluye historial de trabajos y recibos, pero no las claves privadas
de nodos ni la clave del Router (`node/`, `router_key.pem`). Respalda esas
claves por un canal cifrado y separado. Perder la clave del Router invalida los
tokens de despacho activos; perder la clave de un nodo requiere registrarlo
con una identidad nueva. No subas copias, claves ni bases de datos a Git.

## Configuración y credenciales

H0 local no usa credenciales de proveedor: por defecto habla con Atenhea en
`127.0.0.1:11436`. No expongas `18080` a una red externa. El backend general
requiere secretos por variables de entorno (`OPENROUTER_API_KEY`,
`OPENAI_API_KEY` y, cuando se use memoria autenticada, `MEMORY_API_KEY`). No
pongas sus valores en YAML, CLI, informes ni logs. Las credenciales que se
hayan guardado anteriormente en Git deben revocarse en el proveedor; quitar
un secreto de la configuración activa no borra el historial Git.
