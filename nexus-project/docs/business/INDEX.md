# Índice · Negocio y finanzas de NEXUS

Fecha: 2026-10-27. Estado: alpha cerrada, testnet, sin token, sin ingresos ni clientes. Todo lo cuantitativo es **proyección con supuestos**; lo no verificado va como `[POR VERIFICAR]`. Nada de esto es asesoría legal ni de inversión.

| Doc | Contenido |
|---|---|
| [01-modelo-de-negocio.md](01-modelo-de-negocio.md) | Lienzo, fuentes de ingresos, qué no se monetiza, análisis del reparto 75/10/5/5/5 del escrow y propuesta |
| [02-precios.md](02-precios.md) | Referencias de precios con fuente, capas de servicio, método de precio, economía del operador (fórmulas y ejemplos) |
| [03-plan-de-ingresos.md](03-plan-de-ingresos.md) | Escenarios a 36 meses con resultados reales del script, unidad económica, qué tiene que ser cierto |
| [04-financiacion.md](04-financiacion.md) | Pre-seed derivada del modelo, uso de fondos, hitos, alternativas no dilutivas, cap table orientativo |
| [05-legal-y-cumplimiento.md](05-legal-y-cumplimiento.md) | Sociedad, licencias de modelos, pagos/KYC, token, RGPD, ToS, PI y decisiones para abogado |
| [06-pitch-y-memo.md](06-pitch-y-memo.md) | Deck de 12 diapositivas (evidencia y huecos) y memo de inversión |
| [07-riesgos.md](07-riesgos.md) | Registro de riesgos: técnicos, mercado, legales y equipo |

Modelo: `../../finance/model.py` (`python3 finance/model.py`; tests `python3 -m unittest finance.test_model` desde `nexus-project/`). Salidas: `../../finance/output/` (`resumen.md`, `monthly_*.csv`, `sensitivity_*.csv`, `unit_economics.csv`, `operator_economics.csv`, `split_comparison.csv`, `quarterly.csv`, `scenarios_summary.csv`).

Hallazgo principal: a precios de mercado la comisión sobre inferencia no sostiene la empresa ni el operador medio; el plan descansa en enclaves/SLA/certificación y en medir el throughput real por nodo. Ningún escenario llega a equilibrio en 36 meses.
