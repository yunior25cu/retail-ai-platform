# retail-ai-platform — Contrato de Integración con ERPs

**Versión:** 1.0  
**Fecha:** 2026-05-27  
**Estado:** Vigente desde Sub-fase 6.1  

---

## 1. Propósito

Este documento define el contrato público que cualquier ERP debe implementar
para conectarse con retail-ai-platform como fuente de inteligencia artificial
sobre datos de retail.

retail-ai-platform es agnóstico al ERP fuente. No sabe ni le importa si
quien lo llama es Balaxys, SAP B1, Tango, Bind, o una aplicación custom.
Lo único que conoce son los conceptos del dominio retail: tenant, usuario,
rol operativo, y las tablas Gold que alimentan sus herramientas de análisis.

---

## 2. Arquitectura de integración
┌─────────────────────────────────────────────────────────────────┐
│                        CAPA ERP (específica)                    │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Balaxys ERP  │  │   SAP B1     │  │  Tango ERP   │  ...    │
│  │ .NET 8 proxy │  │ Java proxy   │  │ .NET proxy   │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
└─────────┼─────────────────┼─────────────────┼─────────────────┘
│                 │                 │
└─────────────────┴─────────────────┘
│
Contrato público (sección 4)
POST /api/v1/internal/chat
│
┌───────────────────────────▼─────────────────────────────────────┐
│                   retail-ai-platform (agnóstico)                 │
│                                                                  │
│  FastAPI Python  →  15 tools  →  Claude API  →  4 roles IA     │
│  Gold Data Warehouse (dim_, fact_, vw_*)                      │
│  Prompts especializados por rol                                  │
│  Audit log, rate limiting, eval framework                        │
└──────────────────────────────────────────────────────────────────┘
│
┌─────────▼──────────────────────────────────────────────────────┐
│                    CAPA GOLD (agnóstica)                        │
│                                                                 │
│  dim_sku  dim_store  dim_category  dim_date                     │
│  fact_sales_weekly  fact_stock_weekly  fact_transfers           │
│  vw_active_alerts  vw_action_recommendation_priority  ...      │
└─────────┬──────────────────────────────────────────────────────┘
│
┌─────────▼──────────────────────────────────────────────────────┐
│                  CAPA CONECTOR (específica por ERP)             │
│                                                                 │
│  sp_seed_brand_mapping_balaxys.sql                             │
│  sp_seed_sales_plan_balaxys.sql                                │
│  sp_refresh_fact_sales_weekly_balaxys.sql                      │
│  ...                                                           │
│                                                                 │
│  sp_seed_brand_mapping_sapb1.sql      ← futuro                 │
│  sp_refresh_fact_sales_weekly_sapb1.sql  ← futuro              │
└────────────────────────────────────────────────────────────────┘

**Regla de oro:** todo lo que está por encima de la línea del conector
es universal y no cambia entre ERPs. Todo lo que está por debajo es
específico y se reimplementa por ERP.

---

## 3. Responsabilidades de cada parte

### 3.1 El ERP (responsabilidades del integrador)

| Responsabilidad | Descripción |
|---|---|
| **Autenticación de usuarios** | El ERP valida al usuario (JWT, sesión, o lo que use). retail-ai-platform nunca ve credenciales de usuario. |
| **Mapeo de tenant** | El ERP mapea su identificador de empresa/tenant al `tenant_id` del sistema Gold. |
| **Mapeo de roles** | El ERP mapea sus roles/permisos a los 4 roles IA (ver sección 5). |
| **Proxy HTTP** | El ERP implementa un proxy que llama al endpoint interno de retail-ai-platform. |
| **Conector Gold** | El ERP implementa los SPs/scripts que alimentan las tablas Gold desde sus propias tablas. |
| **UI** | El ERP implementa la interfaz de chat en su propio frontend. |

### 3.2 retail-ai-platform (responsabilidades propias)

| Responsabilidad | Descripción |
|---|---|
| **Análisis de datos** | Consulta las tablas Gold y genera insights vía Claude. |
| **Prompts especializados** | Adapta la respuesta al rol del usuario. |
| **Historial conversacional** | Persiste conversaciones en su propia BD (api_audit). |
| **Audit log** | Registra cada request con tokens, costo, duración. |
| **Rate limiting** | Controla consumo por tenant y usuario. |
| **Seguridad interna** | Valida service key, aísla datos por tenant. |

---

## 4. Contrato del endpoint principal

### 4.1 Endpoint
POST /api/v1/internal/chat

Este endpoint es el único punto de integración entre el ERP y
retail-ai-platform. Nunca se expone públicamente — solo es accesible
desde la red interna donde corre el proxy del ERP.

### 4.2 Headers requeridos

| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Service-Key` | string | ✅ | Secreto compartido entre el ERP y retail-ai-platform. Mínimo 32 caracteres. Se configura en ambos sistemas al momento de la integración. |
| `X-Tenant-Id` | integer (string) | ✅ | ID numérico del tenant **en el sistema Gold**. No tiene que coincidir con el ID del ERP — el integrador es responsable del mapeo. |
| `X-User-Role` | string | ✅ | Rol IA del usuario. Valores válidos: `direccion`, `marca`, `tienda`, `sku`. Ver sección 5. |
| `X-User-Id` | integer (string) | ✅ | ID numérico del usuario en el ERP. Solo se usa para audit log — retail-ai-platform no lo valida. |
| `X-Conversation-Id` | UUID (string) | ❌ | ID de conversación existente para continuidad multi-turn. Si no se envía, se crea una nueva conversación. |
| `X-Request-Id` | UUID (string) | ❌ | ID de request para trazabilidad. Si no se envía, se genera automáticamente. |
| `Content-Type` | string | ✅ | `application/json` |

### 4.3 Body del request

```json
{
  "message": "¿Cuáles son las alertas urgentes de esta semana?",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `message` | string | ✅ | Pregunta del usuario. Mínimo 1 carácter, máximo 10.000. |
| `conversation_id` | string (UUID) | ❌ | Alternativa al header X-Conversation-Id. Si ambos están presentes, el header toma prioridad. |

### 4.4 Response exitosa (HTTP 200)

```json
{
  "response": "Esta semana hay 3 alertas críticas...",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "request_id": "7f3a9b2c-1234-5678-abcd-ef0123456789",
  "tools_used": ["get_active_alerts", "get_action_recommendations"],
  "tokens_input": 4821,
  "tokens_output": 634,
  "duration_ms": 12450
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `response` | string | Respuesta en markdown. El ERP es responsable de renderizarla. |
| `conversation_id` | UUID | ID de la conversación. El ERP debe persistirlo para el siguiente turno. |
| `request_id` | UUID | ID del request para trazabilidad en el audit log. |
| `tools_used` | string[] | Herramientas Gold consultadas. Útil para transparencia hacia el usuario. |
| `tokens_input` | integer | Tokens consumidos en el prompt. Para monitoreo de costos. |
| `tokens_output` | integer | Tokens generados en la respuesta. |
| `duration_ms` | integer | Duración total del request en milisegundos. |

### 4.5 Códigos de error

| HTTP | Código interno | Descripción | Acción recomendada |
|---|---|---|---|
| 400 | `MISSING_HEADER` | Falta un header requerido | Verificar headers antes de llamar |
| 401 | `INVALID_SERVICE_KEY` | Service key inválida o ausente | Verificar configuración del secreto compartido |
| 422 | `INVALID_ROLE` | Rol no reconocido | Verificar mapeo de roles (sección 5) |
| 422 | `MESSAGE_TOO_LONG` | Mensaje supera 10.000 caracteres | Truncar en el ERP antes de enviar |
| 429 | `RATE_LIMIT_TENANT` | Límite de requests del tenant superado | Implementar backoff en el proxy |
| 429 | `RATE_LIMIT_USER` | Límite de requests del usuario superado | Notificar al usuario |
| 503 | `SERVICE_UNAVAILABLE` | retail-ai-platform no puede procesar | Mostrar mensaje de no disponibilidad |

Todos los errores retornan:
```json
{
  "error": "INVALID_SERVICE_KEY",
  "message": "El service key proporcionado no es válido.",
  "request_id": "7f3a9b2c-..."
}
```

### 4.6 Endpoint de health check
GET /api/v1/health/ready

Sin headers de autenticación. Retorna:
```json
{
  "status": "ready",
  "mode": "service",
  "tenant_count": 3,
  "version": "0.6.1"
}
```

El ERP debe llamar a este endpoint al startup para verificar
disponibilidad antes de exponer el chat a usuarios.

---

## 5. Mapeo de roles

retail-ai-platform tiene 4 roles que determinan el tipo de respuesta,
las herramientas disponibles y el período de análisis por defecto.

| Rol IA | Período default | Herramientas | Descripción funcional |
|---|---|---|---|
| `direccion` | Mensual | Todas (15 tools) | Visión ejecutiva del negocio. Respuestas concisas orientadas a decisión. |
| `marca` | Semanal | Marca, cobertura, velocidad, transferencias | Análisis de marca en todas las tiendas. |
| `tienda` | Semanal | Dashboard tienda, alertas, recomendaciones | Lista accionable para el encargado de tienda. |
| `sku` | Semanal | Detalle SKU, cobertura, velocidad, comparación | Ficha técnica de decisión sobre producto específico. |

### 5.1 Criterios de mapeo recomendados

El ERP es libre de definir su propio mapeo. Como referencia:

| Perfil típico en el ERP | Rol IA sugerido |
|---|---|
| CEO, Gerente General, Director | `direccion` |
| Gerente de Marca, Brand Manager | `marca` |
| Encargado de Tienda, Jefe de Local | `tienda` |
| Operador, Vendedor, Usuario básico | `sku` |
| Administrador del sistema | `direccion` |

### 5.2 Rol inválido

Si el ERP envía un rol no reconocido, retail-ai-platform no falla —
mapea automáticamente a `sku` (el rol más restrictivo y operativo).
Se recomienda verificar el mapeo antes de lanzar a producción.

---

## 6. Gestión de conversaciones

### 6.1 Flujo multi-turn
Turno 1:
Request:  { message: "...", conversation_id: null }
Response: { ..., conversation_id: "uuid-generado" }
Turno 2:
Request:  { message: "...", conversation_id: "uuid-generado" }
Response: { ..., conversation_id: "uuid-generado" }  ← mismo
Turno N:
Request:  { message: "...", conversation_id: "uuid-generado" }
Response: { ..., conversation_id: "uuid-generado" }

### 6.2 Responsabilidad del ERP

El ERP **debe** persistir el `conversation_id` entre turnos.
retail-ai-platform no tiene mecanismo para asociar requests
al mismo usuario si no recibe el `conversation_id`.

Opciones de persistencia en el ERP:
- localStorage del frontend (con key `ai_conv_{tenantId}_{userId}`)
- Sesión del usuario en el backend del ERP
- BD del ERP (si se quiere historial por usuario)

### 6.3 Aislamiento de conversaciones

retail-ai-platform garantiza que una conversación de `tenant_id=7`
nunca es accesible desde `tenant_id=3`, aunque el `conversation_id`
sea conocido. El aislamiento es responsabilidad de retail-ai-platform,
no del ERP.

### 6.4 Retención de historial

Las conversaciones se retienen indefinidamente en la BD de
retail-ai-platform (tabla `api_audit.conversation_message`).
No hay política de purga automática en v1. Futuras versiones
pueden agregar TTL configurable por tenant.

---

## 7. Implementación del conector Gold

Esta es la parte más específica de cada integración. El conector
es el conjunto de scripts SQL que alimentan las tablas Gold desde
las tablas del ERP.

### 7.1 Tablas Gold que el conector debe alimentar

| Tabla Gold | Descripción | Fuente típica en ERP |
|---|---|---|
| `gold.dim_sku` | Maestro de productos | Tabla de artículos/productos |
| `gold.dim_store` | Maestro de tiendas/almacenes | Tabla de almacenes/sucursales |
| `gold.dim_category` | Categorías de productos | Tabla de categorías/rubros |
| `gold.dim_brand` | Marcas | Campo marca en productos o tabla propia |
| `gold.fact_sales_weekly` | Ventas semanales | Documentos de venta (facturas, tickets) |
| `gold.fact_stock_weekly` | Stock semanal | Kardex / movimientos de inventario |
| `gold.fact_stock_movements` | Movimientos de stock | Tabla de movimientos |
| `gold.fact_transfers` | Transferencias entre tiendas | Remitos internos |
| `gold.fact_sales_plan` | Plan de ventas | Presupuestos / planes (si el ERP los tiene) |

### 7.2 Contratos de datos por tabla

Para cada tabla Gold, el conector debe proveer los campos mínimos:

**gold.dim_sku** (campos requeridos):
sku_id          integer     PK en Gold (puede ser el ID del ERP)
sku_code        varchar     Código único del producto en el ERP
sku_name        varchar     Nombre/descripción
brand_id        integer     FK a dim_brand
category_id     integer     FK a dim_category
tenant_id       integer     ID del tenant en Gold
is_active       boolean     Si está activo para venta

**gold.fact_sales_weekly** (campos requeridos):
tenant_id       integer
iso_year_week   char(8)     Formato 'YYYY-Www' (ej: '2026-W21')
store_id        integer     FK a dim_store
sku_id          integer     FK a dim_sku
units_sold_net  decimal     Unidades vendidas netas (sin devoluciones)
revenue_net     decimal     Importe neto en moneda base
cogs            decimal     Costo de ventas
tickets         integer     Cantidad de transacciones

Ver `sql/gold/` para el esquema completo de todas las tablas.

### 7.3 Patrón de implementación del conector

El conector de Balaxys (referencia) está en `sql/connectors/balaxys/`:
- `sql/connectors/balaxys/03_enrichment_tables.sql` — tablas de enriquecimiento manual
- `sql/connectors/balaxys/04_seeding_procs_emp7.sql` — SPs de seeding del tenant de prueba
- `sql/gold/06_1_fact_sales_weekly.sql` — SP de refresh de ventas semanales (agnóstico)

Para un nuevo ERP, el patrón es:
1. Crear `sql/connectors/<erp_name>/01_mapping.sql`
   — mapeo de IDs del ERP a IDs Gold
2. Crear `sql/connectors/<erp_name>/02_seed_dimensions.sql`
   — seeding de dim_sku, dim_store, dim_category, dim_brand
3. Crear `sql/connectors/<erp_name>/03_refresh_facts.sql`
   — SPs de refresh de facts semanales desde tablas del ERP
4. Registrar en `sp_refresh_all` con el nuevo `@tenant_id`

### 7.4 Estimación de tiempo para un conector nuevo

| Fase | Trabajo | Estimado |
|---|---|---|
| Discovery del schema del ERP | Forense de tablas origen | 1-2 días |
| Mapeo de conceptos | ERP → Gold (campos, tipos, reglas) | 1 día |
| Implementación dimensiones | sp_seed_dim_* | 1-2 días |
| Implementación facts | sp_refresh_fact_* | 2-3 días |
| Validación y cross-checks | Comparar Gold vs ERP directo | 1 día |
| **Total** | | **6-9 días** |

Este es el costo real de agregar un nuevo ERP a la plataforma.
Todo lo demás (Python, tools, prompts, UI) no cambia.

---

## 8. Checklist de integración para un nuevo ERP

### Fase 1 — Infraestructura (antes de codear)
- [ ] Acordar `SERVICE_KEY` (mínimo 32 chars, generado con CSPRNG)
- [ ] Definir `tenant_id` para el cliente en el sistema Gold
- [ ] Confirmar que retail-ai-platform es accesible desde la red del ERP
- [ ] Ejecutar `GET /api/v1/health/ready` y verificar `status: "ready"`

### Fase 2 — Conector Gold
- [ ] Discovery del schema del ERP (tablas de ventas, stock, productos)
- [ ] Implementar sp_seed_dim_sku para el ERP
- [ ] Implementar sp_seed_dim_store para el ERP
- [ ] Implementar sp_refresh_fact_sales_weekly para el ERP
- [ ] Implementar sp_refresh_fact_stock_weekly para el ERP
- [ ] Ejecutar sp_refresh_all para el tenant y verificar resultados
- [ ] Correr sp_run_validations y verificar 0 FAIL

### Fase 3 — Proxy en el ERP
- [ ] Implementar typed HTTP client hacia `/api/v1/internal/chat`
- [ ] Implementar mapeo de roles ERP → roles IA
- [ ] Implementar mapeo de tenant ERP → tenant_id Gold
- [ ] Agregar health check al startup del ERP
- [ ] Implementar manejo de errores (401, 429, 503)
- [ ] Verificar que `tenant_id` nunca viene del request body

### Fase 4 — Frontend en el ERP
- [ ] Implementar UI de chat (drawer, modal, o página)
- [ ] Implementar persistencia de `conversation_id`
- [ ] Implementar control de acceso por rol/permiso
- [ ] Probar flujo multi-turn (mínimo 4 turnos seguidos)
- [ ] Verificar aislamiento cross-tenant (usuario de empresa A no ve empresa B)

### Fase 5 — Go live
- [ ] Seed del addon en BD del ERP (si el ERP tiene sistema de addons)
- [ ] Habilitar para empresa piloto
- [ ] Verificar audit log en retail-ai-platform (`api_audit.ai_audit_log`)
- [ ] Monitorear rate limits primeras 48 horas
- [ ] Grabar demo con datos reales

---

## 9. Rate limits por defecto

| Límite | Valor | Configurable |
|---|---|---|
| Requests por tenant por hora | 100 | Sí, por configuración |
| Requests por usuario por hora | 30 | Sí, por configuración |
| Tokens por tenant por día | 1.000.000 | Sí, por configuración |
| Longitud máxima del mensaje | 10.000 caracteres | No |
| Turnos de memoria conversacional | 3 últimos turnos | No (v1) |

Si un tenant necesita límites superiores, contactar para configuración
personalizada. Los contadores se resetean con ventana deslizante (sliding window).

---

## 10. Versioning y compatibilidad

El contrato de integración sigue semver desde v1.0.

| Tipo de cambio | Política |
|---|---|
| Nuevos campos opcionales en response | Compatible hacia atrás — no rompe integraciones |
| Nuevos headers opcionales | Compatible hacia atrás |
| Nuevos roles IA | Se notifica con 30 días de anticipación |
| Cambios en headers requeridos | Breaking change — versión mayor nueva |
| Cambios en estructura de response | Breaking change — versión mayor nueva |

Breaking changes se anuncian con mínimo 90 días de anticipación
y se mantiene la versión anterior activa por 6 meses.

---

## 11. Integraciones existentes

| ERP | Estado | Conector | Proxy | Fecha |
|---|---|---|---|---|
| Balaxys ERP (v8, .NET 8) | ✅ Producción | `sql/connectors/balaxys/` | `PymeConta/Clients/RetailAiApiClient.cs` | 2026-05 |

---

## 12. Contacto y soporte

Para iniciar una integración o reportar problemas con el contrato:
- Repositorio: https://github.com/yunior25cu/retail-ai-platform
- Issues: https://github.com/yunior25cu/retail-ai-platform/issues
- Documentación técnica: `docs/` en el repositorio

---

*Documento mantenido por el equipo de retail-ai-platform.*  
*Última actualización: 2026-05-27*
