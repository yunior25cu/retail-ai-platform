# Chat interno como cliente MCP de Balaxys ERP

El chat del drawer de Balaxys (AI Assistant) puede usar, además de las tools
retail, las tools ERP del conector MCP de Balaxys: ventas, cobranza, stock,
tesorería, facturas y CFE. Son las mismas que usan Claude y ChatGPT. Este
servicio actúa como **cliente MCP**: no reimplementa lógica ERP. Permisos,
multiempresa, validaciones, confirmaciones y auditoría los resuelve Balaxys.

Especificación funcional (lado Balaxys):
`Documentacion/33- Agente IA MCP/Especificacion-Orquestador-Python-Cliente-MCP.md`.

## Flujo

```
Drawer → API Balaxys ── POST /api/v1/internal/chat + X-Balaxys-Mcp-Token ──▶ este servicio
                                                                             │ Claude (loop de tools)
                                                                             ▼
                                                        API Balaxys  POST /mcp (Streamable HTTP)
                                                        Authorization: Bearer <token>
```

1. `service_auth.get_service_auth_context` lee `X-Balaxys-Mcp-Token`.
   - **Solo** lo lee en la ruta `X-Service-Key` (proxy del ERP).
   - El campo es `repr=False`, así que no aparece en logs.
2. `internal_chat` abre `open_balaxys_mcp(token)` **solo durante ese mensaje**. Hace `initialize` y `tools/list` y
   entrega `None` en cualquiera de estos casos:
   - no hay token;
   - `BALAXYS_MCP_URL` está vacío;
   - Balaxys responde 401 o 403;
   - Balaxys no responde.

   Con `None`, el chat sigue **exactamente como antes**, solo con retail.
3. `run_conversation(erp=...)`:
   - agrega las tools ERP al request (sin pisar tools locales con el mismo nombre);
   - agrega el bloque `prompts/erp.py` al system prompt, con las `instructions` del servidor;
   - rutea esas llamadas a Balaxys en lugar de al registry local.
4. La respuesta suma `cards`: `[{tool, title, data}]`.

## Reglas

- **Tools que modifican datos:** las que tienen `destructiveHint: true` (`confirmar_*`, `emitir_cfe`,
  `enviar_recordatorio_cobranza`) **nunca** llegan al modelo. Se filtran por la anotación, no por nombre.
  - El modelo llama a la `preparar_*` correspondiente.
  - La tarjeta muestra el botón **Confirmar**.
  - El usuario confirma en el drawer y el ERP lo ejecuta (`POST api/v1/AiAssistant/acciones`).
- **Tarjetas:** `data` es el `structuredContent` **sin tocar**. Si se modifica, el botón Confirmar deja de
  funcionar porque `confirmar_con` lleva el token de confirmación.
  - Generan tarjeta: toda `preparar_*`, las de la lista `CARD_TOOLS` y las que traen `_meta.ui.resourceUri`.
  - Máximo 3 por respuesta; primero las que tienen acción.
- **Lo que ve el modelo:** el payload no incluye `token_confirmacion` ni `confirmar_con`; en su lugar recibe
  `requiere_confirmacion`.
- **Sanitizer:** no se aplica a los resultados ERP. El modelo necesita los ids reales para encadenar tools,
  por ejemplo `crear_factura_borrador` → `preparar_confirmacion_factura`, y Balaxys ya aplica los permisos
  del usuario.
- **Empresa y usuario:** los fija el token. El modelo no puede elegirlos (contadores: `cambiar_empresa`).

## Robustez

El transporte Streamable HTTP del SDK corre en un *task group* de anyio. Un error HTTP en medio del mensaje
(token vencido, 5xx, corte) **cancela la tarea que abrió la sesión**. Por eso la conexión vive en una tarea
propia (`_McpWorker`, con cola de pedidos):

- un fallo termina solo el worker;
- la llamada en curso devuelve `erp_no_disponible`;
- la sesión queda marcada rota y no reintenta en loop;
- el loop de Claude sigue y responde con lo que tiene.

Test: `test_caida_del_erp_a_mitad_del_mensaje_no_cancela_al_orquestador`.

## Costo

Con tools ERP el request lleva unas 49 definiciones (≈38 KB de JSON con todos los permisos).

- **Caché de prompt**, solo en requests con tools ERP:
  - un breakpoint en la última tool y otro en el system prompt;
  - `cache_control` top-level para la conversación dentro del loop.

  Las tools van en orden fijo (retail y después ERP ordenadas por nombre) y el bloque del prompt no tiene datos
  variables. Sin ERP, el request no cambia.
- **Subconjunto por rol** (`BALAXYS_MCP_ROLE_SUBSET`). Es solo para costo; los permisos los aplica Balaxys.

  | Rol | Tools ERP |
  |---|---|
  | `direccion` | Todas |
  | `marca`, `tienda` | Base + ventas + stock |
  | `sku`, `produccion` | Base + stock |

  Una tool nueva del ERP llega solo a `direccion` hasta que se la agregue a un grupo en `_ERP_GROUPS`.
- **Tokens:** `tokens_input` informa **tokens equivalentes a tarifa de entrada**:
  `input + 1.25 × cache_write + 0.1 × cache_read`.
  - Así el costo que calcula `audit/persister.py` (`tokens_input × $3/M`) sigue siendo exacto sin cambiar
    el esquema.
  - El detalle crudo queda en `ConversationResult.cache_read_tokens` / `cache_write_tokens` y en el log
    `orchestrator.finished`.
- **Tope:** `BALAXYS_MCP_MAX_TOOL_CALLS` llamadas ERP por mensaje (8 por defecto). Con ERP, el loop admite
  hasta `max(5, ese tope)` iteraciones.

## Configuración

| Variable | Default | Uso |
|---|---|---|
| `BALAXYS_MCP_URL` | vacío | Endpoint `/mcp` de la API Balaxys del mismo ambiente. Vacío deshabilita |
| `BALAXYS_MCP_ENABLED` | `true` | Interruptor general |
| `BALAXYS_MCP_TIMEOUT_SECONDS` | `30` | Timeout por llamada y para abrir la sesión |
| `BALAXYS_MCP_MAX_TOOL_CALLS` | `8` | Tope de llamadas ERP por mensaje |
| `BALAXYS_MCP_ROLE_SUBSET` | `true` | Subconjunto de tools por rol (costo) |
| `BALAXYS_MCP_VERIFY_TLS` | `true` | `false` **solo** contra `https://localhost` con certificado de desarrollo |

Valores de `BALAXYS_MCP_URL` por ambiente:
- dev: `https://pymecontaapidev-dkfsauabatf2bjh2.canadacentral-01.azurewebsites.net/mcp`
- local: `https://localhost:7173/mcp`, con `BALAXYS_MCP_VERIFY_TLS=false` por el certificado de dotnet

## Dependencia

`mcp>=1.9,<2`, el SDK oficial de MCP para Python.

- **Por qué no la 2.x:** reescribe el cliente sobre `httpx2` y cambia la negociación de protocolo. La 1.x usa
  el `httpx` 0.28 del proyecto y está probada contra el servidor de Balaxys.
- **`anthropic` en el `pyproject`:** sigue en `>=0.40`. Una instalación limpia hoy resuelve `anthropic` 2.x,
  que es otra versión mayor. El venv actual usa 0.104.1. Conviene fijar una cota superior en un cambio
  aparte.

## Tests

`api/tests/test_mcp_client/`, sin red, sin Anthropic y sin base de datos:

- **`test_balaxys_mcp.py`:** cliente contra un servidor MCP en proceso (FastMCP sin estado). Cubre:
  - filtro de destructivas y orden estable;
  - token en el encabezado;
  - tarjetas y ocultamiento del token;
  - errores de negocio;
  - tope de llamadas;
  - token rechazado;
  - caída a mitad del mensaje;
  - propagación de errores del cuerpo.
- **`test_orchestrator_erp.py`:** loop con cliente de Claude simulado. Cubre:
  - request idéntico sin ERP;
  - ruteo;
  - errores;
  - choque de nombres;
  - tarjetas;
  - caché;
  - contabilidad de tokens;
  - subconjunto por rol.
- **`test_internal_chat_erp.py`:** endpoint con el encabezado. Cubre token → sesión → `cards`, la ruta sin
  token y que el token no aparezca en `repr`.

Prueba real verificada el 2026-11-10 contra la API local de Balaxys, sin LLM:
- 49 tools ofrecibles con la conexión "Balaxys Chat (interno)";
- ninguna destructiva;
- 27 con tarjeta;
- llamadas reales a `obtener_contexto_empresa`, `clientes_con_deuda_vencida` y `analisis_ventas`;
- un token inválido degrada a `None`.
