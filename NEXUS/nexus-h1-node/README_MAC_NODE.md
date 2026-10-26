# NEXUS H1 — worker

Worker H1: verifica el JWT de despacho antes de ejecutar, usa el motor Atenhea
local (`127.0.0.1:11436`), rechaza trabajos con `tools` y entrega recibos
Ed25519. Por defecto conecta al Router local por loopback HTTP.

## Requisitos

- Python 3.10+; el launcher crea `.venv` e instala `cryptography==50.0.2` desde
  [`requirements-h1.txt`](requirements-h1.txt). Si se define `NEXUS_PYTHON`,
  ese intérprete debe tener exactamente esa versión.
- Router H0/H1 activo.
- Motor Atenhea local con al menos un modelo en `/v1/models`.

## Arranque local

```sh
cd NEXUS/nexus-h1-node
bash run_mac_node.sh
```

El modo local permite únicamente Router HTTP en loopback. `WALLET` es una
identidad EVM opcional; el worker nunca necesita la clave privada EVM. Conserva
`node/` entre arranques para mantener la clave Ed25519 del nodo.

Ante un fallo transitorio de Atenhea (transporte, timeout, HTTP 429 o 5xx), el
worker envía un `retry` autenticado con su firma y JWT de despacho. El Router
vuelve a encolar inmediatamente hasta tres despachos; el último fallo marca el
job como `failed`. Errores no transitorios se rechazan terminalmente. H0/H1 no
aplican backoff entre reintentos.

## Router H1 en red privada

El Router debe arrancarse explícitamente con `--mode remote`, HTTPS y un bind
loopback o una IP RFC1918. No uses `0.0.0.0`, IP pública, proxy público ni
túneles públicos. El certificado TLS debe contener la IP privada exacta del
Router en su SAN y estar firmado por una CA que el worker pueda verificar.

En el Router, guarda los dos tokens en ficheros con permisos `0600`, fuera del
checkout. Los tokens no se aceptan como argumentos y no se deben mostrar en
terminales ni logs:

```sh
umask 077
mkdir -p "$HOME/.nexus-h1"
openssl rand -hex 32 > "$HOME/.nexus-h1/client.token"
openssl rand -hex 32 > "$HOME/.nexus-h1/enrollment.token"
chmod 600 "$HOME/.nexus-h1/client.token" "$HOME/.nexus-h1/enrollment.token"
```

Provisiona una CA privada y certificado de servidor con `subjectAltName` para
la IP privada elegida. Ejemplo con OpenSSL para `192.168.1.20`:

```sh
cd "$HOME/.nexus-h1"
openssl req -x509 -newkey rsa:3072 -nodes -days 365 \
  -keyout ca.key -out ca.crt -subj "/CN=NEXUS private H1 CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl req -newkey rsa:3072 -nodes -keyout router.key -out router.csr \
  -subj "/CN=192.168.1.20"
chmod 600 ca.key router.key
printf 'subjectAltName=IP:192.168.1.20\nextendedKeyUsage=serverAuth\n' > router.ext
openssl x509 -req -in router.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out router.crt -days 90 -sha256 -extfile router.ext
rm router.csr router.ext
```

Conserva `ca.key` fuera del host Router; copia `ca.crt` al worker. Arranca el
Router desde la raíz del repo:

```sh
python3 NEXUS/nexus/h0/router.py --mode remote --host 192.168.1.20 \
  --port 18080 --dir "$HOME/.nexus-h1/state" \
  --tls-cert "$HOME/.nexus-h1/router.crt" \
  --tls-key "$HOME/.nexus-h1/router.key" \
  --client-token-file "$HOME/.nexus-h1/client.token" \
  --enrollment-token-file "$HOME/.nexus-h1/enrollment.token"
```

El modo remoto rechaza opciones parciales, ficheros de secreto con permisos
abiertos y direcciones fuera de loopback/RFC1918. La clave TLS también debe
tener permisos `0600`.

Comparte la CA pública y una copia segura del token de enrolamiento con el
operador del nodo por un canal separado. En el Mac del worker, define rutas de
fichero (no el valor del token) y usa una URL HTTPS:

```sh
ROUTER_URL=https://192.168.1.20:18080 \
ROUTER_CA_FILE=/ruta/segura/ca.crt \
NODE_ENROLLMENT_TOKEN_FILE=/ruta/segura/enrollment.token \
bash run_mac_node.sh
```

El worker usa TLS con validación de cadena CA y hostname/SAN. Incluye el token
en sus peticiones de registro firmado; el Router solo lo exige para una clave
de nodo nueva, lo compara en tiempo constante y no lo persiste. Heartbeats,
polling y recibos usan las firmas Ed25519 existentes. El token de cliente
protege chat/modelos, consulta de jobs, ledger y métricas; el trabajador no lo
necesita. No se registran cuerpos, cabeceras ni valores de tokens.

## Privacidad y retención

El Router conserva prompts y respuestas durante 30 días por defecto
(`--content-retention-days` permite configurarlo). Después elimina el payload
completo y `result_text`, y conserva estado, fechas, contadores y recibos. El
`GET /jobs/{id}` posterior indica `content_expired: true` y `output_text: null`.
La respuesta síncrona de chat se entrega antes de la purga; los trabajos
recientes mantienen contenido para el polling normal.

## Verificación

`NEXUS/nexus/h0/test_h0.py` verifica despacho local, distribución y recibos.
`NEXUS/nexus/h0/test_secure_remote.py` genera credenciales temporales y
comprueba TLS, autenticación, enrolamiento de nodos y purga idempotente en
loopback. Esto no equivale a despliegue ni prueba contra infraestructura remota
o testnet.

## Router + worker en Docker Compose

La ruta Compose se define en `NEXUS/compose.h0.yml`, separada del stack
heredado `NEXUS/docker-compose.yml`. Construye imágenes mínimas para FastAPI y
para Router/worker H1. Atenhea no se
construye ni se inicia en Docker: `ATENHEA_URL` es obligatorio y debe apuntar
al **engine API** (`/v1/models`, `/v1/chat/completions`), no al proxy de agentes
`:11434`. En Docker Desktop se puede probar `http://host.docker.internal:11436`;
en Linux el engine del host debe escuchar en una dirección alcanzable desde el
bridge y el firewall debe limitar ese acceso al host/bridge de confianza. Si
Atenhea está en otra máquina o contenedor, configura su URL privada explícita.
No pongas credenciales en `ATENHEA_URL` ni habilites una ruta pública.

Requisitos: Docker Engine con Compose v2, OpenSSL, una ruta RFC1918 no usada
para la red privada del Compose y un engine Atenhea accesible desde el worker.
Desde la carpeta `NEXUS`:

```sh
./nexus-h1-node/bootstrap-compose-h0.sh
# Edita .env.h0 y configura ATENHEA_URL. Si cambias la IP/subred del Router,
# genera un certificado cuyo SAN contenga DNS:router, DNS:localhost y la IP.
docker compose --env-file .env.h0 -f compose.h0.yml config --quiet
docker compose --env-file .env.h0 -f compose.h0.yml up -d --build --wait --wait-timeout 300
docker compose --env-file .env.h0 -f compose.h0.yml ps
```

El bootstrap crea tokens aleatorios de API, Router y enrolamiento, una CA privada y
certificado TLS del Router. Los ficheros se guardan bajo `.secrets/` con modo
`0600`; `.secrets/`, `.env.h0` y `data/` están excluidos de Git y del contexto
Docker. El proceso del Router y del worker corre con el UID/GID del operador.
La clave de la CA (`.secrets/ca.key`) nunca se monta en los contenedores. El
Router persiste SQLite y su clave Ed25519 en `data/h0-router/`; la identidad
Ed25519 del worker persiste en `data/h0-worker/`. Esos directorios se crean con
modo `0700`. Respalda ambos directorios de forma cifrada; perder la identidad
del nodo requiere enrolar una clave nueva.

El Router usa TLS 1.2+, exige bearer token para chat/modelos y un token de
enrolamiento para nuevas claves. El worker confía en la CA privada y envía el
token de enrolamiento durante el registro. El Router no publica un puerto al
host: solo la API autenticada y ligada a loopback queda accesible en
`127.0.0.1:8000` (cambiable con `API_HOST_PORT`). Asegura que
`NEXUS_H0_SUBNET` no colisione con rutas Docker/VPN del host. El
certificado inicial contiene `router`, `localhost`, `127.0.0.1` y la IP
predeterminada `172.30.240.2`; si se cambia esta IP hay que reemitirlo.

El endpoint local de producto es `http://127.0.0.1:8000`; lee el token de
cliente de `.secrets/api.token` y úsalo como bearer desde un cliente local. La
API presenta `.secrets/client.token` al Router por HTTPS dentro de la red
privada y valida `.secrets/ca.crt`. No imprimas ni incluyas el contenido de
ninguno de los tokens en logs o líneas de comandos. `/ready` y los healthchecks
comprueban la disponibilidad del Router. El worker escribe un marcador de readiness solo tras descubrir el
modelo y registrarse; cada heartbeat correcto mantiene el marcador fresco, y
el healthcheck también comprueba los modelos anunciados por Atenhea. Docker
marca un servicio unhealthy, pero la política `restart` no reinicia solo por
estado unhealthy. SQLite en volumen local es una instancia única, no HA.

Smoke de chat por la entrada autenticada (el token se lee dentro del proceso y
no se imprime):

```sh
python3 - <<'PY'
import json
from pathlib import Path
from urllib.request import Request, urlopen

payload = json.dumps({
    "model": "athenea-e2b",
    "messages": [{"role": "user", "content": "Responde solo: NEXUS listo"}],
    "max_tokens": 16,
}).encode()
request = Request(
    "http://127.0.0.1:8000/v1/chat/completions",
    data=payload,
    headers={
        "Authorization": "Bearer " + Path(".secrets/api.token").read_text().strip(),
        "Content-Type": "application/json",
    },
)
with urlopen(request, timeout=90) as response:
    result = json.load(response)
print(result["choices"][0]["message"]["content"])
PY
```

Para parar sin borrar ledger ni identidades:

```sh
docker compose --env-file .env.h0 -f compose.h0.yml down
```

`down -v` no es necesario para este despliegue y los datos de `data/` son
bind-mounts locales. El Compose no instala ni publica Atenhea, no configura
renovación automática del certificado, no configura firewall ni verifica
conectividad entre hosts. Si Docker no está instalado, solo se puede validar
estáticamente el manifiesto; la construcción/ejecución debe comprobarse en un
host con Docker antes de operación compartida.
