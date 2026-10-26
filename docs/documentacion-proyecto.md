# NEXUS × Atenhea — Documentación del proyecto

> Documento de referencia para entender qué es el proyecto, qué está construido, cómo ejecutarlo y qué falta. Refleja el estado del repositorio a 2026-10-26. Las cifras y afirmaciones de estado se remiten a las fuentes indicadas en cada sección; si algo cambia, prevalece el código y la evidencia en `docs/evidence/`.

## 1. Qué es

NEXUS × Atenhea es una red de **inferencia de IA distribuida**. La idea:

- **Atenhea** es el motor de inferencia que corre en cada nodo. Ejecuta localmente el modelo Gemma 4 E2B con sus pesos originales, puede aplicar adaptadores `.nram` y tiene una memoria episódica privada.
- **NEXUS** es el plano de control: recibe trabajos, los reparte entre nodos, verifica los resultados mediante recibos firmados, mide el consumo y, en el futuro, liquida pagos.

Principios de diseño (spec §0, `docs/spec-fusion-nexus-atenea.md`):

1. **Los pesos base no viajan por la red.** Cada nodo descarga el modelo de la fuente oficial y verifica sus hashes. Lo que se distribuye son los `.nram` (adaptadores de pocos MB verificables por SHA-256).
2. **La memoria de cada nodo es privada y local.** Nunca se sincroniza.
3. **Los trabajos remotos van contra el motor, no contra el agente.** Se ejecutan sin herramientas y sin memoria CHL.
4. **La emisión de NEX se liga a trabajo pagado verificado**, no a subvenciones.

## 2. Estado en una tabla

| Hito | Qué cubre | Estado |
|---|---|---|
| **H0** — local | Router + ledger SQLite + worker + recibos Ed25519 + cliente de prueba | ✅ Funciona en local. Suite mock 100/100; puerta real con Atenhea 100/100 (salida limitada a 24 tokens). |
| **API / Compose** | SDK → FastAPI autenticada → Router TLS → worker, con UI same-origin | ✅ Probado localmente con Colima (dos cuentas, job completado, aislamiento cruzado). CI remoto pendiente. |
| **H1** — dos nodos | Worker H1 en otra máquina, Router remoto con TLS y enrolamiento | 🔄 Probado con dos workers locales. **No** se ha demostrado conectividad entre redes independientes. |
| **Liquidación EVM** | Escrow de lote ERC-20 con raíz Merkle-sum y reparto 75/10/5/5/5 | 🔄 Probado en Anvil local. **No** desplegado en testnet. |
| **H2–H4** | Marketplace `.nram`, nodos externos, beta pública | ⏳ Diseño y especificación, sin implementación validada. |

Fuentes: [`EXECUTIVE_BRIEF.md`](../EXECUTIVE_BRIEF.md), [`PROJECT_DELIVERY.md`](../PROJECT_DELIVERY.md), [`FUSION.md`](../FUSION.md).

### Pendiente antes de cualquier uso público

- CI remoto con el estado actual de los cambios.
- H1 entre redes independientes y reconexión remota de workers.
- Kubernetes: el chart Helm pasa lint y render, pero no hay clúster validado.
- Liquidación en testnet Base Sepolia y ensayo con un snapshot representativo del ledger.
- Revisión de seguridad antes de cualquier superficie pública.
- **Rotación de una credencial OpenRouter** que aparece en el historial público antiguo (commit `8445b54`). Limpiar el árbol actual no la elimina del historial. Hay que revocarla en el proveedor.

## 3. Arquitectura

```text
Cliente (SDK Python/TS, consola web, curl)
        │  POST /v1/chat/completions  (no streaming, texto)
        ▼
Fachada FastAPI  (NEXUS/nexus/api)       ← autenticación, cuentas, cuotas
        │  token upstream separado
        ▼
Router H0  (NEXUS/nexus/h0/router.py)    ← cola, leases, ledger SQLite, verificación de recibos
        ▲  polling firmado + JWT Ed25519 de corta vida
        │
Worker H0/H1  (worker_agent.py / NEXUS/nexus-h1-node)
        │  inferencia
        ▼
Motor Atenhea  (puerto 11436, NEXUS/atenhea)  ← Gemma E2B, sin herramientas ni CHL
        │
        └─► recibo firmado Ed25519 → Router verifica → ledger → (futuro) escrow EVM
```

### Piezas principales

| Pieza | Ruta | Función |
|---|---|---|
| Router H0 | `NEXUS/nexus/h0/router.py` | Gateway y cola de trabajos, ledger SQLite, verificación de firmas, discrepancias de tokens, retención de contenido de 30 días por defecto. |
| Worker | `NEXUS/nexus/h0/worker_agent.py`, `NEXUS/nexus-h1-node/worker2.py` | Pide trabajos, rechaza los que traen `tools`, llama al motor, calcula el precio y firma el recibo. |
| Compartido | `NEXUS/nexus/h0/nexus_common.py` | Recibos canónicos, precios de referencia y reparto (spec §8). |
| Fachada API | `NEXUS/nexus/api/core/api_server.py` | FastAPI que expone el contrato OpenAI-compatible; falla cerrado sin credencial. |
| Consola web | `NEXUS/nexus-web/` (`h0_local.py`, `h0.html`) | Chat mínimo. En Compose actúa como BFF: guarda el token en el servidor. |
| SDK Python | `NEXUS/nexus-sdk-python/` | Cliente asíncrono sin dependencias externas. |
| SDK TypeScript | `NEXUS/nexus-sdk-js/` | Cliente equivalente (`npm ci && npm run build`). |
| Motor Atenhea | `NEXUS/atenhea/` | Inferencia nativa, memoria CHL, microexpertos, entrenamiento y evolución LoRA. |
| Liquidación | `NEXUS/settlement-evm/` | Proyecto Foundry aislado: `InferenceEscrow.sol` con Merkle-sum V2. |
| Compose | `NEXUS/compose.h0.yml` | Empaqueta UI/BFF, API, Router TLS, worker, Valkey y perfil de motor mock. |
| Chart Helm | `NEXUS/charts/nexus/` | Lint y render correctos; no validado en clúster. |

### Modelo de recibos y verificación

- Cada trabajo produce un **recibo firmado con Ed25519** por el worker. El recibo liga el trabajo, el nodo, el modelo, el hash de salida, el precio, el reparto, los autores `.nram` usados y la discrepancia de tokens.
- El Router **rechaza** un recibo si falla la firma, la identidad del nodo, el hash, el precio, el reparto o la discrepancia de medición. También rechaza si el modelo del recibo no coincide con el pedido (incluido el alias `:latest`).
- La medición de tokens descuenta el **andamiaje fijo** del motor (≈428 tokens por petición, calibrado al arrancar y declarado en `scaffolding_tokens`). El cliente paga su carga útil y la salida, no la sobrecarga del nodo. Ver la enmienda de medición en `FUSION.md`.
- Los JWT de despacho son Ed25519, duran 30 minutos y están ligados a un nodo y un trabajo.
- Cada petición de nodo (registro, heartbeat, polling, entrega) va firmada con método, ruta, timestamp, nonce y cuerpo. Las firmas repetidas o caducadas se rechazan.

### Ciclo de vida de un trabajo

1. El cliente envía `POST /v1/chat/completions`. Si el trabajo tarda más del plazo, responde `504` con un `job_id` consultable en `GET /jobs/{job_id}`.
2. El Router crea el trabajo en la cola (`payload` en SQLite) y lo asigna con un **lease de 30 minutos**.
3. El worker lo ejecuta contra el motor. Si hay un fallo transitorio (red, timeout, HTTP 429 o 5xx), pide `retry`. Hay un máximo de **tres despachos**; después el trabajo termina en `failed`. Los errores permanentes son terminales.
4. El worker entrega el resultado con su recibo. El Router lo verifica y lo persiste.
5. Al expirar la retención, el Router borra `payload` y `result_text`, pero conserva recibos y metadatos (`content_expired: true`).

### Seguridad del Router y la red

- El Router **solo escucha en `127.0.0.1`** en modo local. No debe exponerse a Internet ni usarse como servicio multiusuario.
- El modo remoto (`--mode remote`) exige HTTPS, certificado y clave, ficheros de token con permisos `0600`, y bind a loopback o a una IPv4 RFC1918 literal. Rechaza `0.0.0.0` y las IP públicas.
- El worker valida CA y SAN con `--router-ca`. El alta de claves nuevas exige un token de enrolamiento.
- Todas las rutas de chat, modelos, trabajos, ledger y métricas requieren bearer.
- SQLite se abre con `secure_delete=ON`. Esto no cubre backups, snapshots del host ni logs; esos necesitan su propia política.
- Para la capacidad de chat, el Router reserva handlers para el polling de workers. Si se saturan, responde `503 server_busy` con `Retry-After: 1`.

### Privacidad del motor

El worker marca los trabajos de NEXUS. Atenhea no los recupera de la memoria episódica ni los guarda en ella, ni en el buffer de aprendizaje compartido. Hay una regresión que lo verifica. **Todavía no existe memoria por cuenta:** la personalización episódica queda desactivada para ese tráfico.

## 4. Cómo ejecutarlo

Los comandos siguen los README del repositorio. Todas las rutas son desde la raíz del proyecto salvo que se indique.

### 4.1 H0 con mock (sin pesos ni modelo)

Es la forma más rápida de comprobar que el sistema funciona. Valida el protocolo, no la calidad del modelo.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r NEXUS/nexus/h0/requirements-h0.txt
.venv/bin/python NEXUS/nexus/h0/test_h0.py
```

### 4.2 H0 con Atenhea real (macOS Apple Silicon)

1. Prepara Atenhea y sus assets siguiendo [`NEXUS/atenhea/README.md`](../NEXUS/atenhea/README.md). Los pesos y los `.nram` no se versionan.
2. Arranca Router, worker y consola en un solo comando:

```bash
./NEXUS/nexus/h0/run_h0_local.sh
```

   Para probar sin modelos: `NEXUS_H0_ENGINE=mock ./NEXUS/nexus/h0/run_h0_local.sh`.

3. La consola queda en <http://127.0.0.1:18081>. Ctrl-C cierra Router, worker, UI y mock. Un motor real ya activo permanece encendido.

El ledger y las claves se guardan fuera del checkout. En macOS: `~/Library/Application Support/NEXUS/H0`. Se puede cambiar con `NEXUS_H0_DATA_DIR`.

### 4.3 Petición de prueba

Con Router y worker activos:

```bash
curl http://127.0.0.1:18080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"athenea-e2b","messages":[{"role":"user","content":"Hola"}],"max_tokens":128}'
```

### 4.4 Fachada FastAPI

Con el Router levantado, en otra terminal:

```bash
cd NEXUS/nexus/h0
../api/run_h0_api.sh
```

Escucha en `127.0.0.1:8000`. Comprueba `GET /ready`. Requiere credenciales, que van en `NEXUS/.secrets/` (no versionado).

### 4.5 Compose H0/H1 (contenedores)

Requiere Docker Engine o Desktop con Compose v2, Python 3 y OpenSSL. Para un smoke sin pesos:

```bash
cd NEXUS
mkdir -p /ruta/al/volumen-cifrado/nexus-ca
NEXUS_H0_CA_KEY_OUT=/ruta/al/volumen-cifrado/nexus-ca/ca.key ./nexus-h1-node/bootstrap-compose-h0.sh
ATENHEA_URL=http://mock-atenea:11436 NEXUS_H1_ALLOW_HTTP_SERVICE_NAME=mock-atenea \
  docker compose --profile e2e --env-file .env.h0 -f compose.h0.yml up --build --detach --wait --wait-timeout 300 mock-atenea web
```

Abre <http://127.0.0.1:8080>. La API queda en <http://127.0.0.1:8000> y requiere el bearer de `NEXUS/.secrets/api.token`. Para detener sin borrar el ledger:

```bash
docker compose --profile e2e --env-file .env.h0 -f compose.h0.yml down --volumes --remove-orphans
```

La clave privada de la CA **debe** guardarse en un medio extraíble cifrado, fuera de `.secrets/`. El bootstrap no sobrescribe secretos existentes.

Para crear una cuenta humana:

```bash
cd NEXUS
PYTHONPATH=. python3 -m nexus.api.manage_api_users --registry .secrets/api_users.json add --id alice
```

### 4.6 SDKs y consola

```bash
python -m pip install ./NEXUS/nexus-sdk-python
```

```python
import asyncio, os
from nexus_client import NexusClient

async def main():
    async with NexusClient(api_key=os.environ.get("NEXUS_API_TOKEN")) as nexus:
        result = await nexus.chat("Resume la historia de NEXUS", max_tokens=256)
        print(result["choices"][0]["message"]["content"])

asyncio.run(main())
```

El SDK de TypeScript se compila con `npm ci && npm run build` dentro de `NEXUS/nexus-sdk-js`.

### 4.7 Liquidación EVM (solo Anvil local)

Proyecto Foundry en `NEXUS/settlement-evm/`. Contrato `InferenceEscrow.sol`:

- El cliente financia un lote ERC-20.
- El firmante del gateway publica la raíz Merkle-sum antes de un plazo.
- Cualquiera puede reclamar hojas válidas con sus pruebas. Cada trabajo solo se cobra una vez.
- Reparto por cada importe: 75 % worker, 10 % regalía del autor (si no hay autor, va al worker), 5 % pool de verificación, 5 % sumidero (dirección muerta), 5 % tesorería. El redondeo residual va a tesorería.
- Tras expirar, el pagador recupera el saldo no reclamado. Antes de publicar la raíz puede cancelar.

**Límite de confianza:** el contrato no verifica las firmas Ed25519 de los workers. Confía en que el firmante del gateway validó los recibos fuera de la cadena. Un firmante comprometido podría autorizar pagos incorrectos, limitados al importe depositado en el lote. La rotación de firmante es controlada por el owner.

## 5. Pruebas y evidencia

| Evidencia | Qué demuestra | Límite |
|---|---|---|
| [`h0-mock-2026-10-26.json`](evidence/h0-mock-2026-10-26.json) | E2E mock: 100 trabajos, recibos, rechazos de tools, firma y replay, SDK, UI, failover, dos workers | El throughput simulado no es un benchmark. |
| [`h0-real-2026-10-25.json`](evidence/h0-real-2026-10-25.json) | 100 trabajos con Atenhea real, salida limitada a 24 tokens | No es benchmark de salida completa. |
| [`h0-compose-2026-10-26.json`](evidence/h0-compose-2026-10-26.json) | Compose completo (UI → API → Router TLS → worker) | Local, con Colima. |
| [`auth-multiuser-compose-2026-10-26.json`](evidence/auth-multiuser-compose-2026-10-26.json) | Login/logout, dos cuentas, aislamiento cruzado | Local. |
| [`settlement-anvil-2026-10-26.json`](evidence/settlement-anvil-2026-10-26.json) | Liquidación E2E con recibos verificados en Anvil | Solo loopback, no testnet. |

Los workflows activos están en `.github/workflows/` (raíz): `h0-compose` y `settlement-evm`. Los manifiestos heredados de `NEXUS/.github/` no se ejecutan porque GitHub no los descubre allí.

Las suites heredadas (`NEXUS/tests/`) cubren memoria, seguridad, consenso, P2P, LLM y carga. **No se han ejecutado de forma exhaustiva** en esta revisión; se consideran inventario de diseño hasta validarlas módulo a módulo.

## 6. Mapa del repositorio

```text
NEXUS/                      (raíz del proyecto de código)
├── nexus/                  Backend Python
│   ├── h0/                 ★ Router, worker, cliente, tests H0 (ruta activa)
│   ├── api/                ★ Fachada FastAPI autenticada (ruta activa)
│   ├── blockchain/, consensus/, economics/, governance/,
│   │   knowledge/, network/, security/, privacy/, tokenomics/,
│   │   reasoning/, llm/, sync/, monitoring/    Subsistemas heredados, madurez desigual
│   └── core/               Inicialización y memoria heredadas
├── atenhea/                ★ Motor de inferencia local (Gemma E2B, CHL, .nram)
├── nexus-h1-node/          ★ Worker H1 y arranque Mac/Compose
├── nexus-web/              ★ Consola web y BFF
├── nexus-sdk-python/       ★ SDK Python
├── nexus-sdk-js/           ★ SDK TypeScript
├── settlement-evm/         ★ Escrow EVM en Foundry (aislado)
├── contracts/              15 contratos Solidity heredados (no desplegados como sistema)
├── nexus-blockchain/       Implementación Rust/Substrate (no integrada con H0)
├── compose.h0.yml          ★ Compose H0/H1
├── docker-compose.yml      Compose heredado (solo desarrollo local)
├── charts/, kubernetes/, infra/   Despliegues Helm/K8s/Terraform (no validados)
├── monitoring/, scripts/, config/, risk_management/, backup/
└── tests/                  Suites heredadas

docs/                       Especificación y evidencia
├── spec-fusion-nexus-atenea.md     Spec v0.1 (diseño, hitos H0–H4)
└── evidence/                       Resultados de las puertas

FUSION.md                   Visión consolidada y enmiendas
PROJECT_DELIVERY.md         Plan de entrega por verticales y puertas
EXECUTIVE_BRIEF.md          Hoja ejecutiva y límites
```

Los elementos marcados con ★ son la ruta de código activa y verificada. El resto está presente en el árbol pero no debe considerarse integrado ni listo para producción solo por existir. Algunos módulos heredados son esqueletos o tienen métodos faltantes; la spec los identifica expresamente (`marketplace_contract.py`, `reputation.py`, `asset_types.py` están vacíos).

## 7. Qué no es (todavía)

- No es una red multi-host en producción.
- No hay token NEX emitido ni pagos reales.
- No hay streaming, herramientas ni entrada multimodal en la ruta H0.
- No hay memoria por cuenta; la memoria CHL es local a cada nodo.
- No es un benchmark de rendimiento: las cifras de tokens por segundo de los informes mock no son mediciones válidas.
- La calidad del modelo no está evaluada por la suite mock.

## 8. Glosario

| Término | Significado |
|---|---|
| **Atenhea** | Motor de inferencia local (antes `athenea`/`onram`). |
| **Gemma E2B** | Checkpoint base del modelo, en BF16 Safetensors. |
| **`.nram`** | Contenedor de adaptador o microexperto verificable por hash. |
| **CHL** | Memoria episódica privada del nodo. |
| **H0 / H1–H4** | Hitos de la spec: H0 local, H1 dos nodos, H2 marketplace `.nram`, H3 nodos externos, H4 beta pública. |
| **Recibo** | Documento firmado por el worker con el resultado y su medición. |
| **Lease** | Reserva temporal de un trabajo por un worker (30 min). |
| **Andamiaje** | Tokens fijos que el motor añade a cada petición; no se cobran al cliente. |
| **Merkle-sum** | Árbol de Merkle donde cada nodo acumula un importe; sirve para liquidar lotes. |

---

*Documento generado a partir del código y de la documentación existente del repositorio. Fuentes principales: `README.md`, `FUSION.md`, `EXECUTIVE_BRIEF.md`, `PROJECT_DELIVERY.md`, `docs/spec-fusion-nexus-atenea.md`, `NEXUS/nexus/h0/README_H0.md`, `NEXUS/atenhea/README.md`, `NEXUS/settlement-evm/README.md`, `NEXUS/nexus-h1-node/README_MAC_NODE.md`.*
