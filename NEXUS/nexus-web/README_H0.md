# UI local de NEXUS H0

Interfaz mínima de chat para el contrato implementado por `nexus/h0/router.py`.
Envía mensajes de texto no streaming a `POST /v1/chat/completions`, lee los
modelos anunciados en `GET /v1/models` y muestra la respuesta Chat Completions.

1. Arranca el Router y al menos un worker siguiendo
   [`nexus/h0/README_H0.md`](../nexus/h0/README_H0.md).
2. En la raíz del repositorio ejecuta:

   ```sh
   python3 NEXUS/nexus-web/h0_local.py
   ```

3. Abre <http://127.0.0.1:18081>.

El servidor de UI escucha solo en loopback y reenvía exclusivamente
`GET /v1/models`, `POST /v1/chat/completions` y consultas `GET /jobs/job_N` al Router HTTP de loopback
(`127.0.0.1:18080` por defecto; se puede ajustar con `NEXUS_H0_ROUTER_URL`).
La URL debe seguir apuntando a loopback. El chat selecciona el primer modelo anunciado y deshabilita
el envío si no hay worker/modelos; limita el historial a 150.000 caracteres y
comprueba el tamaño UTF-8 JSON final contra el límite de 1 MiB del Router. No
implementa autenticación: H0 es una integración local y no debe exponerse a
Internet. Las solicitudes pueden esperar hasta 30 minutos, igual que el límite
del Router; ante HTTP 504 recupera el ID devuelto y consulta el estado hasta
cinco minutos, conservando el texto en el campo si el trabajo sigue pendiente.
El contrato H0 no admite streaming, tools ni contenido multimodal.

Para un arranque autocontenido desde un clon sin modelos Atenhea instalados,
desde `NEXUS/nexus/h0` usa `NEXUS_H0_ENGINE=mock ./run_h0_local.sh`. El modo
predeterminado `real` requiere el directorio de modelo y el bundle NRAM de
Atenhea; el launcher los valida antes de intentar iniciar el motor. El
launcher comprueba Router, worker, UI y modelo anunciado, y cierra los
procesos locales al recibir Ctrl-C. `NEXUS_H0_STARTUP_TIMEOUT` (300 s por
defecto) cambia la espera para cargas lentas; `NEXUS_H0_ROUTER_PORT`,
`NEXUS_H0_UI_PORT` y `NEXUS_H0_MOCK_PORT` permiten mover los puertos locales.
