# Balaxys ERP — Patrones de Integración para el Módulo AiAssistant

> **Forense read-only** ejecutado 2026-05-27.  
> Repos analizados: `D:\PymeConta_dev\PymeConta` (backend .NET 8) y  
> `D:\PymeConta_dev\nextera-frontend` (frontend React/TS).  
> **Regla de oro:** ningún archivo fue modificado. Ningún DDL/DML ejecutado.

---

## 1. Estructura general del backend

| Item | Valor |
|---|---|
| SDK / Target | `net8.0` |
| Estructura de proyecto | Un único `.csproj` (`PymeConta.csproj`) — **arquitectura plana**, sin capas separadas |
| Namespaces principales | `PymeConta.Controllers.*`, `PymeConta.Services.*`, `PymeConta.Repositories.*`, `PymeConta.Models.*`, `PymeConta.DTOs.*`, `PymeConta.Utils.*` |
| Entry point | `Program.cs` (~950 líneas) — top-level statements, todo el DI registrado ahí |
| ORM | Entity Framework Core 8 + SQL Server (`Microsoft.EntityFrameworkCore.SqlServer`) |
| Contexto EF | `ApplicationDbContext` (en `PymeConta.Context`) |
| Migraciones EF | `Migrations/` — primera migración `20250528033033_Init`, última visible `v1.0.4+` |
| Swagger | Disponible en `/` (root prefix) vía Swashbuckle |
| GraphQL | Endpoint `/graphql` — consumido por el frontend via Apollo Client |

**Módulos de negocio detectados (carpetas bajo `Controllers/`):**
`Accounting`, `AuxFields`, `Catalog`, `Certificados`, `Comission`, `Crm`, `DocumentImport`, `EFactura`, `Finance`, `Importaciones`, `Integrations`, `Inventory`, `Notificacion`, `OCR`, `Portal`, `Public`, `Reporte`, `Security`

---

## 2. Autenticación JWT (backend)

### 2.1 Flujo de extracción del token

Archivo: [Middlewares/JwtMiddleware.cs](../../PymeConta/Middlewares/JwtMiddleware.cs)

```
Request
  → cookie["jwt"]           ← prioridad 1 (httpOnly)
  → Authorization: Bearer   ← fallback
  → sin token               → request continúa sin usuario (401 en acción protegida)
```

Tras validar el token:
```csharp
var userId = long.Parse(jwtToken.Claims.First(x => x.Type == "IdUsuario").Value);
context.Items["Usuario"] = await usuarioService.GetByIdAsync(userId);
```

El **claim del usuario es `IdUsuario`** (tipo `long`). No se usa `sub` ni `user_id`.

### 2.2 Configuración JWT en appsettings

```json
"Authentication": {
  "Jwt": {
    "Issuer": "https://app.balaxys.com",
    "Audience": "https://app.balaxys.com",
    "Key": "<SECRET — nunca commitear>"
  }
}
```

Sección: `Authentication:Jwt`. Key: `Authentication:Jwt:Key`.

### 2.3 Emisión del token

`AuthController` llama a `_usuarioService.GenerarJwtToken(usuario)` y luego `SetTokenCookies(tokenString, refreshToken)`, que establece cookies httpOnly. Hay refresh token con endpoint `/api/v1/Auth/refresh-token`.

### 2.4 Suscripción de acceso

`SubscriptionAccessMiddleware` (después de `JwtMiddleware`) bloquea con HTTP 403 `SubscriptionRequired` si `accessProfile.RequiresSubscription == true`. Rutas exentas: `/api/v1/Auth/*`, `/api/v1/Access/me`, `/api/v1/Empresa/obtener`, etc.

---

## 3. Tenant isolation — convención `id_empresa`

### 3.1 Clase base de entidades

Archivo: [Models/Common/EntidadBase.cs](../../PymeConta/Models/Common/EntidadBase.cs)

```csharp
public abstract class EntidadBase<T>
{
    [Column("id")]        public long Id { get; set; }
    [Column("id_empresa")] public long? IdEmpresa { get; set; }
    [Column("delete")]    public bool Delete { get; set; } = false;  // soft delete
    [Column("deleted_at")] public DateTime? DeletedAt { get; set; }
    [Column("id_user_deleted")] public long? IdUserDeleted { get; set; }
}
public abstract class EntidadAuditable : EntidadBase<int>
{
    [Column("created_at")]       public DateTime CreatedAt { get; set; }
    [Column("id_user_created")]  public long? IdUserCrated { get; set; }
    [Column("updated_at")]       public DateTime? UpdatedAt { get; set; }
    [Column("id_user_updated")]  public long? IdUserUpdated { get; set; }
}
```

**Todas las entidades de negocio heredan `EntidadBase<T>` → todas tienen `id_empresa` (bigint, nullable).**

Columna de soft-delete: `[delete]` (bool). Columnas de auditoría: `created_at`, `updated_at`, `id_user_created`, `id_user_updated`, `deleted_at`, `id_user_deleted`.

### 3.2 Extracción del tenant en controllers

Patrón estándar en el constructor de cada controller:

```csharp
[Authorize]
[Route("api/v1/[controller]")]
[ApiController]
public class ProductoController : ControllerBase
{
    private readonly long _idEmpresa;
    private readonly long _idUsuario;

    public ProductoController(IHttpContextAccessor httpContext, ...)
    {
        _idEmpresa = (httpContext.HttpContext?.Items["Usuario"] as Usuario)!.IdEmpresa!.Value;
        _idUsuario = (httpContext.HttpContext?.Items["Usuario"] as Usuario)!.Id;
    }

    [HttpGet]
    [Permisos(PermisoEnum.P_ProductoServicio_Select)]
    public async Task<IActionResult> GetAll([FromQuery] ProductoFiltroDto Request)
    {
        Request.IdEmpresa = _idEmpresa;   // ← siempre inyectado del JWT, nunca del request body
        var entities = await _service.GetAllAsync(Request);
        return Ok(entities);
    }
}
```

> **Regla crítica para el AiAssistant:** el `IdEmpresa` del tenant SIEMPRE viene del usuario autenticado (`context.Items["Usuario"].IdEmpresa`). Nunca del request body ni de query params.

---

## 4. Sistema de permisos y capabilities

### 4.1 Atributos de autorización

Archivos: `Attributes/AuthorizeAttribute.cs`, `Attributes/PermisosAttribute.cs`, `Attributes/CapabilitiesAttribute.cs`

| Atributo | Propósito | Retorna |
|---|---|---|
| `[Authorize]` | Verifica que `Items["Usuario"] != null` | 401 si no autenticado |
| `[Permisos("NNNNN")]` | Verifica permiso operacional (código numérico) | 403 si sin permiso |
| `[Capabilities("erp.module")]` | Verifica capability comercial (dot-notation) | 403 si sin capability |

Ejemplo de combinación (patrón típico en controllers de reportes):
```csharp
[Authorize]
[Permisos(PermisoEnum.P_Usuario)]        // al menos usuario
[Capabilities("erp.reports.sales")]     // módulo comercialmente habilitado
public async Task<IActionResult> GetVentas(...) { ... }
```

### 4.2 Flujo de resolución de acceso

Ambos atributos llaman a `IAccessControlService.ResolveAsync(user)` y cachean el resultado en `context.HttpContext.Items["AccessProfile"]`:

```csharp
public sealed class ResolvedAccessProfile
{
    public long EmpresaId { get; init; }
    public string? PackageCode { get; init; }         // "package.erp_plus_efactura"
    public string? PlanCode { get; init; }
    public bool IsTrial { get; init; }
    public bool RequiresSubscription { get; init; }
    public IReadOnlyCollection<string> GrantedPermissions { get; init; }
    public IReadOnlyCollection<string> FrontendPermissions { get; init; }
    public IReadOnlyCollection<string> Capabilities { get; init; }
    public IReadOnlyCollection<string> AddonCodes { get; init; }
    public IReadOnlyDictionary<string, string> Limits { get; init; }

    public bool HasPermission(string permission) => ...
    public bool HasCapability(string capability) => ...
}
```

### 4.3 Permisos operacionales (PermisoEnum)

Archivo: [Utils/Enum/PermisoEnum.cs](../../PymeConta/Utils/Enum/PermisoEnum.cs)

Formato: códigos numéricos como string, esquema `MMFNN` (Módulo + Funcionalidad + Operación).

| Código | Constante | Descripción |
|---|---|---|
| `"0"` | `P_Usuario` | Usuario básico (legacy broad) |
| `"1"` | `P_Administrador` | Admin (legacy broad) |
| `"10010"–"10013"` | `P_Rol_*` | CRUD Roles |
| `"10020"–"10024"` | `P_Usuario_*` | CRUD Usuarios + Reset Password |
| `"10032"–"10033"` | `P_Empresa_*` | Update/Delete Empresa |
| `"20000"–"20003"` | `P_Almacen_*` | CRUD Almacenes |
| `"20060"–"20063"` | `P_Unidad_Medida_*` | CRUD Unidades de medida |
| `"21020"–"21023"` | `P_ProductoServicio_*` | CRUD Productos/Servicios |
| `"21020"` | `P_ProductoServicio_Select` | Listar productos |
| `"21021"` | `P_ProductoServicio_Create` | Crear producto |
| `"22010"–"22013"` | `P_Factura_*` | CRUD Facturas |
| Patrón `"2300*"` | — | Todo el módulo de Clientes |
| Patrón `"2200*"` | — | Todo el módulo de Proveedores |

### 4.4 Capabilities (AccessCapabilityCatalog)

Archivo: [Services/Security/AccessCapabilityCatalog.cs](../../PymeConta/Services/Security/AccessCapabilityCatalog.cs)

Formato: dot-notation, jerárquico. Las capabilities de nivel superior incluyen (campo `Includes`) otras capabilities hijas.

**Paquetes comerciales:**
- `package.erp_only` → incluye `shared.core` + `billing.core` + `erp.core`
- `package.efactura_only` → incluye `shared.core` + `billing.core` + `efactura.core`
- `package.erp_plus_efactura` → incluye los tres core modules

**Capabilities relevantes para un módulo AI (secciones que el AI podría necesitar leer):**

| Capability | Área | Incluye / PermPatterns |
|---|---|---|
| `erp.core` | ERP | Sales, Purchases, Inventory, Accounting, Bank, CRM, Analytics, Reports |
| `erp.sales.core` | ERP | erp.sales.quotes, erp.sales.orders, erp.sales.collections, erp.sales.notes |
| `erp.inventory.core` | ERP | Productos, almacenes, movimientos |
| `erp.accounting.core` | ERP | Contabilidad, asientos, cuentas |
| `erp.reports.operational` | ERP | Reportes de ventas, compras, inventario, impuestos |
| `erp.analytics` | ERP | Dashboard y analítica |
| `efactura.core` | EFactura | Emisión, estados, cancelación, PDF/XML, reportes |
| `shared.company_profile` | Shared | Perfil empresa — base de todo |

---

## 5. Patrón de HttpClient

### 5.1 Clientes tipados

Todos registrados con `AddHttpClient<TInterface, TImplementation>()` en `Program.cs`:

```csharp
builder.Services.AddHttpClient<IAuthService, AuthService>((sp, client) =>
{
    var cfg = sp.GetRequiredService<IConfiguration>();
    client.BaseAddress = new Uri(cfg["MercadoLibre:ApiBase"] ?? "https://api.mercadolibre.com/");
    client.Timeout = TimeSpan.FromSeconds(30);
});
```

### 5.2 Clientes nombrados

Para servicios SOAP de DGI y otros:

```csharp
builder.Services.AddHttpClient("DgiSoap", (sp, client) =>
{
    var cfg = sp.GetRequiredService<IOptions<DgiSettings>>().Value;
    client.BaseAddress = new Uri(cfg.UseTestingEnvironment
        ? cfg.Endpoints.HomologBaseUrl
        : cfg.Endpoints.ProdBaseUrl);
    client.Timeout = TimeSpan.FromSeconds(120);
    client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("text/xml"));
})
.ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler
{
    SslProtocols = SslProtocols.Tls12 | SslProtocols.Tls13,
    AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
});
```

Otros nombres: `"DgiConsultasSoap"`, `"IntercambioSoapOutbound"`, `"openai"`.

### 5.3 Polly (retry / circuit breaker)

Patrón con Polly en `MercadoPagoHttpClient`:

```csharp
builder.Services.AddHttpClient<MercadoPagoHttpClient>((sp, client) => { ... })
.AddPolicyHandler((sp, _) =>
{
    var log = sp.GetRequiredService<ILogger<MercadoPagoHttpClient>>();
    return HttpPolicyExtensions
        .HandleTransientHttpError()
        .WaitAndRetryAsync(
            retryCount: 3,
            sleepDurationProvider: attempt => TimeSpan.FromSeconds(Math.Pow(2, attempt)),
            onRetry: (outcome, delay, attempt, _) =>
                log.LogWarning("MP retry {Attempt}/3 after {Delay}s...", attempt, delay.TotalSeconds, ...));
});
```

Patrón para el AiAssistant: registrar el cliente HTTP de Anthropic igual — typed client + Polly exponential backoff.

---

## 6. SignalR (backend)

### 6.1 Hub

Archivo: [Hubs/NotificationHub.cs](../../PymeConta/Hubs/NotificationHub.cs)

```csharp
public class NotificationHub : Hub
{
    // El cliente llama JoinGroup al conectarse
    public async Task JoinGroup(long IdEmpresa)
        => await Groups.AddToGroupAsync(Context.ConnectionId, IdEmpresa.ToString());

    // Notificar refresh de notificaciones a todos los clientes de una empresa
    public async Task NotifyNotificationsChanged(long IdEmpresa)
        => await Clients.Group(IdEmpresa.ToString()).SendAsync("NotificacionesActualizadas");

    // Notificar cambio de configuración
    public async Task NotifyConfigChange(long IdEmpresa, ConfigDto Data)
        => await Clients.Group(IdEmpresa.ToString()).SendAsync("ConfigChanged", Data);
}
```

### 6.2 Registro y ruta

```csharp
builder.Services.AddSignalR();
// ...
app.MapHub<NotificationHub>("/notificationHub");
```

### 6.3 Eventos actuales

| Evento (server → client) | Payload | Trigger |
|---|---|---|
| `NotificacionesActualizadas` | (ninguno) | Cuando hay nuevas notificaciones para la empresa |
| `ConfigChanged` | `ConfigDto` | Cuando cambia la configuración de la empresa |
| `MpPagoConfirmado` | `{ idGestionCobranza, idCobro }` | Cuando Mercado Pago confirma un pago |

### 6.4 Autenticación en SignalR

El Hub **no requiere JWT token explícito en la URL**. La autenticación funciona a través de la cookie httpOnly `jwt` que se envía automáticamente con `withCredentials: true`. El backend usa el mismo `JwtMiddleware` que valida la cookie en cada request HTTP normal.

Para el AiAssistant: si necesita notificar al usuario cuando una consulta AI termina, agregar un evento `AiAssistantResponseReady` a `NotificationHub` y usar `IHubContext<NotificationHub>` en el servicio de AI.

---

## 7. Configuración (IOptions<T>)

### 7.1 Estructura de appsettings.json

```json
{
  "Logging": { "LogLevel": { ... } },
  "Authentication": {
    "Google": { "ClientId": "..." },
    "Jwt": { "Issuer": "...", "Audience": "...", "Key": "<SECRET>" },
    "ApiKey": "<SECRET>"
  },
  "ConnectionStrings": { "DefaultConnection": "<CONNECTION STRING>" },
  "Azure": {
    "StorePymeConnectionString": "<SECRET>",
    "QueueEmailName": "...",
    "ContainerName": "...",
    "UploadSasTtlMinutes": 15,
    "ContainerUrl": "...",
    "KeyVaultUrl": "..."
  },
  "SendGrid": { "Enabled": false, "ApiKey": "<SECRET>", ... },
  "AzureFormRecognizer": { "Endpoint": "...", "ApiKey": "<SECRET>" },
  "EFactura": { "Providers": { "UY:DGI": { ... } }, "Outbox": { ... }, "Polling": { ... } },
  "MercadoPago": { "ApiBaseUrl": "...", "WebhookWorker": { ... } },
  "ClientPortal": { "Enabled": true, "BaseUrl": "...", ... },
  "AdminPass": "<SECRET>",
  "ResetPasswordUrl": "..."
}
```

Archivos de override: `appsettings.Development.json`, `appsettings.Development.local.json`, `appsettings.dev.json`.  
Secretos en desarrollo: User Secrets (`UserSecretsId: "6f6e3e20-..."`). 

> **Para el AiAssistant:** agregar sección `"Anthropic": { "ApiKey": "<SECRET>", "Model": "claude-sonnet-4-6", "MaxTokens": 8192 }` y correspondiente `IOptions<AnthropicSettings>` class.

### 7.2 Patrón de registro de IOptions

```csharp
builder.Services
    .AddOptions<AzureSettings>()
    .Bind(builder.Configuration.GetSection("Azure"))
    .ValidateDataAnnotations()
    .Validate(s => !string.IsNullOrWhiteSpace(s.StorePymeConnectionString), "Azure:StorePymeConnectionString es requerido.")
    .ValidateOnStart();
```

Patrón estándar: `.AddOptions<T>()` + `.Bind(section)` + `.ValidateDataAnnotations()` + `.ValidateOnStart()`.

---

## 8. Logging (Serilog)

### 8.1 Sinks por entorno

| Entorno | Sink | Nivel mínimo | Notas |
|---|---|---|---|
| `Development` | Console + File `Logs/log-.txt` | Information | Rolling diario, 10MB/archivo, retener 90 días |
| `dev` | AzureBlobStorage container `logsdev` | Error | Archivo `log-YYYY-MM-DD.txt` |
| `production` | AzureBlobStorage container `logs` | Error | Archivo `log-YYYY-MM-DD.txt` |

### 8.2 Configuración en Program.cs

```csharp
Log.Logger = new LoggerConfiguration()
    .WriteTo.Console()
    .WriteTo.File("Logs/log-.txt", rollingInterval: RollingInterval.Day, ...)
    .MinimumLevel.Information()
    .MinimumLevel.Override("Microsoft", LogEventLevel.Warning)
    .MinimumLevel.Override("Microsoft.EntityFrameworkCore", LogEventLevel.Warning)
    .CreateLogger();
builder.Host.UseSerilog();
```

### 8.3 Uso en servicios

```csharp
public class MiService
{
    private readonly ILogger<MiService> _logger;
    public MiService(ILogger<MiService> logger) { _logger = logger; }

    public void MiMetodo()
    {
        _logger.LogWarning("MP retry {Attempt}/3 after {Delay}s. Status={Status}", attempt, delay, status);
        _logger.LogInformation("Backend iniciado. Escuchando en: {Urls}", urls);
    }
}
```

Enriquecedores no explícitos detectados (solo `MinimumLevel.Override`). No se usa `FromLogContext` ni `WithMachineName` en la config base.

---

## 9. Background workers

### 9.1 Lista de HostedService registrados

| Worker | Propósito |
|---|---|
| `OutboxWorkerService` | Procesa `integration_outbox` → emite CFE electrónicos |
| `CaeHealthWorkerService` | Monitorea salud CAE + envía notificaciones |
| `FinancialControlNotificationWorkerService` | Notificaciones financieras/contables proactivas |
| `CfeContingenciaWorkerService` | Contingencia fiscal e-Factura |
| `CfcRegularizationPollerWorkerService` | Polling regularización CFE |
| `DailyReportWorkerService` | Envío diario de reportes fiscales |
| `CfePublicationWorkerService` | Publicación de CFE al DGI |
| `CfeStatusPollerWorker` | Polling de estado CFE |
| `CfePdfTemplateBootstrapperHostedService` | Bootstrap de templates PDF |
| `MobileOcrWorkerService` | Ingesta OCR mobile |
| `MercadoPagoWebhookWorkerService` | Procesa webhooks de Mercado Pago |

En modo E2E todos los workers son removidos (`RemoveHostedService<T>(services)`).

### 9.2 Patrón de worker con HTTP client

```csharp
// Ejemplo: MercadoPagoWebhookWorkerService
public class MercadoPagoWebhookWorkerService : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            await ProcessPendingWebhooksAsync(stoppingToken);
            await Task.Delay(TimeSpan.FromSeconds(_options.PollIntervalSeconds), stoppingToken);
        }
    }
}
```

Config de scheduler: `MercadoPago:WebhookWorker:PollIntervalSeconds = 5`, `BatchSize = 10`, `MaxRetries = 5`.

---

## 10. Tests del backend

**Hallazgo:** El proyecto `PymeConta.Tests/` existe como directorio pero **no contiene archivos .cs** (solo archivos auto-generados en `obj/`). Los tests activos están en `PymeConta.ExternalDgiE2ETests/` (también sin archivos fuente encontrados — posiblemente en gitignore o pendientes).

La cobertura de testing en el backend es muy limitada. No hay tests unitarios ni de integración activos en el repo.

---

## 11. Autenticación frontend (React/TS)

### 11.1 Almacenamiento del token

El JWT se almacena como **cookie httpOnly** (NO localStorage ni sessionStorage). El cliente axios siempre envía `withCredentials: true`.

```typescript
// src/core/apirest/apirest.ts
const axiosClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true, // no quitar NUNCA — el sistema usa cookies httpOnly
});
```

### 11.2 Interceptor 401 — refresh automático con queue

```typescript
axiosClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (!is401 || isExcludedPath) return Promise.reject(error);

    if (isRefreshing) {
      await waitForRefresh();           // encola la request
      return axiosClient(originalRequest);
    }

    originalRequest._retry = true;
    isRefreshing = true;
    try {
      await store.dispatch(refreshAccessToken());
      notifySubscribers();             // desencola
      return axiosClient(originalRequest);
    } catch {
      store.dispatch(clearAuth());     // logout
      return Promise.reject(refreshErr);
    }
  }
);
```

Rutas excluidas del retry: `/api/v1/Auth/login`, `/api/v1/Auth/refresh-token`, `/api/v1/Auth/login-google`.

### 11.3 Estado de autenticación (Redux)

Archivo: [src/auth/redux/authSlice.ts](../../nextera-frontend/src/auth/redux/authSlice.ts)

```typescript
interface AuthState {
  isAuthenticated: boolean;
  user: LoginUserType | null;   // incluye empresaId, usuarioId, permisos comerciales, etc.
  permisos: string[];           // capabilities con prefijo "cap:" — ej. "cap:efactura.core"
  loading: boolean;
  error: string | null;
  initialized: boolean;
}
```

`redux-persist` persiste solo `whitelist: ["auth"]` a `localStorage` (para mantener sesión al recargar).

### 11.4 LoginUserType — campos clave

```typescript
interface LoginUserType {
  empresaId: number;        // ← tenant ID
  usuarioId: number;
  usuarioNombre: string;
  empresaNombre: string;
  access?: AccessProfileDto | null;
  permisos: string[];       // capabilities frontend
  // Configuración EF/fiscal
  anno: number | null;      // período contable activo
  mes: number | null;
  esEmisorElectronico: boolean;
  esExonerado: boolean;
  // Moneda base
  moneda: { id, codigo, simbolo, decimales, codigoPais, tasaPromedio };
  codigoPais: string;       // "UY", "USA", etc.
  // ...más campos de config contable
}
```

### 11.5 Inyección del empresaId en cada request

Archivo: [src/services/customBaseQuery.ts](../../nextera-frontend/src/services/customBaseQuery.ts)

```typescript
const axiosBaseQuery = (): BaseQueryFn<...> =>
  async ({ url, method, data, params, responseType }, api) => {
    const state = api.getState() as RootState;
    const empresaId = state.auth?.user?.empresaId;

    const headers: Record<string, string> = {};
    if (empresaId) headers["empresaId"] = empresaId.toString();
    // ...
  };
```

**Cada request RTK Query envía el header `empresaId` con el tenant ID del usuario logueado.**

### 11.6 useAuth hook

Archivo: [src/auth/hooks/useAuth.ts](../../nextera-frontend/src/auth/hooks/useAuth.ts)

Retorna el estado de auth + checks computados:
- `canAccessElectronicOnboarding` → `permisos.includes("cap:efactura.onboarding")`
- `canManageElectronicCertificate` → `permisos.includes("cap:efactura.fiscal_config")`
- `requiresSubscription` → `user.access.requiresSubscription`
- `existPeriod` → `!user.mes`
- `certificateDaysLeft` — días hasta vencimiento del certificado PFX

---

## 12. RTK Query

### 12.1 Instancia central de la API

Archivo: [src/services/api.ts](../../nextera-frontend/src/services/api.ts)

```typescript
export const api = createApi({
  reducerPath: "api",
  baseQuery: axiosBaseQuery(),
  tagTypes: [
    "Products", "Client", "Supplier", "Sale", "Reception",
    "Payments", "Collections", "BankAccount", "Voucher",
    "CfeIssued", "CfeLogs", "Cae", "ElectronicOnboarding",
    "Notifications", "Plans", "AccessManagement",
    "Dashboard", "MpConfig", "MpPagoLink",
    // ... 50+ tag types totales
  ],
  endpoints: () => ({}),  // vacío — cada módulo inyecta sus endpoints
  refetchOnMountOrArgChange: true,
});
```

### 12.2 Patrón de módulo API (injectEndpoints)

Cada módulo hace `api.injectEndpoints(...)`:

```typescript
// src/services/InventoryApi.ts
export const inventoryApi = api.injectEndpoints({
  endpoints: (builder) => ({
    getAllProducts: builder.query<
      { items: ProductType[]; totalRecords: number },
      { page: number; pageSize: number; query?: string; activo?: boolean; ... }
    >({
      query: ({ page, pageSize, query, activo, ... }) => ({
        url: `/api/v1/Producto?page=${page}&pageSize=${pageSize}...`,
        method: "get",
      }),
      providesTags: [{ type: "Products", id: "LIST" }],
    }),

    createProduct: builder.mutation<ProductType, CreateProductType>({
      query: (data) => ({ url: "/api/v1/Producto", method: "post", data }),
      invalidatesTags: [{ type: "Products", id: "LIST" }],
    }),
  }),
});

export const { useGetAllProductsQuery, useCreateProductMutation } = inventoryApi;
```

### 12.3 Manejo de errores (customBaseQuery)

El `axiosBaseQuery` normaliza todos los errores a `BaseQueryError = { status: number, data: ApiError }` donde `ApiError` incluye `title`, `detail`, `errors` (validación), `message` (string legible), `traceId`.

Función de utilidad exportada: `getApiErrorMessage(error)` → string legible para mostrar en UI.

---

## 13. SignalR (frontend)

### 13.1 Configuración de la conexión

Archivo: [src/auth/signalR/signalRService.ts](../../nextera-frontend/src/auth/signalR/signalRService.ts)

```typescript
connection = new HubConnectionBuilder()
  .withUrl(`${import.meta.env.VITE_API_URL_SIGNALR}notificationHub`)
  // Sin withAccessTokenFactory — la cookie jwt se envía automáticamente por withCredentials
  .withAutomaticReconnect()
  .configureLogging(LogLevel.Warning)
  .build();
```

Variable de entorno: `VITE_API_URL_SIGNALR` (separada de `VITE_API_URL` para la API REST).

### 13.2 Suscripción a eventos

```typescript
connection.on("ConfigChanged", (newConfig: ConfigDto) => {
  store.dispatch(updateUserCompanyConfig({ ... }));
});

connection.on("NotificacionesActualizadas", () => {
  store.dispatch(notificationApi.util.invalidateTags([{ type: "Notifications", id: "LIST" }]));
});

connection.on("MpPagoConfirmado", (payload: { idGestionCobranza, idCobro }) => {
  store.dispatch(api.util.invalidateTags([{ type: "CollectionsManagement", id: "BOARD" }]));
  setMessage({ severity: "success", text: `Mercado Pago confirmó un pago...` });
});
```

### 13.3 Ciclo de vida en App.tsx

```typescript
useEffect(() => {
  if (!auth.isAuthenticated || !auth.user) return;
  const connect = async () => {
    await startSignalR();
    await joinGroup(auth.user!.empresaId);  // se une al grupo de su empresa
  };
  void connect();
}, [auth.isAuthenticated, auth.user?.empresaId]);
```

### 13.4 Reconexión

Al reconectar, el handler `connection.onreconnected` vuelve a llamar `joinGroup(empresaId)` para re-suscribirse al grupo de la empresa.

### 13.5 Patrón para AiAssistant

Para notificaciones de streaming o finalización de consultas AI:

```typescript
// Agregar en signalRService.ts:
connection.on("AiAssistantProgress", (payload: { requestId: string, status: string }) => {
  store.dispatch(api.util.invalidateTags([{ type: "AiAssistant", id: payload.requestId }]));
});
```

---

## 14. Redux store

### 14.1 Estructura del store

Archivo: [src/store/index.ts](../../nextera-frontend/src/store/index.ts)

```
store
├── api          → RTK Query cache (todos los endpoints inyectados)
├── auth         → AuthState (user, permisos, isAuthenticated) ← PERSISTED
├── passwordForgot
└── passwordReset
```

`authListenerMiddleware` escucha la acción `clearAuth` y llama `stopSignalR()`.

### 14.2 Hooks tipados

Archivo: [src/store/hooks.ts](../../nextera-frontend/src/store/hooks.ts)

```typescript
export const useAppDispatch = () => useDispatch<AppDispatch>();
export const useAppSelector = <T>(selector: (state: RootState) => T) => useSelector<RootState, T>(selector);
```

### 14.3 Nota: MobX también está presente

`App.tsx` usa `observer` de `mobx-react-lite`. Es un uso residual/específico, no el patrón principal. El patrón principal es Redux + RTK Query.

---

## 15. Formularios

**Ambas librerías están presentes** en `package.json`:
- `formik@^2.4.9` + `yup@^1.7.1` — patrón legacy (pre-existente)
- `react-hook-form@^7.74.0` + `@hookform/resolvers@^5.2.2` — patrón más reciente

El frontend muestra coexistencia de ambos. Para el AiAssistant: si se necesita un formulario (ej. panel de configuración de consultas), usar `react-hook-form` + `yup` (patrón más moderno).

Ejemplo de validación con yup:
```typescript
const schema = yup.object({
  message: yup.string().required("Campo requerido").max(10000),
  tenantId: yup.number().positive().required(),
});
```

---

## 16. Tema y MUI

### 16.1 ThemeProvider

Archivo: [src/core/theme/ThemeWrapper.tsx](../../nextera-frontend/src/core/theme/ThemeWrapper.tsx)

```tsx
export const ThemeWrapper: FC<PropsWithChildren> = ({ children }) => {
  const [mode, setMode] = useState<PaletteMode>("light");
  const theme = useMemo(() => buildTheme(mode), [mode]);

  return (
    <ColorModeContext.Provider value={{ toggleTheme: () => setMode(...) }}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </ColorModeContext.Provider>
  );
};
```

### 16.2 Versiones MUI

| Paquete | Versión |
|---|---|
| `@mui/material` | ^7.3.2 |
| `@mui/icons-material` | ^7.3.2 |
| `@mui/x-data-grid` | ^7.29.1 |
| `@mui/x-date-pickers` | ^7.29.1 |
| `@mui/x-charts` | ^8.3.0 |
| `@mui/x-tree-view` | ^7.29.1 |

### 16.3 Estructura de componentes

Los componentes MUI se usan directamente (sin wrappers propios). La convención de nombres en `src/components/` sigue por dominio: `clients/`, `suppliers/`, `inventory/`, `banks/`, `cfe/`, `accounting/`, etc.

---

## 17. Tests del frontend

### 17.1 Testing unitario / componentes

Framework: **Vitest** (`vitest@^4.1.5`) + `@testing-library/react` + MSW para mocks de API.

Configuración: `"test": "cross-env VITE_API_URL=http://localhost:3000 vitest --reporter=verbose"`.

Tests en: `src/__test__/` y `src/core/routing/__tests__/`.

### 17.2 E2E Playwright

Tests en: `tests/` — archivos `.spec.ts`.

Archivos encontrados:
- `login.smoke.spec.ts`
- `access.smoke.spec.ts` — valida login, menú visible/oculto por capabilities, rutas protegidas
- `access.real.smoke.spec.ts`
- `tenant-management.real.smoke.spec.ts`

Patrón E2E:
```typescript
test(`${scenario.key}: valida login, menú y acceso protegido`, async ({ page }) => {
  await installAccessSmokeMocks(page, scenario);
  await loginThroughUi(page);
  await expect(page).toHaveURL(/\/home$/);
  // verifica menú visible/oculto según capabilities
  await page.goto(scenario.blockedRoute);
  await expect(page).toHaveURL(/\/unauthorized$/);
});
```

---

## 18. Tablas de seguridad / tenancy (DB)

Deducidas de los modelos EF Core y migraciones:

### 18.1 Tabla `empresa`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | bigint PK | ID de la empresa/tenant |
| `rut` | varchar(50) | RUT fiscal |
| `nombre` | varchar(255) | Razón social |
| `id_moneda` | bigint FK | Moneda base |
| `tz` | varchar(250) | Timezone |
| `id_empresa_config` | bigint FK | Config extendida |
| `fecha_registro` | datetime | Alta |
| `estado_empresa` | varchar(100) | Estado |

### 18.2 Tabla `usuario`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | bigint PK | |
| `id_empresa` | bigint FK | Tenant (via EntidadBase) |
| `correo` | varchar(255) | Login |
| `clave` | varchar | Hash BCrypt |
| `idioma` | varchar(5) | "es", "en" |
| `en_uso` | bit | |
| `activo` | bit | |
| `delete` | bit | Soft delete |
| `created_at` | datetime | |

Relaciones N:M: `usuario` ↔ `rol` (tabla de unión), `usuario` → `empleado` (1:1).

### 18.3 Tabla `rol`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | bigint PK | |
| `id_empresa` | bigint FK | Tenant |
| `denominacion` | varchar | Nombre del rol |
| Permisos | via `permission_set` | N:M |

### 18.4 Tabla `permission_set`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | int PK | |
| `id_empresa` | bigint FK | Tenant |
| `codigo` | varchar(100) | Identificador |
| `denominacion` | varchar(255) | |
| `permisos` | text | **CSV de códigos** — ej: `"20000,20001,21020,21021"` |
| `es_activo` | bit | |

Los permisos se deserializan via split por `,` en el modelo. NO es una tabla relacional por permiso.

### 18.5 Tabla `security_group`

Existe (`SecurityGroup.cs`) — agrupa `PermissionSet`s y `Usuario`s. Permite compartir conjuntos de permisos entre usuarios.

---

## 19. Addons y entitlements (DB)

### 19.1 Tabla `addon`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | bigint PK | |
| `codigo` | varchar(100) | Ej: `"ai_assistant"`, `"efactura_uy"` |
| `denominacion` | varchar(255) | Nombre visible |
| `tipo` | enum `AddonTypeEnum` | `Module`, etc. |
| `precio` | decimal(18,2) | |
| `ciclo_facturacion` | int | Días (30 = mensual) |
| `es_activo` | bit | |

### 19.2 Tabla `empresa_addon`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | int PK | |
| `id_empresa` | bigint FK | Tenant |
| `id_addon` | bigint FK | |
| `fecha_inicio` | datetime | |
| `fecha_fin` | datetime? | null = sin vencimiento |
| `es_activo` | bit | |

### 19.3 Tabla `plan_entitlement`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | bigint PK | |
| `id_plan` | bigint FK | |
| `tipo` | enum `AccessEntitlementKindEnum` | `Capability` u otro |
| `code` | varchar(150) | Ej: `"ai_assistant"`, `"erp.core"` |
| `value` | varchar(255) | Valor del límite (si aplica) |
| `enabled` | bit | |

### 19.4 Tabla `empresa_capability_override`

Existe (`EmpresaCapabilityOverride.cs`) — permite sobrescribir capabilities a nivel de empresa individual (ej. habilitar un feature en beta para una empresa específica).

### 19.5 Tabla `usuario_permission_override`

Existe (`UsuarioPermissionOverride.cs`) — sobrescribe permisos a nivel de usuario individual.

---

## 20. Convención de tenant ID — resumen ejecutivo

| Contexto | Convención |
|---|---|
| Columna en DB | `id_empresa` (bigint, NOT NULL en tablas principales) |
| Propiedad C# en models | `IdEmpresa` (tipo `long?`) |
| Claim JWT | `IdUsuario` → lookup DB → `Usuario.IdEmpresa` |
| Header HTTP frontend | `empresaId` (string numérico) en cada request |
| Redux state | `state.auth.user.empresaId` (number) |
| SignalR groups | `IdEmpresa.ToString()` |
| Parámetro de queries EF | `Request.IdEmpresa = _idEmpresa` inyectado en constructor |
| Visibilidad en requests | **NUNCA** en request body — siempre del contexto de autenticación |

---

## 21. Recomendaciones para el módulo AiAssistant

### 21.1 Cómo integrar el controller

```csharp
[Authorize]
[Capabilities("ai.assistant")]          // nueva capability a registrar
[Route("api/v1/[controller]")]
[ApiController]
public class AiAssistantController : ControllerBase
{
    private readonly long _idEmpresa;
    private readonly long _idUsuario;

    public AiAssistantController(IHttpContextAccessor httpContext, IAiAssistantService service)
    {
        _idEmpresa = (httpContext.HttpContext?.Items["Usuario"] as Usuario)!.IdEmpresa!.Value;
        _idUsuario = (httpContext.HttpContext?.Items["Usuario"] as Usuario)!.Id;
        _service = service;
    }

    [HttpPost("chat")]
    [Permisos(PermisoEnum.P_AiAssistant_Use)]  // nuevo permiso a crear
    public async Task<IActionResult> Chat([FromBody] AiChatRequest request)
    {
        // _idEmpresa ya está disponible — no aceptar tenantId del body
        var result = await _service.ChatAsync(_idEmpresa, _idUsuario, request, ct);
        return Ok(result);
    }
}
```

### 21.2 Cómo registrar la nueva capability

En `AccessCapabilityCatalog.cs`, agregar:
```csharp
new("ai.assistant", "AI Assistant", "ai",
    Array.Empty<string>(),
    ["ai.assistant.chat", "ai.assistant.history"],
    ["shared.core", "erp.core"]),
```

### 21.3 Cómo agregar el addon en DB

```sql
INSERT INTO addon (codigo, denominacion, tipo, precio, ciclo_facturacion, es_activo)
VALUES ('ai_assistant', 'AI Assistant - Balaxys Analytics', 1, 0, 30, 1);
```

Luego habilitarlo por empresa via `empresa_addon`.

### 21.4 Cómo integrar el frontend (RTK Query + header empresaId)

```typescript
// src/services/AiAssistantApi.ts
export const aiAssistantApi = api.injectEndpoints({
  endpoints: (builder) => ({
    chat: builder.mutation<AiChatResponse, AiChatRequest>({
      query: (data) => ({ url: "/api/v1/AiAssistant/chat", method: "post", data }),
      // El header empresaId se inyecta automáticamente por axiosBaseQuery
    }),
  }),
});
export const { useChatMutation } = aiAssistantApi;
```

### 21.5 Cómo verificar acceso en el frontend

```typescript
const { permisos } = useAuth();
const canUseAi = permisos.includes("cap:ai.assistant");
```

### 21.6 Cómo notificar con SignalR cuando el AI termina

En el backend: `IHubContext<NotificationHub>` → `Clients.Group(empresaId.ToString()).SendAsync("AiResponseReady", payload)`.

En el frontend: agregar `connection.on("AiResponseReady", ...)` en `signalRService.ts`.

---

## 22. Preguntas para el propietario del ERP

Las siguientes dudas surgieron durante el forense y necesitan respuesta antes de estimar con precisión Phase 6:

1. **Modelo de pricing del AI addon:** ¿Será un addon de pago separado (`empresa_addon`) o estará incluido en algún `plan_entitlement` existente? ¿Se cobra por empresa o por usuario?

2. **Permisos granulares AI:** ¿Querés controlar a nivel de permiso numérico qué acciones puede hacer un usuario en el AI (ej. solo consultas vs. también exportación)? ¿O alcanza con la capability `ai.assistant`?

3. **Acceso a datos históricos ERP:** El AI deberá leer tablas de `dbo.*` (documentos, kardex, etc.) del tenant. ¿Esas tablas ya tienen `id_empresa` como FK, o necesitamos un join adicional? ¿Hay views o SPs ya construidos para las consultas más comunes?

4. **Multi-empresa:** ¿Un usuario puede estar en múltiples empresas (el código tiene `P_Vincular_Empresa`)? En ese caso, el `empresaId` que llega en el header HTTP, ¿siempre es el correcto? ¿O puede cambiar durante la sesión sin re-login?

5. **Rate limiting AI:** ¿Se necesita un rate limit por empresa (ej. X consultas/hora) o por usuario? ¿Dónde almacenamos los contadores — en DB, Redis, o en memoria como hace la `retail-ai-platform` actual?

6. **Historial de conversaciones:** ¿El historial de chats AI debe almacenarse en la misma base SQL Server (`pymeconta`)? ¿O en la DB separada de `retail-ai-platform`? ¿Cuánto tiempo de retención?

7. **Contexto de datos que el AI puede ver:** ¿El AI puede ver TODOS los módulos del ERP del tenant, o solo los que el usuario tiene habilitados (según capabilities)? Esto afecta el diseño de los tools.

8. **SignalR para streaming:** ¿Se necesita streaming de tokens (como ChatGPT) o alcanza respuesta completa al final? El streaming requiere WebSockets o SSE — SignalR puede hacer ambos.

9. **Coexistencia con `retail-ai-platform`:** ¿El AiAssistant de Phase 6 reemplaza a `retail-ai-platform` o coexiste? Si coexiste, ¿comparten base de datos o son independientes?

10. **Entorno de deploy:** ¿El AI backend va como otro endpoint en el mismo `PymeConta` ASP.NET Core, o como microservicio separado? Esto afecta si podemos reutilizar `JwtMiddleware`, `IAccessControlService`, etc. directamente.

---

## 23. Estimado de Phase 6

Basado en el forense, la Phase 6 implica conectar `retail-ai-platform` (FastAPI Python con 15 tools ya construidos) con el ciclo auth/tenant de Balaxys. Las tareas identificadas:

| Tarea | Esfuerzo estimado | Notas |
|---|---|---|
| Controller `AiAssistantController` en .NET 8 | 0.5 día | Patrón conocido — copiar de ProductoController |
| `IAiAssistantService` + HTTP client a FastAPI | 1 día | Typed HttpClient + Polly retry |
| Capability `ai.assistant` en catalog + seeding addon | 0.5 día | Registro en AccessCapabilityCatalog + migración EF |
| Nueva sección `Anthropic:*` en appsettings + IOptions | 0.5 día | |
| Frontend: `AiAssistantApi.ts` + RTK Query | 1 día | injectEndpoints en api singleton |
| Frontend: página/componente de chat | 3-5 días | Depende de la complejidad del UI |
| Frontend: control de acceso por capability | 0.5 día | `permisos.includes("cap:ai.assistant")` |
| SignalR event `AiResponseReady` (si streaming) | 1 día | Solo si se necesita streaming |
| Tests Vitest / Playwright para el módulo AI | 1-2 días | |
| **Total estimado sin UI compleja** | **~6 días** | |
| **Total estimado con UI compleja (chat + historial)** | **~10-14 días** | |

> La mayor incertidumbre es el **item 9** de las preguntas (coexistencia con `retail-ai-platform`). Si el AI corre dentro del mismo proceso .NET (como una capa de llamadas internas), el esfuerzo baja. Si corre como microservicio Python externo, el esfuerzo sube por el manejo de auth cross-service.

---

*Documento generado: 2026-05-27 | Forense ejecutado por Claude Code, read-only.*
