# NEXUS × Atenhea — Hito H0

Integración en un solo equipo según la spec v0.1 (§11, H0): Router mínimo +
Atenhea real + ledger local + recibos firmados. Sin red externa, sin cadena.

## Piezas

| Fichero | Qué hace |
|---|---|
| `router.py` | Router + ledger SQLite (`nexus_h0.db`): cola de trabajos, registro de nodos, verificación de recibos firmados, resumen de liquidación |
| `worker_agent.py` | Sidecar del nodo: pide trabajos al Router y los ejecuta contra el **motor** de Atenhea (`:11436`), nunca contra el proxy de agentes (`:11434`) → los trabajos H0 no tocan la memoria CHL ni herramientas locales |
| `nexus_common.py` | Recibos canónicos Ed25519, precios de referencia y reparto (spec §8.1/§8.4) |
| `dogfood_client.py` | Envía el lote, espera y escribe `h0_report.json` con la puerta H0 evaluada |
| `gen_jobs.py` | Genera `jobs.jsonl`: 100 trabajos tipo fábrica de novelas + 1 sonda con `tools` que debe ser **rechazada** |
| `mock_atenea.py` | Motor falso determinista para probar todo sin el Mac |
| `test_h0.py` | Test E2E completo contra el mock (lote, firmas, manipulación de recibo, sonda) |
| `run_h0_mac.sh` | Arranque completo en el Mac de David en un solo comando |

Desviaciones H0 respecto a la spec (declaradas): el token de despacho por
trabajo es HMAC con secreto local en lugar de JWT (mismas propiedades en
local; JWT llega en H1), y el precio se contabiliza en micro-USD al precio de
referencia de la spec §8.4, sin token todavía (eso es H1, testnet).

## En el Mac (un comando)

```sh
cd ~/Desktop/nexus-h0 && ./run_h0_mac.sh
```

El script: crea `.venv` (solo instala `cryptography`), arranca Atenhea desde
`~/Desktop/ongram` si no está en marcha, levanta Router y worker, ejecuta los
100 trabajos + la sonda y deja el informe en `h0_report.json`. Al terminar
apaga Router y worker; Atenhea queda encendida. La primera vez la descarga e
instalación de `cryptography` tarda ~1 min; el lote de 100 trabajos es batch
y puede tardar (el informe registra tokens/s reales del E2B).

## Puerta H0 (en `h0_report.json` → `gate`)

- `100_jobs_done`: los 100 trabajos terminan.
- `all_receipts_verified`: todos los recibos Ed25519 verifican en el Router.
- `discrepancy_le_1pct`: conteo del ledger vs conteo del motor ≤ 1 %.
- `tools_probe_rejected`: la sonda con herramientas es rechazada por el worker.

## Probar sin Mac (en cualquier máquina)

```sh
python3 -m venv .venv && .venv/bin/pip install cryptography
.venv/bin/python test_h0.py
```
