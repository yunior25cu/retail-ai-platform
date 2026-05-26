/* ============================================================
 * 02_dim_date.sql  (originally: block_2)
 * Purpose : calendar dimension with ISO week ('YYYY-Www') at day grain.
 * Depends : 01_schema_and_logging.sql
 * Frequency: once on deploy + whenever the date range needs extension.
 * Notes:
 *   - iso_year_week format CHAR(8): '2026-W21'
 *   - day_of_week is ISO (1=Mon..7=Sun), independent of @@DATEFIRST.
 *   - iso_year computed via the standard trick: shift by (26 - iso_week)
 *     days lands inside the correct ISO year (year containing the Thursday).
 * ============================================================ */

IF OBJECT_ID('gold.dim_date','U') IS NOT NULL DROP TABLE gold.dim_date;
GO
CREATE TABLE gold.dim_date (
    date_id          INT          NOT NULL,                  -- yyyymmdd, sortable
    [date]           DATE         NOT NULL,
    [year]           INT          NOT NULL,
    [quarter]        TINYINT      NOT NULL,
    [month]          TINYINT      NOT NULL,
    iso_week         TINYINT      NOT NULL,
    iso_year         INT          NOT NULL,
    iso_year_week    CHAR(8)      NOT NULL,                  -- '2026-W21'
    day_of_week      TINYINT      NOT NULL,                  -- 1=Mon..7=Sun (ISO)
    is_weekend       BIT          NOT NULL,
    week_start_date  DATE         NOT NULL,                  -- ISO Monday
    week_end_date    DATE         NOT NULL,                  -- ISO Sunday
    season_id        INT          NOT NULL CONSTRAINT df_dim_date_season DEFAULT 0,
    season_month     TINYINT      NULL,                      -- 1..6 (placeholder, set via dim_season_mapping)
    CONSTRAINT pk_dim_date PRIMARY KEY CLUSTERED (date_id),
    CONSTRAINT uq_dim_date_date UNIQUE ([date])
);
CREATE INDEX ix_dim_date_iso_yw    ON gold.dim_date (iso_year_week);
CREATE INDEX ix_dim_date_week_end  ON gold.dim_date (week_end_date);
GO

IF OBJECT_ID('gold.sp_populate_dim_date','P') IS NOT NULL DROP PROCEDURE gold.sp_populate_dim_date;
GO
CREATE PROCEDURE gold.sp_populate_dim_date
    @from_date DATE,
    @to_date   DATE
AS
BEGIN
    SET NOCOUNT ON;

    IF @from_date IS NULL OR @to_date IS NULL OR @from_date > @to_date
    BEGIN
        RAISERROR(N'Invalid date range', 16, 1);
        RETURN;
    END;

    DELETE FROM gold.dim_date WHERE [date] BETWEEN @from_date AND @to_date;

    ;WITH nums AS (
        SELECT 0 AS n
        UNION ALL
        SELECT n+1 FROM nums WHERE n < DATEDIFF(DAY, @from_date, @to_date)
    ),
    fechas AS (
        SELECT DATEADD(DAY, n, @from_date) AS d FROM nums
    ),
    enriched AS (
        SELECT d,
               DATEPART(iso_week, d) AS iso_w,
               ((DATEPART(WEEKDAY, d) + @@DATEFIRST - 2) % 7) + 1 AS dow_iso
        FROM fechas
    )
    INSERT INTO gold.dim_date
        (date_id, [date], [year], [quarter], [month], iso_week, iso_year, iso_year_week,
         day_of_week, is_weekend, week_start_date, week_end_date, season_id, season_month)
    SELECT
        CAST(CONVERT(CHAR(8), d, 112) AS INT),
        d,
        DATEPART(YEAR, d),
        DATEPART(QUARTER, d),
        DATEPART(MONTH, d),
        iso_w,
        YEAR(DATEADD(DAY, 26 - iso_w, d)),
        CONCAT(
            CAST(YEAR(DATEADD(DAY, 26 - iso_w, d)) AS CHAR(4)),
            N'-W',
            RIGHT(N'0' + CAST(iso_w AS NVARCHAR(2)), 2)
        ),
        dow_iso,
        CASE WHEN dow_iso IN (6,7) THEN 1 ELSE 0 END,
        DATEADD(DAY, 1 - dow_iso, d),    -- ISO Monday
        DATEADD(DAY, 7 - dow_iso, d),    -- ISO Sunday
        0,
        NULL
    FROM enriched
    OPTION (MAXRECURSION 0);
END;
GO

-- Initial load 2020 -> 2030 (extend as needed via sp_populate_dim_date)
EXEC gold.sp_populate_dim_date @from_date = '2020-01-01', @to_date = '2030-12-31';
GO
