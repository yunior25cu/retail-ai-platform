"""
Prophet forecast runner — independiente de Power BI.

Extrae ventas históricas de GestionProlimpio, entrena un modelo Prophet
por SKU y guarda las predicciones en gold.fact_demand_forecast.
Al finalizar recalcula gold.fact_production_plan_weekly.

Uso:
    python scripts/run_prophet_forecast.py --tenant 100
    python scripts/run_prophet_forecast.py --tenant 100 --horizon 90 --version 1.1
"""

from __future__ import annotations

import argparse
import logging
import warnings
from datetime import date

import pandas as pd
import pyodbc
from prophet import Prophet

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

# ── Conexiones ────────────────────────────────────────────────────────────────
MACROSOFT_CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=192.168.20.42;DATABASE=GestionProlimpio;"
    "UID=consulta;PWD=consulta;"
)
GOLD_CONN = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;DATABASE=pymeconta_local;"
    "Trusted_Connection=yes;"
)

# ── Query de ventas históricas (validada en Power BI) ─────────────────────────
# Incluye ventas de Fábrica (documentos base) y transferencias a Av Italia (doc 35)
_QUERY_VENTAS = """
SELECT
    L.Fecha,
    L.CodArt AS CodArticulo,
    (L.CantidadHaber - L.CantidadDebe)
        * CASE C.DebeHaber WHEN 'H' THEN -1 ELSE 1 END AS CantidadVendida,
    'Fabrica' AS Origen
FROM dbo.Lineas L
JOIN dbo.Cabezal C
    ON  L.Documento = C.Documento
    AND L.NroFact   = C.NroFact
    AND L.NroDoc    = C.NroDoc
JOIN dbo.Articulos A ON A.CodArticulo = L.CodArt
JOIN dbo.StockArt  S ON S.CodStock   = A.CodStock
WHERE L.Documento IN ('002','01','0101','02','20','21','03','04','22','23')
  AND L.Fecha >= '2022-01-01'
  AND A.LlevaStock = 1

UNION ALL

SELECT
    li.Fecha,
    li.CodArt AS CodArticulo,
    (li.CantidadDebe - li.CantidadHaber) AS CantidadVendida,
    'Ave Italia' AS Origen
FROM dbo.Lineas li
JOIN dbo.deposito  dp ON li.Deposito    = dp.Deposito
JOIN dbo.Articulos A  ON li.CodArt     = A.CodArticulo
JOIN dbo.StockArt  S  ON A.CodStock    = S.CodStock
WHERE li.Fecha     >= '2022-09-01'
  AND li.Documento  = '35'
  AND dp.Deposito   = 'I'
  AND A.LlevaStock  = 1
"""

_MERGE_SQL = """
MERGE gold.fact_demand_forecast AS t
USING (VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)) AS s(
    tenant_id, sku_code, forecast_date, iso_year_week,
    predicted_units, yhat_lower, yhat_upper,
    model_run_date, horizon_days
)
ON  t.tenant_id      = s.tenant_id
AND t.sku_code       = s.sku_code
AND t.forecast_date  = s.forecast_date
AND t.model_run_date = s.model_run_date
WHEN NOT MATCHED THEN
    INSERT (
        tenant_id, sku_code, forecast_date, iso_year_week,
        predicted_units, yhat_lower, yhat_upper,
        model_run_date, horizon_days, model_version
    )
    VALUES (
        s.tenant_id, s.sku_code, s.forecast_date,
        (SELECT iso_year_week FROM gold.dim_date WHERE date = s.forecast_date),
        s.predicted_units, s.yhat_lower, s.yhat_upper,
        s.model_run_date, s.horizon_days, '{model_version}'
    );
"""


def _fetch_sales(conn_str: str) -> pd.DataFrame:
    log.info("Conectando a GestionProlimpio…")
    conn = pyodbc.connect(conn_str)
    df = pd.read_sql(_QUERY_VENTAS, conn)
    conn.close()
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    df["CodArticulo"] = df["CodArticulo"].str.strip()
    return df[df["CantidadVendida"] > 0].copy()


def _train_product(
    datos: pd.DataFrame,
    producto: str,
    horizon_days: int,
    today: date,
) -> list[dict]:
    d = datos[datos["CodArticulo"] == producto].copy()
    rango = pd.date_range(d["Fecha"].min(), d["Fecha"].max())
    ventas = (
        d.groupby("Fecha")["CantidadVendida"]
        .sum()
        .reindex(rango, fill_value=0)
        .reset_index()
        .rename(columns={"index": "ds", "CantidadVendida": "y"})
    )

    if len(ventas) < 60:
        log.warning("  %s: solo %d días, omitido", producto, len(ventas))
        return []

    weekends = pd.DataFrame(
        {"holiday": "weekend", "ds": ventas[ventas["ds"].dt.weekday >= 5]["ds"]}
    )
    modelo = Prophet(holidays=weekends, weekly_seasonality=10)
    modelo.fit(ventas)

    futuro = modelo.make_future_dataframe(periods=horizon_days)
    futuro = futuro[futuro["ds"].dt.weekday < 5]
    pron = modelo.predict(futuro)

    hoy_ts = pd.Timestamp(today)
    pron = pron[pron["ds"] >= hoy_ts].copy()

    rows = []
    for _, row in pron.iterrows():
        rows.append(
            {
                "sku_code": producto,
                "forecast_date": row["ds"].date(),
                "predicted_units": max(0, round(row["yhat"])),
                "yhat_lower": max(0, round(row.get("yhat_lower", 0))),
                "yhat_upper": max(0, round(row.get("yhat_upper", 0))),
            }
        )
    return rows


def _save_forecasts(
    rows: list[dict],
    tenant_id: int,
    model_run_date: date,
    horizon_days: int,
    model_version: str,
    conn_str: str,
) -> None:
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE gold.fact_demand_forecast SET is_active = 0 "
        "WHERE tenant_id = ? AND model_run_date < ?",
        tenant_id,
        model_run_date,
    )

    merge_sql = _MERGE_SQL.format(model_version=model_version)
    batch: list[tuple] = []
    for r in rows:
        batch.append(
            (
                tenant_id,
                r["sku_code"],
                str(r["forecast_date"]),
                str(r["forecast_date"]),  # iso_year_week resolved via subquery
                int(r["predicted_units"]),
                int(r["yhat_lower"]),
                int(r["yhat_upper"]),
                str(model_run_date),
                horizon_days,
            )
        )
        if len(batch) >= 500:
            cursor.executemany(merge_sql, batch)
            batch = []

    if batch:
        cursor.executemany(merge_sql, batch)

    conn.commit()
    conn.close()
    log.info("Guardadas %d predicciones en gold.fact_demand_forecast", len(rows))


def _refresh_plan(tenant_id: int, conn_str: str) -> None:
    conn = pyodbc.connect(conn_str)
    cursor = conn.cursor()
    cursor.execute("EXEC gold.sp_refresh_production_plan_weekly ?", tenant_id)
    conn.commit()
    conn.close()
    log.info("Plan semanal recalculado para tenant %d", tenant_id)


def run_forecast(
    tenant_id: int,
    horizon_days: int = 60,
    model_version: str = "1.0",
) -> None:
    datos = _fetch_sales(MACROSOFT_CONN)
    productos = datos["CodArticulo"].unique()
    log.info("%d productos a procesar", len(productos))

    model_run_date = date.today()
    todas: list[dict] = []

    for producto in productos:
        try:
            rows = _train_product(datos, producto, horizon_days, model_run_date)
            if rows:
                todas.extend(rows)
                log.info("  %s: OK — %d días", producto, len(rows))
        except Exception as exc:
            log.error("  %s: ERROR — %s", producto, exc)

    if not todas:
        log.error("Sin predicciones generadas. Revisar datos fuente.")
        return

    _save_forecasts(todas, tenant_id, model_run_date, horizon_days, model_version, GOLD_CONN)
    _refresh_plan(tenant_id, GOLD_CONN)
    log.info("Forecast completo: %d filas para tenant %d", len(todas), tenant_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Corre Prophet y guarda predicciones en gold.fact_demand_forecast"
    )
    parser.add_argument("--tenant",  type=int, required=True, help="tenant_id (ej: 100)")
    parser.add_argument("--horizon", type=int, default=60,    help="Días a predecir (default 60)")
    parser.add_argument("--version", type=str, default="1.0", help="Versión del modelo")
    args = parser.parse_args()
    run_forecast(args.tenant, args.horizon, args.version)
