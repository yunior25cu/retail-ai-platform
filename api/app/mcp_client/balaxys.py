"""Cliente MCP de Balaxys ERP para el chat interno.

El ERP (Balaxys) llama a ``/api/v1/internal/chat`` con ``X-Balaxys-Mcp-Token``:
un access token MCP de vida corta (5 min) que representa la conexion interna
"Balaxys Chat (interno)" de ese usuario y empresa. Con ese token este modulo
abre una sesion MCP (Streamable HTTP, servidor sin estado) contra
``settings.balaxys_mcp_url`` y expone al orquestador:

    - las tools ERP **que no modifican datos** (lectura, borradores y
      ``preparar_*``) convertidas al formato de tools de Anthropic;
    - ``call()`` para ejecutarlas, con tope de llamadas por mensaje;
    - la tarjeta (``ErpCard``) a mostrar en el drawer, con el
      ``structuredContent`` intacto de la tool.

Reglas de seguridad (ver docs/mcp-client.md):

    - Las tools con ``destructiveHint: true`` (``confirmar_*``, ``emitir_cfe``,
      ``enviar_recordatorio_cobranza``) **nunca** se exponen al modelo: en el chat
      interno confirma el usuario con el boton "Confirmar" de la tarjeta, que el
      ERP ejecuta por su cuenta (``POST api/v1/AiAssistant/acciones``).
    - El token no se loguea ni se guarda: vive solo durante el mensaje.
    - La empresa y el usuario los fija el token; el modelo no puede elegirlos.

Si el ERP no responde, rechaza el token o no hay token, ``open_balaxys_mcp``
entrega ``None`` y el chat sigue solo con el flujo retail.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import structlog
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, InitializeResult, ListToolsResult, TextContent, Tool

from app.config import settings

log = structlog.get_logger(__name__)

# Tools que el ERP muestra como tarjeta (mismo criterio que
# Services/Mcp/McpWidgets.cs del ERP). Ademas cuenta cualquier tool cuyo
# ``_meta.ui.resourceUri`` este definido, para cubrir tools futuras.
CARD_TOOLS: frozenset[str] = frozenset(
    {
        "resumen_negocio", "tesoreria_resumen", "saldos_bancarios", "cuentas_por_cobrar",
        "cuentas_por_pagar", "clientes_con_deuda_vencida", "listar_facturas",
        "listar_facturas_compra", "obtener_factura", "listar_cobros", "obtener_cobro",
        "consultar_stock", "alertas_reposicion",
        "estado_resultados", "analisis_ventas", "novedades", "resumen_cartera", "cae_disponible",
        "estado_cfe", "crear_factura_borrador", "preparar_recordatorio_cobranza",
    }
)

# Tool del ERP con los datos basicos de la empresa (nombre, moneda, fecha de hoy).
CONTEXT_TOOL = "obtener_contexto_empresa"

# Toda tool ``preparar_*`` devuelve ``confirmar_con``: siempre lleva tarjeta.
_PREPARE_PREFIX = "preparar_"

# Maximo de tarjetas por respuesta (las que traen ``confirmar_con`` van primero).
MAX_CARDS = 3

# Campos del structuredContent que el modelo no necesita ver. La tarjeta los
# conserva: el boton Confirmar ejecuta ``confirmar_con`` tal cual.
_TOKEN_FIELD = "token_confirmacion"
_ACTION_FIELD = "confirmar_con"
# Marca de las tarjetas de accion guardadas en el historial (ya no se pueden confirmar).
HISTORY_EXPIRED_FIELD = "confirmacion_vencida"
_ACTION_NOTE = (
    "Accion preparada. La confirma el usuario con el boton Confirmar de la tarjeta; "
    "no la confirmes vos."
)

_UNAVAILABLE_MSG = "No se pudo consultar Balaxys ERP en este momento."

# Subconjunto de tools ERP por rol del chat, SOLO para bajar tokens: cada tool
# cuesta tokens en cada request. Los permisos reales los aplica el ERP con el
# token del usuario; esto no es un control de seguridad. ``direccion`` (y
# cualquier rol no listado) recibe todas. Tools nuevas del ERP: solo direccion,
# hasta que se las agregue a un grupo.
_ERP_GROUPS: dict[str, frozenset[str]] = {
    "base": frozenset(
        {"obtener_contexto_empresa", "listar_empresas", "cambiar_empresa", "novedades", "resumen_negocio"}
    ),
    "ventas": frozenset(
        {
            "analisis_ventas", "listar_facturas", "obtener_factura", "buscar_clientes", "obtener_cliente",
            "crear_cliente", "crear_factura_borrador", "preparar_confirmacion_factura", "cuentas_por_cobrar",
            "antiguedad_cuentas_por_cobrar", "clientes_con_deuda_vencida", "resumen_cartera",
            "preparar_recordatorio_cobranza", "listar_cobros", "obtener_cobro", "crear_cobro_borrador",
            "preparar_confirmacion_cobro",
            "crear_nota_credito_borrador", "preparar_confirmacion_nota_credito", "preparar_emision_cfe",
            "estado_cfe", "cae_disponible",
        }
    ),
    "stock": frozenset(
        {
            "consultar_stock", "alertas_reposicion", "buscar_productos", "crear_ajuste_inventario_borrador",
            "preparar_confirmacion_ajuste", "crear_orden_compra_borrador", "preparar_confirmacion_orden_compra",
            "buscar_proveedores", "listar_facturas_compra",
        }
    ),
}
_ROLE_GROUPS: dict[str, tuple[str, ...]] = {
    "marca": ("base", "ventas", "stock"),
    "tienda": ("base", "ventas", "stock"),
    "sku": ("base", "stock"),
    "produccion": ("base", "stock"),
}


def tools_for_role(tools: list[ErpTool], role: str | None) -> list[ErpTool]:
    """Tools ERP a ofrecer al modelo segun el rol (ver ``_ERP_GROUPS``)."""
    if not settings.balaxys_mcp_role_subset:
        return tools
    groups = _ROLE_GROUPS.get((role or "").lower())
    if groups is None:
        return tools
    allowed = frozenset().union(*(_ERP_GROUPS[g] for g in groups))
    return [t for t in tools if t.name in allowed]

# (headers, timeout) -> cliente httpx. Los tests inyectan uno con transporte ASGI.
HttpClientFactory = Callable[[dict[str, str], httpx.Timeout], httpx.AsyncClient]
_CallFn = Callable[[str, dict[str, Any]], Awaitable[CallToolResult]]


@dataclass(frozen=True)
class ErpTool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    has_card: bool

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass(frozen=True)
class ErpCard:
    """Tarjeta para el drawer: ``data`` es el structuredContent sin tocar."""

    tool: str
    title: str
    data: dict[str, Any]

    @property
    def has_action(self) -> bool:
        return isinstance(self.data.get(_ACTION_FIELD), dict)

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "title": self.title, "data": self.data}

    def to_history_dict(self) -> dict[str, Any]:
        """Version para guardar en el historial de la conversacion.

        Sin ``token_confirmacion`` ni ``confirmar_con``: el token vence a los
        10 minutos y una tarjeta del historial no debe poder confirmar nada.
        Las tarjetas de accion quedan marcadas con ``confirmacion_vencida`` para
        que el cliente muestre que hay que pedir la accion de nuevo.
        """
        data = {k: v for k, v in self.data.items() if k not in (_TOKEN_FIELD, _ACTION_FIELD)}
        if self.has_action:
            data[HISTORY_EXPIRED_FIELD] = True
        return {"tool": self.tool, "title": self.title, "data": data}


@dataclass(frozen=True)
class ErpToolResult:
    payload: Any          # lo que ve el modelo (tool_result)
    is_error: bool
    duration_ms: int
    card: ErpCard | None = None


@dataclass
class BalaxysMcpSession:
    """Sesion MCP abierta durante un mensaje del chat."""

    _call: _CallFn
    tools: list[ErpTool]
    instructions: str | None
    timeout_seconds: float
    max_calls: int
    calls_used: int = 0
    _broken: bool = field(default=False, repr=False)

    def has_tool(self, name: str) -> bool:
        return any(t.name == name for t in self.tools)

    def anthropic_tools(self) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> ErpToolResult:
        t0 = time.perf_counter()
        tool = next((t for t in self.tools if t.name == name), None)
        if tool is None:
            return ErpToolResult({"error": "herramienta_no_disponible", "tool": name}, True, _ms(t0))
        if self.calls_used >= self.max_calls:
            return ErpToolResult(
                {
                    "error": "limite_llamadas_erp",
                    "mensaje": (
                        f"Se alcanzo el maximo de {self.max_calls} consultas a Balaxys ERP en este "
                        "mensaje. Responde con lo que ya tenes."
                    ),
                },
                True,
                _ms(t0),
            )
        if self._broken:
            return ErpToolResult({"error": "erp_no_disponible", "mensaje": _UNAVAILABLE_MSG}, True, _ms(t0))

        self.calls_used += 1
        try:
            result = await self._call(name, arguments or {})
        except Exception as e:  # noqa: BLE001 - red, 401, timeout: el chat no se cae
            self._broken = True
            log.warning("mcp.call_failed", tool=name, reason=type(e).__name__, detail=_short(e))
            return ErpToolResult({"error": "erp_no_disponible", "mensaje": _UNAVAILABLE_MSG}, True, _ms(t0))

        return _to_result(tool, result, _ms(t0))

    async def company_context(self) -> dict[str, Any] | None:
        """Datos basicos de la empresa para el system prompt, sin pasar por el modelo.

        Llama directo a ``obtener_contexto_empresa`` (no cuenta para ``max_calls``)
        para que el modelo no gaste una ronda entera en pedirlos en cada mensaje.
        ``None`` si la tool no esta o falla: el modelo la llama como antes.
        """
        if self._broken or not self.has_tool(CONTEXT_TOOL):
            return None
        t0 = time.perf_counter()
        try:
            result = await self._call(CONTEXT_TOOL, {})
        except Exception as e:  # noqa: BLE001 - igual que call(): el chat no se cae
            self._broken = True
            log.warning("mcp.context_failed", reason=type(e).__name__, detail=_short(e))
            return None
        data = result.structuredContent if isinstance(result.structuredContent, dict) else None
        context = None if result.isError or data is None else _compact_context(data)
        log.info("mcp.context", ms=_ms(t0), ok=context is not None)
        return context


def select_cards(cards: list[ErpCard]) -> list[ErpCard]:
    """Hasta MAX_CARDS tarjetas, primero las que traen accion, en orden de aparicion."""
    ordered = [c for c in cards if c.has_action] + [c for c in cards if not c.has_action]
    return ordered[:MAX_CARDS]


@asynccontextmanager
async def open_balaxys_mcp(
    token: str | None,
    *,
    http_client_factory: HttpClientFactory | None = None,
) -> AsyncIterator[BalaxysMcpSession | None]:
    """Abre la sesion MCP del mensaje o entrega ``None`` (flujo solo retail).

    ``None`` si: no llego token, el conector esta deshabilitado o sin URL, el
    servidor rechaza el token (401/403) o no responde. Los errores del cuerpo
    del ``async with`` (orquestador) se propagan sin cambios.
    """
    url = (settings.balaxys_mcp_url or "").strip()
    if not token or not settings.balaxys_mcp_enabled or not url:
        yield None
        return

    timeout = float(settings.balaxys_mcp_timeout_seconds)
    worker = _McpWorker(url, token, timeout, http_client_factory or _default_http_client)
    t0 = time.perf_counter()
    try:
        init, listed = await worker.start()
        tools = sorted(
            (t for t in (_to_erp_tool(raw) for raw in listed.tools) if t is not None),
            key=lambda t: t.name,  # orden estable: no invalida la cache de prompt
        )
    except Exception as e:  # noqa: BLE001 - 401/403, red, timeout: chat solo retail
        log.warning("mcp.unavailable", reason=type(e).__name__, detail=_short(e))
        await worker.close()
        yield None
        return

    erp = BalaxysMcpSession(
        _call=worker.call,
        tools=tools,
        instructions=(init.instructions or None),
        timeout_seconds=timeout,
        max_calls=max(1, int(settings.balaxys_mcp_max_tool_calls)),
    )
    log.info("mcp.connected", tools=len(tools), ms=_ms(t0))
    try:
        yield erp
    finally:
        await worker.close()


class _McpWorker:
    """Duenio de la conexion MCP en su propia tarea.

    El transporte Streamable HTTP del SDK corre en un task group de anyio: un
    error HTTP (token vencido, 5xx, corte de red) cancela la tarea que abrio la
    sesion. Aislandolo aca, ese fallo termina solo este worker; el orquestador
    recibe un error en la llamada y degrada a "ERP no disponible" en vez de
    cancelarse el mensaje entero.
    """

    def __init__(self, url: str, token: str, timeout: float, factory: HttpClientFactory) -> None:
        self._url = url
        self._token = token
        self._timeout = timeout
        self._factory = factory
        self._queue: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future[CallToolResult]] | None] = (
            asyncio.Queue()
        )
        self._ready: asyncio.Future[tuple[InitializeResult, ListToolsResult]] | None = None
        self._current: asyncio.Future[CallToolResult] | None = None
        self._task: asyncio.Task[None] | None = None
        self._closing = False

    async def start(self) -> tuple[InitializeResult, ListToolsResult]:
        self._ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run(), name="balaxys-mcp")
        return await asyncio.wait_for(asyncio.shield(self._ready), self._timeout)

    async def call(self, name: str, arguments: dict[str, Any]) -> CallToolResult:
        if self._task is None or self._task.done():
            raise ConnectionError("La conexion MCP con Balaxys ERP esta cerrada.")
        fut: asyncio.Future[CallToolResult] = asyncio.get_running_loop().create_future()
        await self._queue.put((name, arguments, fut))
        return await asyncio.wait_for(fut, self._timeout + 5)

    async def close(self) -> None:
        if self._task is None:
            return
        self._closing = True
        if not self._task.done():
            await self._queue.put(None)
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 5)
            except TimeoutError:
                self._task.cancel()
        with contextlib.suppress(BaseException):
            await self._task  # recoge el resultado o la excepcion: sin "never retrieved"

    async def _run(self) -> None:
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with (
                self._factory(headers, httpx.Timeout(self._timeout)) as http,
                streamable_http_client(self._url, http_client=http) as (read, write, _),
                ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self._timeout)) as session,
            ):
                init = await session.initialize()
                listed = await session.list_tools()
                if self._ready is not None and not self._ready.done():
                    self._ready.set_result((init, listed))
                while (item := await self._queue.get()) is not None:
                    name, arguments, fut = item
                    self._current = fut
                    try:
                        result = await session.call_tool(name, arguments)
                        if not fut.done():
                            fut.set_result(result)
                    except Exception as e:  # noqa: BLE001 - lo recibe quien llamo
                        if not fut.done():
                            fut.set_exception(e)
                    finally:
                        self._current = None
        except asyncio.CancelledError:
            self._fail_pending(ConnectionError("La conexion MCP con Balaxys ERP fue cancelada."))
            if self._closing:
                raise  # cancelacion pedida por close(): se respeta
        except BaseException as e:  # noqa: BLE001 - p.ej. ExceptionGroup del transporte
            self._fail_pending(e if isinstance(e, Exception) else ConnectionError(str(e)))
        finally:
            self._fail_pending(ConnectionError("La conexion MCP con Balaxys ERP se cerro."))

    def _fail_pending(self, error: BaseException) -> None:
        if self._ready is not None and not self._ready.done():
            self._ready.set_exception(error)
        if self._current is not None and not self._current.done():
            self._current.set_exception(error)
        while not self._queue.empty():
            item = self._queue.get_nowait()
            if item is not None and not item[2].done():
                item[2].set_exception(error)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_http_client(headers: dict[str, str], timeout: httpx.Timeout) -> httpx.AsyncClient:
    # Redirecciones: las maneja el transporte MCP (solo mismo origen), no httpx.
    return httpx.AsyncClient(headers=headers, timeout=timeout, verify=settings.balaxys_mcp_verify_tls)


def _to_erp_tool(raw: Tool) -> ErpTool | None:
    ann = raw.annotations
    if ann is not None and ann.destructiveHint is True:
        return None  # confirmaciones/emision/envio: solo con el boton de la tarjeta
    meta = raw.meta or {}
    ui = meta.get("ui") if isinstance(meta.get("ui"), dict) else {}
    has_card = (
        raw.name in CARD_TOOLS
        or raw.name.startswith(_PREPARE_PREFIX)  # toda preparar_* trae confirmar_con
        or bool(ui.get("resourceUri"))
        or bool(meta.get("ui/resourceUri"))
    )
    schema = dict(raw.inputSchema or {})
    schema.setdefault("type", "object")
    return ErpTool(
        name=raw.name,
        title=(raw.title or (ann.title if ann else None) or raw.name),
        description=raw.description or "",
        input_schema=schema,
        read_only=bool(ann.readOnlyHint) if ann else False,
        has_card=has_card,
    )


def _to_result(tool: ErpTool, result: CallToolResult, ms: int) -> ErpToolResult:
    structured = result.structuredContent if isinstance(result.structuredContent, dict) else None
    text = "\n".join(c.text for c in result.content if isinstance(c, TextContent)).strip()

    if result.isError:
        mensaje = text or (structured or {}).get("mensaje") or "La herramienta devolvio un error."
        return ErpToolResult({"error": "erp_error", "mensaje": mensaje}, True, ms)

    if structured is None:
        return ErpToolResult({"resultado": text}, False, ms)

    card = None
    if tool.has_card:
        title = structured.get("titulo") if isinstance(structured.get("titulo"), str) else None
        card = ErpCard(tool=tool.name, title=title or tool.title, data=structured)
    return ErpToolResult(_for_model(structured), False, ms, card)


def _compact_context(data: dict[str, Any]) -> dict[str, Any] | None:
    """Lo minimo de ``obtener_contexto_empresa`` que el modelo necesita en cada mensaje.

    Sin correo del usuario, permisos ni lista de tools (el modelo ya tiene las tools).
    """
    empresa = data.get("empresa") if isinstance(data.get("empresa"), dict) else None
    fecha = data.get("fecha_hoy")
    if empresa is None or not isinstance(fecha, str) or not fecha:
        return None
    moneda = empresa.get("moneda_base") if isinstance(empresa.get("moneda_base"), dict) else {}
    return {
        "empresa": empresa.get("nombre"),
        "pais": empresa.get("pais"),
        "moneda_base": moneda.get("codigo"),
        "simbolo_moneda": moneda.get("simbolo"),
        "zona_horaria": empresa.get("zona_horaria"),
        "emite_efactura": empresa.get("emite_efactura"),
        "fecha_hoy": fecha,
    }


def _for_model(data: dict[str, Any]) -> dict[str, Any]:
    """Copia para el modelo sin el token de confirmacion ni la accion ejecutable."""
    out = copy.deepcopy(data)
    out.pop(_TOKEN_FIELD, None)
    if out.pop(_ACTION_FIELD, None) is not None:
        out["requiere_confirmacion"] = _ACTION_NOTE
    return out


def _short(e: BaseException) -> str:
    leaf: BaseException = e
    while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
        leaf = leaf.exceptions[0]
    return f"{type(leaf).__name__}: {str(leaf)[:200]}"


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
