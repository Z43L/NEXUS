# NEXUS × Atenhea

NEXUS coordina trabajos y nodos; Atenhea ejecuta inferencia local. La meta del proyecto es una red donde cada operador conserva sus pesos base y memoria privada, recibe trabajos aislados sin herramientas y presenta recibos firmados para medición y futura liquidación.

## Estado actual

- **H0 local:** router/gateway, cola SQLite, worker sidecar y recibos Ed25519/JWT. El router escucha en loopback.
- **Gateway:** `POST /v1/chat/completions`, texto no streaming, respuesta estilo OpenAI. Tools y entrada multimodal no están soportadas en H0.
- **Verificación:** recibos ligados al trabajo y nodo, autoría NRAM solicitada, hash de salida, precio/reparto y discrepancia de tokens.
- **Protección bajo concurrencia:** chats síncronos limitados con capacidad de handlers reservada para polling/resultados; selección del modelo requerido y verificación de que el modelo del recibo coincide.
- **Clientes/API:** fachada FastAPI con API keys técnicas y cuentas de usuario scrypt, sesiones opacas en Valkey, cookies HttpOnly, invalidación por cambios de credenciales/permisos y cuotas distribuidas atómicas; SDKs Python/TypeScript extienden el timeout HTTP más allá del deadline del trabajo.
- **Privacidad del motor:** el worker marca los trabajos NEXUS y Atenhea evita recuperarlos o guardarlos en la memoria episódica/buffer compartido; memoria CHL particionada por cuenta aún no existe.
- **Despliegue H1:** la ruta Compose de `NEXUS/compose.h0.yml` empaqueta UI/BFF, API, Router TLS privado, worker, Valkey y perfil de engine mock. Se construyó y ejecutó localmente con Colima contra mock y Atenhea real local; UI/API solo se publican en loopback. El chart Helm pasa lint/render, pero no hay clúster validado.
- **Pruebas verificadas:** suite H0 mock (100 trabajos, recibos, SDK Python, UI, replay, failover y dos workers locales), puerta Atenhea real (100 trabajos con salida máxima de 24 tokens) y E2E Compose multiusuario (login/logout, dos cuentas, job completado y aislamiento cruzado). Evidencia: `docs/evidence/h0-mock-2026-10-26.json`, `docs/evidence/h0-compose-2026-10-26.json` y `docs/evidence/auth-multiuser-compose-2026-10-26.json`. El throughput simulado no es una medida de rendimiento.
- **Pendiente:** CI remoto, H1 entre redes independientes, Kubernetes runtime, ensayo con snapshot representativo del ledger, Base Sepolia y revisión de seguridad antes de una superficie pública. El E2E Anvil liquida recibos verificados de Router solo en loopback, no en testnet.

Una credencial OpenRouter de aspecto real está presente en el historial público antiguo `8445b54`; hay que revocarla/rotarla en el proveedor y coordinar limpieza del historial. El checkout actual ya usa `OPENROUTER_API_KEY` de entorno.

El backend cognitivo, P2P, contratos, tokenómica, UIs y despliegues heredados no deben considerarse integrados ni listos para producción solo por estar presentes en el árbol.

## Requisitos para H0

- Python 3.10 o posterior.
- Para el mock: no hacen falta pesos ni assets del modelo.
- Para modo real: motor Atenhea local con API compatible en `http://127.0.0.1:11436` y assets locales.
- `cryptography==50.0.2`, con hashes SHA-256 para Linux glibc x86_64/aarch64 y macOS arm64, incluido desde `NEXUS/nexus/h0/requirements-h0.txt`.

## Probar con el mock

Desde la raíz del repositorio:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r NEXUS/nexus/h0/requirements-h0.txt
.venv/bin/python NEXUS/nexus/h0/test_h0.py
```

La prueba E2E levanta y elimina sus procesos temporales. El motor simulado valida el protocolo, no la calidad ni el rendimiento de Gemma.

El SDK JavaScript/TypeScript se encuentra en `NEXUS/nexus-sdk-js`; compílalo
con `npm ci && npm run build`. Los dos SDKs y el chat web usan el contrato
local no streaming de `/v1/chat/completions`.

## Ejecutar H0 contra Atenhea

1. Instala y prepara Atenhea y sus assets siguiendo [`NEXUS/atenhea/README.md`](NEXUS/atenhea/README.md). Los pesos y el bundle `.nram` no se versionan con NEXUS.
2. Desde la raíz, inicia Router, worker y consola en un comando:

```sh
./NEXUS/nexus/h0/run_h0_local.sh
```

Por defecto reutiliza un motor activo o arranca Atenhea si encuentra todos los
assets; si faltan, informa las rutas antes de fallar. Para probar el camino
local sin modelos:

```sh
NEXUS_H0_ENGINE=mock ./NEXUS/nexus/h0/run_h0_local.sh
```

La consola queda en <http://127.0.0.1:18081>. Ctrl-C cierra Router, worker,
UI y mock; un motor real ya activo permanece encendido. El ledger y las claves
se guardan fuera del checkout por defecto; `NEXUS_H0_DATA_DIR` permite elegir
otro directorio privado. El resultado de 100 trabajos reales y los smokes del
launcher están en [`docs/evidence/h0-real-2026-10-25.json`](docs/evidence/h0-real-2026-10-25.json).
`run_h0_mac.sh` sigue disponible para ejecutar el lote batch y escribir
`h0_report.json` en un Mac con Atenhea real.

## Usar el gateway

Con router y worker activos, una petición local:

```sh
curl http://127.0.0.1:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"athenea-e2b","messages":[{"role":"user","content":"Hola"}],"max_tokens":128}'
```

La respuesta incluye `choices[0].message.content` y `usage`. H0 solo enlaza a `127.0.0.1`: no publiques ese puerto ni lo uses para tráfico multiusuario.

## Ruta integrada Compose H0/H1

Esta ruta empaqueta la consola same-origin, FastAPI autenticada, Router TLS y
worker H1. La UI y API solo se publican en loopback; Atenhea es un servicio
externo al Compose. La configuración, el build ARM64 y el runtime Compose se
validaron localmente con Colima; la evidencia incluye dos cuentas y una
inferencia completada. El worker solo omite la API key para motores en
loopback. El host Docker, servicios Compose y motores remotos requieren una
clave de servicio; un listener Atenhea fuera de loopback exige además HTTPS
con certificado verificable.

Requisitos: Docker Engine/Desktop con Compose v2, Python 3 y OpenSSL. Para un
smoke reproducible sin pesos, provisiona credenciales locales y arranca el
mock privado del perfil E2E:

```sh
cd NEXUS
mkdir -p /ruta/al/volumen-cifrado/nexus-ca
NEXUS_H0_CA_KEY_OUT=/ruta/al/volumen-cifrado/nexus-ca/ca.key ./nexus-h1-node/bootstrap-compose-h0.sh
ATENHEA_URL=http://mock-atenea:11436 NEXUS_H1_ALLOW_HTTP_SERVICE_NAME=mock-atenea \
  docker compose --profile e2e --env-file .env.h0 -f compose.h0.yml up --build --detach --wait --wait-timeout 300 mock-atenea web
```

Abre <http://127.0.0.1:8080>, inicia sesión con una cuenta provisionada y envía
un chat. La UI usa cookies HttpOnly y no recibe el bearer técnico. FastAPI
también está disponible en <http://127.0.0.1:8000> y requiere el bearer de
`NEXUS/.secrets/api.token`. Para
detener los contenedores sin borrar el ledger o los datos del worker:

```sh
docker compose --profile e2e --env-file .env.h0 -f compose.h0.yml down --volumes --remove-orphans
```

El bootstrap no sobrescribe secretos existentes. Antes de ejecutarlo, crea un
directorio en medio extraíble cifrado y exporta `NEXUS_H0_CA_KEY_OUT` con una
ruta absoluta fuera del proyecto; el bootstrap falla si no se indica. La clave
privada CA se guarda allí y no dentro de `.secrets/`. Para pruebas locales
efímeras puede usarse una ruta temporal, pero hay que borrarla al terminar. La
renovación recibe esa clave mediante `NEXUS_H0_CA_KEY_FILE=/ruta/offline/ca.key`
al ejecutar `./nexus-h1-node/rotate-compose-router-cert.sh`. La ruta permite
API keys de servicio y cuentas humanas con cuotas. Para provisionar una cuenta,
ejecuta desde `NEXUS` con `PYTHONPATH=.`:
`python3 -m nexus.api.manage_api_users --registry .secrets/api_users.json add --id alice`.
El comando solicita una contraseña de forma interactiva; reinicia el servicio
API para refrescar el secreto montado. No expongas esta ruta a Internet ni uses
el mock para evaluar calidad del modelo.

## Compose heredado (solo desarrollo local)

El Compose legado no inicia el camino H0. Sus puertos de Postgres, Weaviate,
API y métricas quedan enlazados a loopback. Antes de usarlo, copia
`NEXUS/.env.example` a `NEXUS/.env` y sustituye las plantillas por valores
válidos; `.env` está excluido de Git. Esta configuración no está lista para
desplegar en una red compartida.

Para una ruta separada Router H0 + worker H1 con TLS privado y un engine
Atenhea externo explícito, consulta [`NEXUS/compose.h0.yml`](NEXUS/compose.h0.yml)
y [`NEXUS/nexus-h1-node/README_MAC_NODE.md`](NEXUS/nexus-h1-node/README_MAC_NODE.md).
No mezcles esos servicios con el compose heredado: sus requisitos de red y
seguridad son distintos.

## Arquitectura y estado de entrega

- [Visión consolidada y estado H0–H4](FUSION.md)
- [Especificación de fusión](docs/spec-fusion-nexus-atenea.md)
- [Plan de entrega y puertas pendientes](PROJECT_DELIVERY.md)
- [Hoja ejecutiva del análisis del repositorio](EXECUTIVE_BRIEF.md)
- [Documentación detallada de H0](NEXUS/nexus/h0/README_H0.md)

## Credenciales

No guardes claves en archivos versionados. El backend heredado requiere `OPENROUTER_API_KEY` en el entorno; otros componentes pueden requerir `OPENAI_API_KEY` o `MEMORY_API_KEY`. La clave que antes estaba escrita en `NEXUS/config/reasoning_agent.yaml` se eliminó del archivo y fue confirmada en el commit público `8445b54` y debe revocarse/rotarse en el proveedor; limpiar el árbol actual no la elimina del historial Git.
