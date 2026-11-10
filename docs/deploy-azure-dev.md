# Despliegue en Azure: orquestador para Balaxys dev

App Service Linux **`ai-platform`** (grupo `rg-ai-platform`, West US 3). Atiende **solo a Balaxys dev**; prod tendrá su
propio App Service. Base de datos: **`pymeconta_test`** (Azure SQL `pymeconta.database.windows.net`).

## Qué corre

- **Modo "solo ERP"** (`RETAIL_TOOLS_ENABLED=false`).
  - El almacén `gold` no existe en `pymeconta_test`, así que no se ofrecen las tools retail.
  - El chat trabaja con las tools ERP de Balaxys vía MCP (`docs/mcp-client.md`).
  - Sin token MCP (empresa sin el add-on Conector IA), responde sin herramientas.
- **Tablas propias**, esquema `api_audit` en `pymeconta_test`: conversaciones, auditoría, feedback y configuración
  por empresa. Se crean, en este orden, con:
  1. `api/scripts/setup_audit_schema.sql`
  2. `sql/gold/12_feedback.sql`
  3. `sql/gold/13_tenant_config.sql`

## Despliegue

`.github/workflows/main_ai-platform.yml` corre en cada push a `main`:

1. Instala `api/requirements.txt`, que tiene versiones fijas.
2. Compila y corre los tests que no necesitan base ni Anthropic.
3. Empaqueta `api/` sin venv, tests ni `.env`.
4. Despliega con OIDC: secretos `AZUREAPPSERVICE_*` del Deployment Center.

Azure instala las dependencias en el servidor (`SCM_DO_BUILD_DURING_DEPLOYMENT=true`).

Comando de arranque del App Service:

```
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Es un solo proceso, porque el rate limiter está en memoria.

## Configuración del App Service

| Variable | Valor | Quién la carga |
|---|---|---|
| `ENVIRONMENT` | `production` | Claude |
| `RETAIL_TOOLS_ENABLED` | `false` | Claude |
| `SQL_SERVER` | `pymeconta.database.windows.net` | Claude |
| `SQL_DATABASE` | `pymeconta_test` | Claude |
| `SQL_DRIVER` | `{ODBC Driver 18 for SQL Server}` | Claude |
| `SQL_ENCRYPT` | `yes` | Claude |
| `SQL_TRUST_SERVER_CERTIFICATE` | `no` | Claude |
| `PG_TENANTS` | vacío (ningún tenant en PostgreSQL) | Claude |
| `BALAXYS_MCP_URL` | `https://pymecontaapidev-dkfsauabatf2bjh2.canadacentral-01.azurewebsites.net/mcp` | Claude |
| `AUTH_REQUIRE_JWT` | `true` | Claude |
| `SERVICE_MODE` | `true`: solo acepta llamadas del ERP con `X-Service-Key` | Claude |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | Claude |
| `SQL_USER` / `SQL_PASSWORD` | Usuario de base dedicado (abajo) | **Responsable** |
| `ANTHROPIC_API_KEY` | Clave de Anthropic | **Responsable** |
| `SERVICE_KEY` | Secreto compartido con Balaxys dev | **Responsable** |
| `JWT_SECRET` | Aleatorio, 32+ caracteres | **Responsable** |

Usuario de base dedicado, con acceso solo a su esquema. Se ejecuta en `pymeconta_test` con una contraseña propia:

```sql
CREATE USER ai_platform WITH PASSWORD = '<contraseña>';
GRANT SELECT, INSERT, UPDATE, DELETE ON SCHEMA::api_audit TO ai_platform;
```

## Lado Balaxys (App Service `PymeContaApiDev`)

| Variable | Valor |
|---|---|
| `RetailAi__BaseUrl` | `https://ai-platform-b7g5gvb6frbwbugq.westus3-01.azurewebsites.net` |
| `RetailAi__ServiceKey` | El mismo valor que `SERVICE_KEY` del orquestador |

## Límites del plan gratuito (F1)

- No permite "Siempre activo": la primera llamada después de un rato sin uso tarda mientras arranca la app.
- 60 minutos de CPU por día.

Alcanza para probar dev. Para uso continuo conviene el plan B1.
