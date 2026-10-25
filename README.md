# NEXUS × Atenhea

NEXUS coordina trabajos y nodos; Atenhea ejecuta inferencia local. La meta del proyecto es una red donde cada operador conserva sus pesos base y memoria privada, recibe trabajos aislados sin herramientas y presenta recibos firmados para medición y futura liquidación.

## Estado actual

- **H0 local:** router/gateway, cola SQLite, worker sidecar y recibos Ed25519/JWT. El router escucha en loopback.
- **Gateway:** `POST /v1/chat/completions`, texto no streaming, respuesta estilo OpenAI. Tools y entrada multimodal no están soportadas en H0.
- **Verificación:** recibos ligados al trabajo y nodo, autoría NRAM solicitada, hash de salida, precio/reparto y discrepancia de tokens.
- **Protección bajo concurrencia:** chats síncronos limitados con capacidad de handlers reservada para polling/resultados; selección del modelo requerido y verificación de que el modelo del recibo coincide.
- **Clientes/API:** fachada FastAPI con auth opcional, rate limit de proceso único y respuesta de error preservada; SDKs Python/TypeScript extienden el timeout HTTP más allá del deadline de trabajo.
- **Despliegue H1:** hay una ruta Compose separada en `NEXUS/compose.h0.yml` con TLS/auth y Atenhea como engine externo. El YAML pasó validación estática, pero todavía requiere Docker para validar configuración, build y ejecución.
- **Pruebas verificadas:** suite E2E mock (100 trabajos, recibos, SDK Python, UI, replay, failover y dos workers locales) y puerta Atenhea real (100 trabajos, recibos válidos, salida limitada a 24 tokens). El launcher se probó con mock y Atenhea real mediante la consola.
- **Pendiente:** H1 entre redes independientes, ejecución de CI, ensayo con snapshot representativo de ledger, Base Sepolia y revisión de seguridad antes de cualquier superficie pública. El E2E Anvil levanta Router, worker y mock, obtiene recibos verificados de su ledger y liquida el lote solo en loopback.

Una credencial OpenRouter de aspecto real está presente en el historial público antiguo `8445b54`; hay que revocarla/rotarla en el proveedor y coordinar limpieza del historial. El checkout actual ya usa `OPENROUTER_API_KEY` de entorno.

El backend cognitivo, P2P, contratos, tokenómica, UIs y despliegues heredados no deben considerarse integrados ni listos para producción solo por estar presentes en el árbol.

## Requisitos para H0

- Python 3.10 o posterior.
- Para el mock: no hacen falta pesos ni assets del modelo.
- Para modo real: motor Atenhea local con API compatible en `http://127.0.0.1:11436` y assets locales.
- `cryptography==50.0.2`, instalado desde `NEXUS/nexus/h0/requirements-h0.txt`.

## Probar con el mock

Desde la raíz del repositorio:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r NEXUS/nexus/h0/requirements-h0.txt
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
