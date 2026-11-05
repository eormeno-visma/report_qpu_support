"""
Report QPU Support
==================
Punto de entrada principal con menú interactivo.

Al ejecutar, solicita mes y año y luego presenta un menú para ejecutar
cada etapa de forma independiente:

  [1] Probar conectividad a las bases de datos
  [2] Obtener listado maestro de empresas
  [3] Exportar logs del período (mes por mes)
  [4] Consolidar logs en un solo CSV (o cargar archivo existente)
  [5] Ejecutar queries del CSV (KPIs)
  [6] Exportar reporte consolidado a CSV
  [7] Ejecutar todo (flujo completo)
  [0] Salir

Uso:
  python main.py
"""

import csv
import io
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from dateutil.relativedelta import relativedelta

from config.queries import COMPANIES_QUERY
from db.connections import MySQLMainConnection, MySQLLogsConnection, MongoConnection
from db.executors import MySQLQueryExecutor, MongoQueryExecutor
from services.connection_tester import ConnectionTester
from services.date_handler import DateHandler
from services.input_handler import ask_params
from services.query_processor import QueryProcessor, QueryRow


CSV_PATH = os.path.join(os.path.dirname(__file__), "input", "query.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")


# ---------------------------------------------------------------------------
# Sistema de logging: escribe a consola Y a archivo simultáneamente
# ---------------------------------------------------------------------------

class _TeeStream(io.TextIOBase):
    """Stream que duplica la escritura a la consola original y a un archivo de log."""

    def __init__(self, original_stream, log_file):
        self._original = original_stream
        self._log_file = log_file

    def write(self, msg):
        if msg:
            self._original.write(msg)
            self._original.flush()
            self._log_file.write(msg)
            self._log_file.flush()
        return len(msg) if msg else 0

    def flush(self):
        self._original.flush()
        self._log_file.flush()

    def isatty(self):
        return self._original.isatty()


def _setup_logging() -> tuple[io.TextIOWrapper | None, str | None]:
    """Configura el logging a archivo.

    Crea un archivo de log con timestamp en la carpeta ``logs/``.
    Redirige stdout y stderr para que todo lo impreso se duplique al archivo.

    Retorna ``(log_file_handle, log_path)`` para poder cerrarlo al final.
    """
    os.makedirs(LOGS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOGS_DIR, f"session_{timestamp}.log")

    log_file = open(log_path, mode="w", encoding="utf-8")

    # Duplicar stdout y stderr al archivo
    sys.stdout = _TeeStream(sys.__stdout__, log_file)
    sys.stderr = _TeeStream(sys.__stderr__, log_file)

    return log_file, log_path


def _teardown_logging(log_file, log_path: str | None) -> None:
    """Restaura stdout/stderr originales y cierra el archivo de log."""
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
    if log_file:
        log_file.close()
    if log_path:
        print(f"\n📝 Log de sesión guardado en: {log_path}")

LOGS_CHUNK_SIZE = 25000
LOGS_MAX_WORKERS = 4  # Ajustar según capacidad del servidor MySQL

# Tamaño de chunk para WHERE IN ({user_ids}) — evita queries con miles de IDs
USER_IDS_CHUNK_SIZE = 500
USER_IDS_MAX_WORKERS = 8

# Tamaño de chunk para lectura del CSV consolidado (filas por chunk)
CSV_READ_CHUNK_SIZE = 50000
CSV_READ_MAX_WORKERS = 4

# Tamaño de chunk para queries C3 — particiona company_ids para paralelizar
QUERY_COMPANY_CHUNK_SIZE = 50   # Empresas por chunk (cada chunk es una sub-query independiente)
QUERY_MAX_WORKERS = 4

# Mensajes conocidos para filtrar login en los logs exportados
_LOGIN_MESSAGES = ("Cambiar de usuario", "Cambiar de plataforma")



# ---------------------------------------------------------------------------
# Exportación de logs en paralelo
# ---------------------------------------------------------------------------

def _build_logs_count_query(fecha_inicio: str, fecha_fin: str, company_ids: list[int]) -> str:
    """Construye el COUNT query de logs con los mismos filtros."""
    ids_str = ", ".join(str(cid) for cid in company_ids)
    return (
        f"SELECT COUNT(*) AS total\n"
        f"FROM logs\n"
        f"WHERE date >= '{fecha_inicio}' AND date <= '{fecha_fin}'\n"
        f"  AND companies_id IN ({ids_str})"
    )


def _build_logs_minmax_query(fecha_inicio: str, fecha_fin: str, company_ids: list[int]) -> str:
    """Construye el query para obtener MIN y MAX id del rango filtrado."""
    ids_str = ", ".join(str(cid) for cid in company_ids)
    return (
        f"SELECT MIN(id) AS min_id, MAX(id) AS max_id\n"
        f"FROM logs\n"
        f"WHERE date >= '{fecha_inicio}' AND date <= '{fecha_fin}'\n"
        f"  AND companies_id IN ({ids_str})"
    )


def _fetch_logs_chunk_by_range(
    fecha_inicio: str, fecha_fin: str, company_ids: list[int],
    id_start: int, id_end: int,
) -> list[dict]:
    """Cada worker abre su propia conexión y descarga un chunk de logs por rango de id.

    Usa WHERE id BETWEEN ... en vez de LIMIT/OFFSET, lo cual es mucho más eficiente
    porque MySQL puede usar el índice primario directamente sin escanear filas previas.
    """
    ids_str = ", ".join(str(cid) for cid in company_ids)
    chunk_query = (
        f"SELECT *\n"
        f"FROM logs\n"
        f"WHERE date >= '{fecha_inicio}' AND date <= '{fecha_fin}'\n"
        f"  AND companies_id IN ({ids_str})\n"
        f"  AND id BETWEEN {id_start} AND {id_end}\n"
        f"ORDER BY id;"
    )
    with MySQLLogsConnection() as conn:
        executor = MySQLQueryExecutor(conn)
        return executor.fetch_all(chunk_query)


def _get_month_ranges(date_handler: DateHandler) -> list[tuple[int, int, str, str]]:
    """Devuelve la lista de (año, mes, fecha_inicio, fecha_fin) para cada mes del rango."""
    import calendar as _cal

    range_start = date.fromisoformat(date_handler.fecha_inicio_3m)
    range_end = date.fromisoformat(date_handler.fecha_fin)
    months: list[tuple[int, int, str, str]] = []
    cursor = range_start
    while cursor <= range_end:
        y, m = cursor.year, cursor.month
        last_day = _cal.monthrange(y, m)[1]
        m_start = date(y, m, 1).strftime("%Y-%m-%d")
        m_end = date(y, m, last_day).strftime("%Y-%m-%d")
        months.append((y, m, m_start, m_end))
        cursor += relativedelta(months=1)
    return months


def _process_single_month(
    m_year: int,
    m_month: int,
    m_start: str,
    m_end: str,
    company_ids: list[int],
    month_idx: int,
    total_months: int,
) -> str | None:
    """Procesa un solo mes: COUNT → chunks en paralelo → exporta CSV.

    Retorna la ruta del archivo generado o None si no hubo datos.
    """
    m_name = DateHandler.MESES[m_month]
    header = f"📅 [{month_idx}/{total_months}] {m_name} {m_year}  ({m_start} → {m_end})"
    print(f"\n   {'-'*55}")
    print(f"   {header}")
    print(f"   {'-'*55}")

    # COUNT del mes
    count_query = _build_logs_count_query(m_start, m_end, company_ids)
    minmax_query = _build_logs_minmax_query(m_start, m_end, company_ids)
    with MySQLLogsConnection() as conn:
        executor = MySQLQueryExecutor(conn)
        count_result = executor.fetch_all(count_query)
        total_expected = count_result[0]["total"] if count_result else 0

    if total_expected == 0:
        print(f"   ⚠️  {m_name} {m_year}: sin registros, se omite.")
        return None

    print(f"   📊 Registros: {total_expected:,}")

    # Obtener rango de IDs para partición eficiente (en vez de LIMIT/OFFSET)
    with MySQLLogsConnection() as conn:
        executor = MySQLQueryExecutor(conn)
        minmax_result = executor.fetch_all(minmax_query)

    min_id = minmax_result[0]["min_id"] if minmax_result else None
    max_id = minmax_result[0]["max_id"] if minmax_result else None

    if min_id is None or max_id is None:
        print(f"   ⚠️  {m_name} {m_year}: no se pudo obtener rango de IDs, se omite.")
        return None

    # Calcular rangos de ID para cada chunk
    # Usamos rangos de tamaño proporcional al LOGS_CHUNK_SIZE
    total_id_range = max_id - min_id + 1
    # Número de chunks basado en el total esperado de registros
    num_chunks = max(1, (total_expected + LOGS_CHUNK_SIZE - 1) // LOGS_CHUNK_SIZE)
    id_range_per_chunk = max(1, total_id_range // num_chunks)

    id_ranges: list[tuple[int, int]] = []
    current_start = min_id
    while current_start <= max_id:
        current_end = min(current_start + id_range_per_chunk - 1, max_id)
        id_ranges.append((current_start, current_end))
        current_start = current_end + 1

    print(f"   📦 Chunks: {len(id_ranges)}  (rango IDs {min_id:,}–{max_id:,}, workers {LOGS_MAX_WORKERS})")
    print(f"      Estrategia: range-based partitioning por id (más eficiente que LIMIT/OFFSET)")

    results_map: dict[int, list[dict]] = {}

    with ThreadPoolExecutor(max_workers=LOGS_MAX_WORKERS) as pool:
        future_to_idx = {
            pool.submit(
                _fetch_logs_chunk_by_range,
                m_start, m_end, company_ids, id_start, id_end,
            ): idx
            for idx, (id_start, id_end) in enumerate(id_ranges)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            chunk_num = idx + 1
            try:
                rows = future.result()
                results_map[idx] = rows
                print(f"      ✅ Chunk {chunk_num}/{len(id_ranges)}: {len(rows):,} registros")
            except Exception as e:
                print(f"      ❌ Chunk {chunk_num}/{len(id_ranges)} falló: {e}")
                results_map[idx] = []

    # Concatenar en orden de rangos
    all_rows: list[dict] = []
    for idx in range(len(id_ranges)):
        all_rows.extend(results_map.get(idx, []))

    if not all_rows:
        print(f"   ⚠️  {m_name} {m_year}: chunks vacíos, se omite.")
        return None

    # Exportar CSV
    year_dir = os.path.join(OUTPUT_DIR, str(m_year))
    os.makedirs(year_dir, exist_ok=True)
    output_file = os.path.join(year_dir, f"logs_{m_name}_{m_year}.csv")

    df = pd.DataFrame(all_rows)
    df.to_csv(output_file, index=False, encoding="utf-8")
    print(f"   📁 {m_name} {m_year}: {len(df):,} registros → {output_file}")
    return output_file


def _export_logs(date_handler: DateHandler, company_ids: list[int]) -> list[str]:
    """
    Ejecuta la extracción de logs **mes por mes** con workers paralelos
    y exporta un CSV por cada mes.

    Cada mes se procesa de forma independiente (COUNT + chunks propios),
    evitando un query único demasiado pesado sobre todo el rango.

    Retorna la lista de rutas de archivos CSV generados.
    """
    nombre_mes = date_handler.nombre_mes
    year = date_handler.year

    # Calcular los meses individuales del rango
    month_ranges = _get_month_ranges(date_handler)

    print(f"\n{'='*60}")
    print(f"📋 EXPORTACIÓN DE LOGS — {nombre_mes} {year}")
    print(f"{'='*60}")
    print(f"   Rango: {month_ranges[0][2]} (3 meses atrás) → {month_ranges[-1][3]} (fin mes actual)")
    print(f"   Meses a procesar: {len(month_ranges)}")
    print(f"   Empresas: {len(company_ids)} IDs")

    generated_files: list[str] = []

    for idx, (m_year, m_month, m_start, m_end) in enumerate(month_ranges, start=1):
        result = _process_single_month(
            m_year, m_month, m_start, m_end,
            company_ids, idx, len(month_ranges),
        )
        if result:
            generated_files.append(result)

    # Resumen final
    print(f"\n{'='*60}")
    print(f"✅ Exportación finalizada — {len(generated_files)}/{len(month_ranges)} archivos generados.")
    for f in generated_files:
        print(f"   📁 {f}")
    print(f"{'='*60}")

    return generated_files


def _consolidate_logs(
    generated_files: list[str], date_handler: DateHandler
) -> tuple[str | None, pd.DataFrame | None]:
    """
    Consolida todos los CSV de logs generados por mes en un solo archivo CSV.

    El archivo resultante se guarda en:
        output/logs_consolidado_<MesInicio>_<AñoInicio>_a_<MesFin>_<AñoFin>.csv

    Retorna una tupla ``(ruta_archivo, DataFrame)`` o ``(None, None)`` si no hay archivos.
    """
    if not generated_files:
        print("\n⚠️  No hay archivos de logs para consolidar.")
        return None, None

    print(f"\n{'='*60}")
    print(f"📦 CONSOLIDANDO LOGS EN UN SOLO CSV")
    print(f"{'='*60}")
    print(f"   Archivos a unir: {len(generated_files)}")

    dfs: list[pd.DataFrame] = []
    for filepath in generated_files:
        df = pd.read_csv(filepath, encoding="utf-8")
        print(f"   📄 {os.path.basename(filepath)}: {len(df):,} registros")
        dfs.append(df)

    consolidated = pd.concat(dfs, ignore_index=True)

    # Nombre del archivo: rango completo basado en fecha_inicio_3m → fecha_fin
    month_ranges = _get_month_ranges(date_handler)
    first_m_name = DateHandler.MESES[month_ranges[0][1]]
    first_m_year = month_ranges[0][0]
    last_m_name = DateHandler.MESES[month_ranges[-1][1]]
    last_m_year = month_ranges[-1][0]

    filename = (
        f"logs_consolidado_{first_m_name}_{first_m_year}"
        f"_a_{last_m_name}_{last_m_year}.csv"
    )
    output_file = os.path.join(OUTPUT_DIR, filename)

    consolidated.to_csv(output_file, index=False, encoding="utf-8")

    print(f"\n✅ Consolidado: {len(consolidated):,} registros totales")
    print(f"📁 Archivo: {output_file}")
    print(f"💾 DataFrame cargado en memoria ({consolidated.memory_usage(deep=True).sum() / 1024 / 1024:.1f} MB)")
    print(f"{'='*60}")

    return output_file, consolidated


# ---------------------------------------------------------------------------
# Lectura de user_ids desde el CSV consolidado (en vez de la BD de logs)
# ---------------------------------------------------------------------------

def _detect_date_range_for_step1(
    row: QueryRow, date_handler: DateHandler
) -> tuple[str, str]:
    """Detecta qué rango de fechas aplica al Step_1 original de una fila.

    Si el Step_1 original contiene '{fecha_inicio_3m}' usa el rango de 3 meses,
    de lo contrario usa el rango de 1 mes.
    """
    if "{fecha_inicio_3m}" in row.step_1:
        return date_handler.fecha_inicio_3m, date_handler.fecha_fin
    return date_handler.fecha_inicio, date_handler.fecha_fin


def _extract_user_ids_from_csv(
    consolidated_csv: str,
    fecha_inicio: str,
    fecha_fin: str,
    messages: tuple[str, ...] = _LOGIN_MESSAGES,
) -> list[int]:
    """
    Lee el CSV consolidado de logs **en chunks paralelos** y filtra por
    *message* y rango de *date* para obtener los user_ids distintos.

    Equivalente al Step_1 SQL:
        SELECT DISTINCT CONCAT(users_id, ',')
        FROM logs
        WHERE message IN (...) AND date BETWEEN '...' AND '...'

    Retorna la lista de users_id como enteros (sin decimales).
    """
    start = pd.Timestamp(fecha_inicio)
    end = pd.Timestamp(fecha_fin) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    messages_set = set(messages)

    def _process_chunk(chunk: pd.DataFrame) -> set[int]:
        """Filtra un chunk y retorna los user_ids únicos como enteros."""
        chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce")
        mask = chunk["message"].isin(messages_set) & (chunk["date"] >= start) & (chunk["date"] <= end)
        ids = chunk.loc[mask, "users_id"].dropna().unique()
        result: set[int] = set()
        for uid in ids:
            val = str(uid).strip()
            if val:
                try:
                    result.add(int(float(val)))
                except (ValueError, TypeError):
                    pass
        return result

    # Leer en chunks y enviarlos al pool de forma streaming
    # (sin acumular todos los chunks en RAM antes de procesar)
    all_ids: set[int] = set()
    total_chunks = 0
    print(f"        📄 CSV: leyendo en chunks de {CSV_READ_CHUNK_SIZE:,} filas → {CSV_READ_MAX_WORKERS} workers (streaming)")

    with ThreadPoolExecutor(max_workers=CSV_READ_MAX_WORKERS) as pool:
        futures: dict = {}
        for chunk in pd.read_csv(
            consolidated_csv,
            usecols=["users_id", "message", "date"],
            dtype={"users_id": str},
            chunksize=CSV_READ_CHUNK_SIZE,
        ):
            total_chunks += 1
            futures[pool.submit(_process_chunk, chunk)] = total_chunks

        print(f"        📄 CSV: {total_chunks} chunks enviados al pool")

        for future in as_completed(futures):
            chunk_ids = future.result()
            all_ids.update(chunk_ids)

    return list(all_ids)


# ---------------------------------------------------------------------------
# Soporte para filas csv-logs: lectura de KPIs sociales desde CSV consolidado
# ---------------------------------------------------------------------------

def _parse_csv_logs_query(sql: str) -> tuple[list[str], list[str]]:
    """Extrae los mensajes y userTypes del SQL original de una fila csv-logs.

    Analiza el SQL original (pensado para MySQL Logs) y extrae:
      - Los valores de ``l.message IN (...)`` o ``l.message = '...'``
      - Los valores de ``userType`` del filtro JSON (``= 'RRHH'`` o ``IN ('Jefe', 'Colaborador')``)

    Retorna ``(messages, user_types)`` como listas de strings.
    """
    messages: list[str] = []
    user_types: list[str] = []

    # Extraer mensajes — buscar IN (...) o = '...' después de l.message
    # Los mensajes en el CSV usan "" como escape de comillas internas
    msg_in = re.search(r"l\.message\s+IN\s*\((.+?)\)\s*AND", sql, re.IGNORECASE | re.DOTALL)
    if msg_in:
        raw = msg_in.group(1)
        # Extraer strings entre comillas simples (los "" internos son comillas literales del CSV)
        messages = re.findall(r"'([^']*(?:''[^']*)*)'", raw)
        # Limpiar escapes: '""' → '"' (viene del CSV con pipe-delimiter)
        messages = [m.replace('""', '"') for m in messages]
    else:
        msg_eq = re.search(r"l\.message\s*=\s*'(.+?)'(?:\s+AND|\s*$)", sql, re.IGNORECASE | re.DOTALL)
        if msg_eq:
            messages = [msg_eq.group(1).replace('""', '"')]

    # Extraer userType — buscar = 'RRHH' o IN ('Jefe', 'Colaborador')
    ut_in = re.search(
        r"userType['\"]?(?:\s*\))+\s*(?:=\s*'([^']+)'|IN\s*\(([^)]+)\))",
        sql,
        re.IGNORECASE,
    )
    if ut_in:
        if ut_in.group(1):
            user_types = [ut_in.group(1)]
        elif ut_in.group(2):
            user_types = re.findall(r"'([^']+)'", ut_in.group(2))

    if not messages:
        raise ValueError(
            "No se pudieron extraer los 'message' del SQL de la fila csv-logs — "
            f"el KPI daría 0 para todas las empresas. SQL: {sql[:300]}"
        )
    if "userType" in sql and not user_types:
        raise ValueError(
            "No se pudieron extraer los valores de 'userType' del SQL de la fila csv-logs — "
            f"el filtro quedaría vacío y el KPI daría 0 para todas las empresas. SQL: {sql[:300]}"
        )

    return messages, user_types


def _load_superadmin_user_ids() -> set[int]:
    try:
        with MySQLMainConnection() as conn:
            rows = MySQLQueryExecutor(conn).fetch_all(
                "SELECT DISTINCT user_id FROM user_roles "
                "WHERE is_hidden_admin = 1 AND user_id IS NOT NULL;"
            )
        ids = {int(r["user_id"]) for r in rows if r["user_id"] is not None}
        print(f"        🚫 Excluyendo {len(ids):,} usuarios con superadministrador asociado")
        return ids
    except Exception as e:
        raise RuntimeError(
            f"No se pudo obtener la lista de usuarios con superadmin asociado: {e}"
        ) from e


def _extract_social_kpi_from_csv(
    consolidated_csv: str,
    fecha_inicio: str,
    fecha_fin: str,
    messages: list[str],
    user_types: list[str],
    companies: list[dict[str, Any]],
    excluded_user_ids: set[int] | None = None,
) -> list[Any]:
    """
    Lee el CSV consolidado de logs en chunks y calcula un KPI social:
    COUNT(DISTINCT userId) agrupado por companies_id.

    Equivalente al SQL original contra MySQL Logs:
        SELECT l.companies_id,
               COUNT(DISTINCT JSON_EXTRACT(l.context, '$.userId')) AS total_usuarios
        FROM logs l
        WHERE l.date BETWEEN ... AND ...
          AND l.message IN (...)
          AND JSON_EXTRACT(l.context, '$.userType') IN (...)
        GROUP BY l.companies_id;

    Los filtros de ``message`` y ``userType`` se extraen del SQL original
    mediante ``_parse_csv_logs_query``.

    Retorna una lista alineada al orden maestro de empresas.
    """
    start = pd.Timestamp(fecha_inicio)
    end = pd.Timestamp(fecha_fin) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    messages_set = set(messages)
    user_types_set = set(user_types)
    excluded_ids = excluded_user_ids or set()

    def _process_chunk(chunk: pd.DataFrame) -> dict[int, set[int]]:
        """Filtra un chunk y retorna {companies_id: set(userIDs)}."""
        chunk["date"] = pd.to_datetime(chunk["date"], errors="coerce")
        mask = (
            chunk["message"].isin(messages_set)
            & (chunk["date"] >= start)
            & (chunk["date"] <= end)
        )
        filtered = chunk.loc[mask, ["companies_id", "context"]].copy()
        if filtered.empty:
            return {}

        # Extraer userId y userType del campo context (JSON string)
        result: dict[int, set[int]] = {}
        for _, row_data in filtered.iterrows():
            ctx = row_data["context"]
            if not isinstance(ctx, str):
                continue
            try:
                ctx_dict = json.loads(ctx)
            except (json.JSONDecodeError, TypeError):
                continue

            u_type = ctx_dict.get("userType", "")
            u_id = ctx_dict.get("userID") or ctx_dict.get("userId")
            cid = row_data["companies_id"]

            if u_type not in user_types_set:
                continue
            if u_id is None or pd.isna(cid):
                continue

            try:
                cid_int = int(cid)
                uid_int = int(u_id)
            except (ValueError, TypeError):
                continue

            # Usuarios con superadministrador asociado no cuentan como uso del cliente
            if excluded_ids and uid_int in excluded_ids:
                continue

            result.setdefault(cid_int, set()).add(uid_int)

        return result

    # Leer en chunks y procesar en paralelo
    merged: dict[int, set[int]] = {}
    total_chunks = 0
    print(f"        📄 CSV: leyendo en chunks de {CSV_READ_CHUNK_SIZE:,} filas → {CSV_READ_MAX_WORKERS} workers")

    with ThreadPoolExecutor(max_workers=CSV_READ_MAX_WORKERS) as pool:
        futures: dict = {}
        for chunk in pd.read_csv(
            consolidated_csv,
            usecols=["companies_id", "message", "date", "context"],
            dtype={"context": str, "companies_id": str},
            chunksize=CSV_READ_CHUNK_SIZE,
        ):
            total_chunks += 1
            futures[pool.submit(_process_chunk, chunk)] = total_chunks

        print(f"        📄 CSV: {total_chunks} chunks enviados al pool")

        for future in as_completed(futures):
            partial = future.result()
            for cid, uid_set in partial.items():
                merged.setdefault(cid, set()).update(uid_set)

    # Alinear al orden maestro: contar usuarios distintos por empresa
    aligned: list[Any] = []
    for comp in companies:
        cid = int(comp["empresa_id"])
        aligned.append(len(merged.get(cid, set())))

    total_with_data = sum(1 for v in aligned if v > 0)
    print(f"        📊 Resultado: {total_with_data}/{len(companies)} empresas con datos")

    return aligned

def _parse_mongo_pipeline(raw_step2: str, user_ids: list[str], fecha_inicio: str, fecha_fin: str) -> list[dict]:
    """
    Parsea el texto del Step_2 (pipeline de agregación MongoDB) desde el CSV,
    reemplaza placeholders de fechas e inyecta los IDs de usuario.

    El CSV almacena el pipeline como JSON con comillas dobles escapadas.
    También maneja la sintaxis abreviada sin comillas como fallback.

    Los userId en MongoDB son enteros (demo.py: df_users['id'].tolist()),
    y las fechas deben convertirse a datetime para que MongoDB las filtre.

    Nota sobre fechas:
      - {fecha_inicio} se usa con $gte (incluye el primer día completo).
      - {fecha_fin} se usa con $lt.  Como fecha_fin es el último día del mes
        (ej. "2026-01-31") y datetime("2026-01-31") = medianoche del 31,
        se suma un día para que $lt cubra todo el día 31.
    """
    text = raw_step2.strip()

    # Extraer solo el array del pipeline si viene envuelto en
    # db.getCollection("...").aggregate([...]); (formato CSV actualizado)
    m = re.search(r'\.aggregate\s*\(\s*(\[.*])\s*\)\s*;?\s*$', text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    # Reemplazar placeholders de fecha
    text = text.replace("{fecha_inicio}", fecha_inicio)

    # Para {fecha_fin}: sumar un día para que $lt incluya todo el último día del mes
    # Ej: fecha_fin="2026-01-31" → fecha_fin_next="2026-02-01"
    #     $lt: "2026-02-01" incluye todo el 31 de enero
    fecha_fin_dt = date.fromisoformat(fecha_fin)
    fecha_fin_next = (fecha_fin_dt + timedelta(days=1)).isoformat()
    text = text.replace("{fecha_fin}", fecha_fin_next)

    # Reemplazar el placeholder de IDs de usuario "<IDs del Query N>"
    # Los IDs deben ser enteros para que MongoDB los compare correctamente
    int_ids = []
    for uid in user_ids:
        try:
            int_ids.append(int(uid))
        except (ValueError, TypeError):
            int_ids.append(uid)
    ids_json_array = json.dumps(int_ids)
    # Usar lambda para evitar que re.sub interprete secuencias de escape
    # (ej. \\u en JSON se convertiría a \u, rompiendo el parsing posterior)
    text = re.sub(
        r'\[\s*"<IDs del Query \d+>"\s*]',
        lambda _: ids_json_array,
        text,
    )

    # Intentar parsear como JSON directamente
    pipeline = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            pipeline = parsed
    except json.JSONDecodeError:
        pass

    # Fallback: convertir sintaxis MongoDB shell (sin comillas) a JSON válido
    # Ej: { $match: { active: true } } → { "$match": { "active": true } }
    if pipeline is None:
        fixed = text
        # Agregar comillas a valores $campo que no están entre comillas
        fixed = re.sub(r'(?<=[{,\s])(\$\w+)(?=\s*[,}\]])', r'"\1"', fixed)
        # Agregar comillas a claves sin comillas (incluidas las que empiezan con $)
        fixed = re.sub(r'(?<=[{,\s])(\$?\w+)\s*:', r'"\1":', fixed)
        try:
            parsed = json.loads(fixed)
            if isinstance(parsed, list):
                pipeline = parsed
        except json.JSONDecodeError:
            pass

    if pipeline is None:
        raise ValueError(f"No se pudo parsear el pipeline MongoDB.\nTexto: {text}")

    # Post-procesamiento: convertir strings de fecha a datetime en createdAt/$gte/$lt
    _convert_dates_in_pipeline(pipeline)

    return pipeline


def _convert_dates_in_pipeline(obj: Any) -> None:
    """Convierte recursivamente strings con formato de fecha ISO a datetime objects
    dentro de las claves $gte, $lt, $lte, $gt de un pipeline MongoDB."""
    if isinstance(obj, list):
        for item in obj:
            _convert_dates_in_pipeline(item)
    elif isinstance(obj, dict):
        for key, val in obj.items():
            if key in ("$gte", "$lt", "$lte", "$gt") and isinstance(val, str):
                try:
                    obj[key] = datetime.fromisoformat(val)
                except ValueError:
                    pass
            else:
                _convert_dates_in_pipeline(val)


def _detect_mongo_collection(step2_text: str) -> str:
    """Detecta la colección de MongoDB a usar según el contenido del pipeline.

    Primero intenta extraer el nombre de la colección del wrapper
    ``db.getCollection("nombre")``.  Si no lo encuentra, aplica heurísticas
    basadas en el contenido del pipeline.

    Basado en demo.py:
      - Pipeline con 'cantidad_grupos'       → colección 'groups'
      - Pipeline con 'like' / '$lookup' posts → colección 'reactions'
      - Default: 'reactions'
    """
    # Intentar extraer de db.getCollection("...")
    m = re.search(r'db\.getCollection\(\s*["\'](\w+)["\']\s*\)', step2_text)
    if m:
        return m.group(1)

    lower = step2_text.lower()
    if "cantidad_grupos" in lower:
        return "groups"
    return "reactions"


def _align_mongo_results_to_companies(
    companies: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[Any]:
    """
    Alinea resultados de un pipeline MongoDB al listado maestro de empresas.

    MongoDB retorna documentos como: { "_id": <companyId>, "cantidad_xxx": N }
    El _id es el companyId (string numérico o int).
    """
    if not results:
        return [0] * len(companies)

    # Indexar por _id (companyId)
    result_map: dict[int, Any] = {}
    for doc in results:
        cid = doc.get("_id")
        if cid is None:
            continue
        # Obtener el valor del KPI (primera key que no sea _id)
        val = 0
        for k, v in doc.items():
            if k != "_id":
                val = v
                break
        try:
            result_map[int(cid)] = val
        except (ValueError, TypeError):
            continue

    # Alinear al orden maestro
    aligned: list[Any] = []
    for comp in companies:
        cid = int(comp["empresa_id"])
        aligned.append(result_map.get(cid, 0))
    return aligned


# ---------------------------------------------------------------------------
# Helpers para detectar la columna company‑id en los resultados de cada query
# ---------------------------------------------------------------------------

# Posibles nombres de columna que representan el ID de la empresa
_COMPANY_ID_KEYS = {"empresa_id", "id", "company_id", "COMPANY_ID", "companies_id"}


def _find_company_id_key(row: dict[str, Any]) -> str | None:
    """Devuelve la primera key del dict que coincida con un nombre de company id."""
    for key in _COMPANY_ID_KEYS:
        if key in row:
            return key
    # Fallback: buscar insensible a mayúsculas
    for key in row:
        if key.lower() in {k.lower() for k in _COMPANY_ID_KEYS}:
            return key
    return None


def _find_value_column(row: dict[str, Any], company_key: str) -> str | None:
    """Encuentra la columna de *valor* del KPI (la que no es id/nombre/hubspot)."""
    skip = {company_key.lower(), "id", "empresa_id", "empresa_nombre",
            "company_id", "hub_id", "hubspot_id", "name", "nombre"}
    for key in row:
        if key.lower() not in skip:
            return key
    return None


# ---------------------------------------------------------------------------
# Ordenar resultados de un query según el listado maestro
# ---------------------------------------------------------------------------

def _align_results_to_companies(
    companies: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[Any]:
    """
    Dado el listado maestro de empresas y los resultados de un KPI query,
    retorna una lista de valores del KPI alineada al orden de *companies*.

    Si una empresa del listado maestro no aparece en los resultados,
    se coloca 0 (o cadena vacía para texto).
    """
    if not results:
        return [0] * len(companies)

    # Detectar la columna de company id en los resultados
    sample = results[0]
    cid_key = _find_company_id_key(sample)
    if cid_key is None:
        # No se puede mapear → devolver 0 para todas
        return [0] * len(companies)

    val_key = _find_value_column(sample, cid_key)
    if val_key is None:
        return [0] * len(companies)

    # Indexar resultados por company_id
    result_map: dict[int, Any] = {}
    for r in results:
        cid = r.get(cid_key)
        if cid is not None:
            result_map[int(cid)] = r.get(val_key, 0)

    # Construir lista alineada al orden maestro
    aligned: list[Any] = []
    for comp in companies:
        cid = int(comp["empresa_id"])
        aligned.append(result_map.get(cid, 0))

    return aligned


# ---------------------------------------------------------------------------
# Ejecución de queries
# ---------------------------------------------------------------------------

def _execute_query_row(
    row: QueryRow,
    processor: QueryProcessor,
    mysql_main_executor: MySQLQueryExecutor,
    mysql_logs_executor: MySQLQueryExecutor | None,
    user_ids: list[int | str] | None = None,
) -> list[dict[str, Any]]:
    """Ejecuta una fila del CSV y retorna los resultados crudos."""

    # --- Step_1 + Step_2 ---
    if row.step_1 and row.step_2:
        step1_sql = processor.get_processed_step1(row)
        # Step_1 suele correr en logs
        if mysql_logs_executor and row.origin == "logs":
            s1_results = mysql_logs_executor.fetch_all(step1_sql)
        else:
            # Para Step_1 de logs que se ejecutan desde performance
            if mysql_logs_executor:
                s1_results = mysql_logs_executor.fetch_all(step1_sql)
            else:
                s1_results = mysql_main_executor.fetch_all(step1_sql)

        # Extraer IDs del Step_1
        ids: list[int | str] = []
        for r in s1_results:
            for v in r.values():
                val = str(v).strip().rstrip(",")
                if val:
                    try:
                        ids.append(int(float(val)))
                    except (ValueError, TypeError):
                        ids.append(val)

        step2_sql = processor.get_processed_step2(row, user_ids=ids)
        return mysql_main_executor.fetch_all(step2_sql)

    # --- Solo Step_1 (fila proveedora de IDs) ---
    if row.step_1 and not row.step_2:
        step1_sql = processor.get_processed_step1(row)
        if mysql_logs_executor:
            return mysql_logs_executor.fetch_all(step1_sql)
        return mysql_main_executor.fetch_all(step1_sql)

    # --- Solo Query simple ---
    if row.query and not row.query.lower().startswith("pasos"):
        sql = processor.get_processed_query(row, user_ids=user_ids)
        if row.origin == "logs" and mysql_logs_executor:
            return mysql_logs_executor.fetch_all(sql)
        return mysql_main_executor.fetch_all(sql)

    return []


# ---------------------------------------------------------------------------
# Ejecución de queries C3 con company_ids particionados en chunks + workers
# ---------------------------------------------------------------------------

def _inject_company_ids_filter(sql: str, company_ids_chunk: list[int]) -> str:
    """Inyecta un filtro de empresa ``IN (...)`` al SQL de una query C3.

    Auto-detecta la columna correcta según el contenido del SQL:
      - ``l.companies_id``  → queries contra la BD de logs (alias ``l``)
      - ``companies_id``    → queries contra logs sin alias
      - ``c.id``            → queries contra performance (alias ``c``)

    Estrategia de inserción: busca ``GROUP BY``, ``ORDER BY`` o ``LIMIT``
    (en ese orden) e inserta el filtro justo antes.
    Como último recurso, lo agrega al final antes del ``;``.
    """
    ids_str = ", ".join(str(cid) for cid in company_ids_chunk)

    # Detectar la columna de empresa correcta según el SQL
    lower_sql = sql.lower()
    if "l.companies_id" in lower_sql:
        column = "l.companies_id"
    elif "companies_id" in lower_sql and "from logs" in lower_sql:
        column = "companies_id"
    else:
        column = "c.id"

    filter_clause = f" AND {column} IN ({ids_str})"

    sql_stripped = sql.rstrip().rstrip(";")

    # Buscar la posición de inserción (antes de GROUP BY, ORDER BY o LIMIT)
    lower = sql_stripped.lower()

    # Para queries de logs con GROUP BY, insertar ANTES del GROUP BY
    group_pos = lower.rfind("group by")
    if group_pos > 0:
        return sql_stripped[:group_pos] + filter_clause + " " + sql_stripped[group_pos:] + ";"

    order_pos = lower.rfind("order by")
    if order_pos > 0:
        return sql_stripped[:order_pos] + filter_clause + " " + sql_stripped[order_pos:] + ";"

    limit_pos = lower.rfind("limit")
    if limit_pos > 0:
        return sql_stripped[:limit_pos] + filter_clause + " " + sql_stripped[limit_pos:] + ";"

    # Fallback: agregar al final
    return sql_stripped + filter_clause + ";"


def _fetch_query_chunk(
    sql: str,
    company_ids_chunk: list[int],
    use_logs_db: bool,
) -> list[dict[str, Any]]:
    """Cada worker abre su propia conexión y ejecuta la query C3 para un chunk de empresas."""
    chunk_sql = _inject_company_ids_filter(sql, company_ids_chunk)
    if use_logs_db:
        with MySQLLogsConnection() as conn:
            executor = MySQLQueryExecutor(conn)
            return executor.fetch_all(chunk_sql)
    else:
        with MySQLMainConnection() as conn:
            executor = MySQLQueryExecutor(conn)
            return executor.fetch_all(chunk_sql)


def _execute_query_chunked(
    sql: str,
    company_ids: list[int],
    companies: list[dict[str, Any]],
    use_logs_db: bool = False,
    chunk_size: int = QUERY_COMPANY_CHUNK_SIZE,
    max_workers: int = QUERY_MAX_WORKERS,
) -> list[Any]:
    """
    Particiona los company_ids en chunks y ejecuta la query C3 en workers paralelos.
    Cada worker abre su propia conexión MySQL y ejecuta la query filtrada a su
    subconjunto de empresas (`AND c.id IN (...)`).

    Los resultados parciales se fusionan y alinean al orden maestro de empresas.

    Si el total de empresas cabe en un solo chunk, ejecuta directo sin overhead.
    """
    if not company_ids:
        return [0] * len(companies)

    # Si caben en un solo chunk, ejecutar directo
    if len(company_ids) <= chunk_size:
        chunk_sql = _inject_company_ids_filter(sql, company_ids)
        if use_logs_db:
            with MySQLLogsConnection() as conn:
                executor = MySQLQueryExecutor(conn)
                results = executor.fetch_all(chunk_sql)
        else:
            with MySQLMainConnection() as conn:
                executor = MySQLQueryExecutor(conn)
                results = executor.fetch_all(chunk_sql)
        return _align_results_to_companies(companies, results)

    # Particionar en chunks
    chunks: list[list[int]] = []
    for i in range(0, len(company_ids), chunk_size):
        chunks.append(company_ids[i:i + chunk_size])

    total_chunks = len(chunks)
    db_name = "MySQL Logs" if use_logs_db else "MySQL Performance"
    print(f"        📦 Particionando {len(company_ids)} empresas → {total_chunks} chunks de ~{chunk_size}  ({max_workers} workers → {db_name})")

    # Ejecutar en paralelo
    partial_results: list[list[dict[str, Any]]] = [[] for _ in range(total_chunks)]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {
            pool.submit(_fetch_query_chunk, sql, chunk, use_logs_db): idx
            for idx, chunk in enumerate(chunks)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                rows = future.result()
                partial_results[idx] = rows
                print(f"           ✅ Chunk {idx + 1}/{total_chunks}: {len(rows)} filas")
            except Exception as e:
                print(f"           ❌ Chunk {idx + 1}/{total_chunks}: {e}")

    # Fusionar todos los resultados parciales
    all_results: list[dict[str, Any]] = []
    for partial in partial_results:
        all_results.extend(partial)

    return _align_results_to_companies(companies, all_results)


# ---------------------------------------------------------------------------
# Ejecución de Step_2 con user_ids particionados en chunks + workers
# ---------------------------------------------------------------------------

def _fetch_step2_chunk(
    step2_template: str,
    ids_chunk: list[int | str],
) -> list[dict[str, Any]]:
    """Ejecuta un Step_2 con un chunk de user_ids en su propia conexión MySQL."""
    from services.query_processor import PLACEHOLDER_USER_IDS
    ids_str = ",".join(str(int(float(uid))) for uid in ids_chunk)
    sql = step2_template.replace(PLACEHOLDER_USER_IDS, ids_str)
    with MySQLMainConnection() as conn:
        executor = MySQLQueryExecutor(conn)
        return executor.fetch_all(sql)


def _execute_step2_chunked(
    step2_template: str,
    user_ids: list[int | str],
    companies: list[dict[str, Any]],
    chunk_size: int = USER_IDS_CHUNK_SIZE,
    max_workers: int = USER_IDS_MAX_WORKERS,
) -> list[Any]:
    """
    Particiona los user_ids en chunks y ejecuta el Step_2 en workers paralelos.
    Cada worker abre su propia conexión MySQL.

    Los resultados parciales se fusionan (merge) por empresa:
      - Para conteos (int), se suman los parciales.
      - Para otros tipos, se toma el primer valor no-cero.

    Retorna una lista alineada al orden maestro de empresas.
    """
    if not user_ids:
        return [0] * len(companies)

    # Si caben en un solo chunk, ejecutar directo (sin overhead de workers)
    if len(user_ids) <= chunk_size:
        from services.query_processor import PLACEHOLDER_USER_IDS
        ids_str = ",".join(str(int(float(uid))) for uid in user_ids)
        sql = step2_template.replace(PLACEHOLDER_USER_IDS, ids_str)
        with MySQLMainConnection() as conn:
            executor = MySQLQueryExecutor(conn)
            results = executor.fetch_all(sql)
        return _align_results_to_companies(companies, results)

    # Particionar en chunks
    chunks: list[list[int | str]] = []
    for i in range(0, len(user_ids), chunk_size):
        chunks.append(user_ids[i:i + chunk_size])

    total_chunks = len(chunks)
    print(f"        📦 Particionando {len(user_ids):,} IDs → {total_chunks} chunks de ~{chunk_size:,}  ({max_workers} workers)")

    # Ejecutar en paralelo — cada worker abre su propia conexión
    partial_results: list[list[dict[str, Any]]] = [[] for _ in range(total_chunks)]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {
            pool.submit(_fetch_step2_chunk, step2_template, chunk): idx
            for idx, chunk in enumerate(chunks)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                rows = future.result()
                partial_results[idx] = rows
                print(f"           ✅ Chunk {idx + 1}/{total_chunks}: {len(rows)} filas")
            except Exception as e:
                print(f"           ❌ Chunk {idx + 1}/{total_chunks}: {e}")

    # Fusionar resultados parciales por empresa (sumar conteos)
    merged_map: dict[int, int] = {}
    for partial in partial_results:
        if not partial:
            continue
        sample = partial[0]
        cid_key = _find_company_id_key(sample)
        if cid_key is None:
            continue
        val_key = _find_value_column(sample, cid_key)
        if val_key is None:
            continue
        for r in partial:
            cid = r.get(cid_key)
            if cid is None:
                continue
            cid_int = int(cid)
            val = r.get(val_key, 0)
            try:
                merged_map[cid_int] = merged_map.get(cid_int, 0) + int(val)
            except (ValueError, TypeError):
                if cid_int not in merged_map:
                    merged_map[cid_int] = val

    # Alinear al orden maestro
    aligned: list[Any] = []
    for comp in companies:
        cid = int(comp["empresa_id"])
        aligned.append(merged_map.get(cid, 0))

    return aligned


# ---------------------------------------------------------------------------
# Contexto compartido entre opciones del menú
# ---------------------------------------------------------------------------

class _AppContext:
    """Almacena el estado compartido entre las diferentes opciones del menú."""

    def __init__(self):
        self.date_handler: DateHandler | None = None
        self.processor: QueryProcessor | None = None
        self.companies: list[dict[str, Any]] | None = None
        self.company_ids: list[int] | None = None
        self.generated_log_files: list[str] | None = None
        self.consolidated_csv_path: str | None = None
        self.consolidated_df: pd.DataFrame | None = None
        self.kpi_columns: dict[str, list[Any]] | None = None

    def ensure_params(self) -> None:
        """Solicita mes/año si aún no se han configurado."""
        if self.date_handler is None:
            mes, anio = ask_params()
            self.date_handler = DateHandler(month=mes, year=anio)
            print(f"\n📅 Mes seleccionado: {self.date_handler.nombre_mes} {self.date_handler.year}")
            print(f"   1 mes:   {self.date_handler.fecha_inicio} → {self.date_handler.fecha_fin}")
            print(f"   3 meses: {self.date_handler.fecha_inicio_3m} → {self.date_handler.fecha_fin}")
            print(f"   6 meses: {self.date_handler.fecha_inicio_6m} → {self.date_handler.fecha_fin}")

    def ensure_processor(self) -> None:
        """Carga el procesador de queries si aún no se ha hecho."""
        self.ensure_params()
        if self.processor is None:
            self.processor = QueryProcessor(csv_path=CSV_PATH, date_handler=self.date_handler)
            self.processor.load()
            self.processor.print_summary()

    def ensure_companies(self) -> bool:
        """Obtiene el listado maestro de empresas si aún no se tiene.
        Retorna True si se obtuvieron empresas."""
        if self.companies is not None:
            return True
        self.ensure_params()
        print("\n🔌 Obteniendo listado maestro de empresas...")
        with MySQLMainConnection() as conn:
            main_executor = MySQLQueryExecutor(conn)
            self.companies = main_executor.fetch_all(COMPANIES_QUERY)

        if not self.companies:
            print("⚠️  No se obtuvieron empresas del query maestro.")
            return False

        print(f"✅ {len(self.companies)} empresas obtenidas (orden canónico por nombre).")
        self.company_ids = [int(c["empresa_id"]) for c in self.companies]
        return True


# ---------------------------------------------------------------------------
# Funciones de cada opción del menú
# ---------------------------------------------------------------------------

def opt_test_connections(ctx: _AppContext) -> None:
    """Opción 1: Probar conectividad a las bases de datos."""
    print()
    ConnectionTester.test_all()


def opt_get_companies(ctx: _AppContext) -> None:
    """Opción 2: Obtener listado maestro de empresas."""
    ctx.ensure_companies()


def opt_export_logs(ctx: _AppContext) -> None:
    """Opción 3: Exportar logs del período (mes por mes en paralelo)."""
    if not ctx.ensure_companies():
        return
    ctx.generated_log_files = _export_logs(ctx.date_handler, ctx.company_ids)


def opt_consolidate_logs(ctx: _AppContext, auto: bool = False) -> None:
    """Opción 4: Consolidar los CSV de logs en un solo archivo y cargar en memoria.

    Si ``auto=True`` (flujo completo), consolida directamente sin preguntar.
    """
    ctx.ensure_params()

    if not auto:
        # --- Sub-menú: elegir la fuente de datos ---
        print(f"\n{'='*60}")
        print(f"📦 CONSOLIDAR LOGS EN UN SOLO CSV")
        print(f"{'='*60}")
        print(f"  [A] Consolidar desde archivos generados (opción 3 o disco)")
        print(f"  [B] Cargar un archivo CSV consolidado existente (indicar ruta)")
        print(f"{'='*60}")

        sub_choice = input("\n🔹 Seleccione una opción (A/B): ").strip().upper()

        if sub_choice == "B":
            # --- Opción B: seleccionar o indicar ruta de un CSV consolidado existente ---
            # Buscar archivos consolidados existentes en output/
            consolidados: list[str] = []
            if os.path.isdir(OUTPUT_DIR):
                consolidados = sorted(
                    os.path.join(OUTPUT_DIR, f)
                    for f in os.listdir(OUTPUT_DIR)
                    if f.startswith("logs_consolidado_") and f.endswith(".csv")
                )

            if consolidados:
                print(f"\n📂 Archivos consolidados encontrados en output/:")
                for i, path in enumerate(consolidados, start=1):
                    print(f"   [{i}] {os.path.basename(path)}")
                print(f"   [0] Indicar otra ruta manualmente")

                sel = input("\n🔹 Seleccione un número: ").strip()
                if sel.isdigit() and 1 <= int(sel) <= len(consolidados):
                    ruta = consolidados[int(sel) - 1]
                elif sel == "0":
                    ruta = input("📂 Ingrese la ruta completa del archivo CSV consolidado: ").strip()
                    ruta = ruta.strip('"').strip("'")
                else:
                    print("⚠️  Selección inválida.")
                    return
            else:
                ruta = input("📂 Ingrese la ruta completa del archivo CSV consolidado: ").strip()
                ruta = ruta.strip('"').strip("'")

            if not os.path.isfile(ruta):
                print(f"\n⚠️  El archivo no existe: {ruta}")
                return

            print(f"\n📄 Cargando archivo en memoria: {ruta}")
            try:
                df = pd.read_csv(ruta, encoding="utf-8")
            except Exception as e:
                print(f"❌ Error al leer el archivo: {e}")
                return

            ctx.consolidated_csv_path = ruta
            ctx.consolidated_df = df
            mem_mb = df.memory_usage(deep=True).sum() / 1024 / 1024

            print(f"\n✅ Archivo cargado exitosamente")
            print(f"   📁 Ruta     : {ruta}")
            print(f"   📊 Registros: {len(df):,}")
            print(f"   📋 Columnas : {list(df.columns)}")
            print(f"   💾 Memoria  : {mem_mb:.1f} MB")
            print(f"{'='*60}")
            return

    # --- Opción A (default): consolidar desde archivos generados ---

    # Verificar si ya existe un archivo consolidado en disco para el rango actual
    month_ranges = _get_month_ranges(ctx.date_handler)
    first_m_name = DateHandler.MESES[month_ranges[0][1]]
    first_m_year = month_ranges[0][0]
    last_m_name = DateHandler.MESES[month_ranges[-1][1]]
    last_m_year = month_ranges[-1][0]
    expected_filename = (
        f"logs_consolidado_{first_m_name}_{first_m_year}"
        f"_a_{last_m_name}_{last_m_year}.csv"
    )
    expected_path = os.path.join(OUTPUT_DIR, expected_filename)

    if os.path.isfile(expected_path):
        size_mb = os.path.getsize(expected_path) / 1024 / 1024
        print(f"\n📂 Se encontró un archivo consolidado existente:")
        print(f"   📄 {expected_filename} ({size_mb:.1f} MB en disco)")

        if auto:
            # En flujo automático, cargar directamente sin preguntar
            load_existing = True
        else:
            sel = input("\n🔹 ¿Desea cargarlo en memoria directamente? (S/N): ").strip().upper()
            load_existing = sel in ("S", "SI", "SÍ", "Y", "YES")

        if load_existing:
            print(f"\n📄 Cargando archivo consolidado existente en memoria...")
            try:
                df = pd.read_csv(expected_path, encoding="utf-8")
            except Exception as e:
                print(f"❌ Error al leer el archivo: {e}")
                return

            ctx.consolidated_csv_path = expected_path
            ctx.consolidated_df = df
            mem_mb = df.memory_usage(deep=True).sum() / 1024 / 1024

            print(f"\n{'='*60}")
            print(f"✅ Consolidado cargado desde disco (sin re-procesar)")
            print(f"   📁 Ruta     : {expected_path}")
            print(f"   📊 Registros: {len(df):,}")
            print(f"   📋 Columnas : {list(df.columns)}")
            print(f"   💾 Memoria  : {mem_mb:.1f} MB")
            print(f"{'='*60}")
            return

        print("\n🔄 Se procederá a re-consolidar desde los archivos por mes...")

    # Buscar archivos individuales por mes
    if ctx.generated_log_files is None:
        # Intentar detectar archivos generados previamente en disco
        existing: list[str] = []
        for m_year, m_month, _, _ in month_ranges:
            m_name = DateHandler.MESES[m_month]
            path = os.path.join(OUTPUT_DIR, str(m_year), f"logs_{m_name}_{m_year}.csv")
            if os.path.isfile(path):
                existing.append(path)
        if existing:
            print(f"\n📂 Se encontraron {len(existing)} archivos de logs previos en disco.")
            ctx.generated_log_files = existing
        else:
            print("\n⚠️  No hay archivos de logs generados. Ejecute primero la opción 3 (Exportar logs).")
            return

    result_path, result_df = _consolidate_logs(ctx.generated_log_files, ctx.date_handler)
    ctx.consolidated_csv_path = result_path
    ctx.consolidated_df = result_df


def _build_section_index(rows: list[QueryRow]) -> list[dict[str, Any]]:
    """Construye un índice de secciones con sus filas hijas.

    Retorna una lista de dicts con:
      - 'name': nombre de la sección (title o kpi del encabezado)
      - 'header_idx': índice del encabezado en la lista ``rows``
      - 'row_indices': lista de índices de filas ejecutables de la sección
      - 'kpi_labels': lista de labels de los KPIs de la sección (solo para mostrar)
      - 'has_provider': True si la sección tiene un proveedor de IDs (Step_1)
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for i, row in enumerate(rows):
        if row.is_header:
            if current is not None:
                sections.append(current)
            current = {
                "name": row.title or row.kpi,
                "header_idx": i,
                "row_indices": [],
                "kpi_labels": [],
                "has_provider": False,
            }
            continue

        if current is not None:
            current["row_indices"].append(i)
            # Detectar proveedores de IDs
            if row.step_1 and not row.step_2 and not row.query:
                current["has_provider"] = True
                current["kpi_labels"].append(f"🔗 {row.kpi or '(proveedor de IDs)'}")
            else:
                current["kpi_labels"].append(row.label or row.kpi)

    if current is not None:
        sections.append(current)

    return sections


def _truncate_query(sql: str, max_len: int = 90) -> str:
    """Trunca un SQL para mostrar un preview legible en una sola línea."""
    if not sql:
        return ""
    # Colapsar espacios múltiples y saltos de línea
    collapsed = " ".join(sql.split())
    if len(collapsed) <= max_len:
        return collapsed
    return collapsed[:max_len] + "…"


def _describe_row_queries(row: "QueryRow") -> list[str]:
    """Genera líneas descriptivas con las queries de una fila del CSV.

    Retorna una lista de strings listos para imprimir (sin indentación inicial).
    """
    lines: list[str] = []
    is_provider = row.step_1 and not row.step_2 and not row.query
    is_perf_social = row.origin == "performance-social" and row.step_1 and row.step_2
    is_csv_logs = row.origin == "csv-logs" and row.query
    has_c3_and_c5 = row.query and row.step_2
    has_only_step2 = row.step_2 and not row.step_1 and not row.query

    if is_provider:
        lines.append(f"└─ [{row.origin}] Step_1: {_truncate_query(row.step_1)}")
    elif is_perf_social:
        lines.append(f"├─ [performance] Step_1: {_truncate_query(row.step_1)}")
        # Detectar colección MongoDB
        coll = _detect_mongo_collection(row.step_2)
        lines.append(f"└─ [MongoDB → {coll}] Step_2: {_truncate_query(row.step_2)}")
    elif has_c3_and_c5:
        lines.append(f"├─ [{row.origin}] C3: {_truncate_query(row.query)}")
        lines.append(f"└─ [performance] C5: {_truncate_query(row.step_2)}")
    elif has_only_step2:
        lines.append(f"└─ [performance] Step_2: {_truncate_query(row.step_2)}")
    elif is_csv_logs:
        lines.append(f"└─ [csv-logs] Query: {_truncate_query(row.query)}")
    elif row.query:
        lines.append(f"└─ [{row.origin}] Query: {_truncate_query(row.query)}")

    return lines


def _ask_section_selection(
    sections: list[dict[str, Any]],
    rows: list["QueryRow"] | None = None,
) -> set[int] | None:
    """Muestra las secciones disponibles y permite seleccionar una o varias.

    Si se proporciona ``rows``, muestra además un preview de las queries
    asociadas a cada KPI.

    Retorna:
      - ``None`` → ejecutar TODAS las filas (sin filtro).
      - ``set[int]`` → conjunto de índices de filas (row_indices) seleccionadas.
        Incluye automáticamente los encabezados y proveedores de IDs necesarios.
    """
    print(f"\n{'='*65}")
    print(f"📋 SECCIONES DISPONIBLES EN query.csv")
    print(f"{'='*65}")
    for s_idx, sec in enumerate(sections, start=1):
        n_kpis = sum(1 for lbl in sec["kpi_labels"] if not lbl.startswith("🔗"))
        provider = " 🔗" if sec["has_provider"] else ""
        print(f"  [{s_idx:>2}] {sec['name']}{provider}  ({n_kpis} KPIs)")

        # Mostrar cada KPI con su query asociada
        for lbl_idx, lbl in enumerate(sec["kpi_labels"]):
            if lbl.startswith("🔗"):
                print(f"        {lbl}")
            else:
                print(f"        • {lbl}")

            # Mostrar detalle de queries si se proporcionaron las filas
            if rows is not None and lbl_idx < len(sec["row_indices"]):
                row_i = sec["row_indices"][lbl_idx]
                if row_i < len(rows):
                    for qline in _describe_row_queries(rows[row_i]):
                        print(f"          {qline}")

    print(f"  [ A] Ejecutar TODAS las secciones")
    print(f"{'='*65}")

    sel_input = input(
        "\n🔹 Seleccione secciones (ej: 1,3,5  o  2-6  o  A para todas): "
    ).strip().upper()

    if not sel_input or sel_input == "A":
        return None  # Todas

    # Parsear selección: soporta "1,3,5" y "2-6" y combinaciones "1,3-5,8"
    selected_section_nums: set[int] = set()
    for part in sel_input.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                lo, hi = int(bounds[0]), int(bounds[1])
                for n in range(lo, hi + 1):
                    selected_section_nums.add(n)
            except ValueError:
                pass
        else:
            try:
                selected_section_nums.add(int(part))
            except ValueError:
                pass

    if not selected_section_nums:
        print("  ⚠️  Selección inválida. Se ejecutarán todas las secciones.")
        return None

    # Validar rango
    valid = {n for n in selected_section_nums if 1 <= n <= len(sections)}
    if not valid:
        print("  ⚠️  Ninguna sección válida seleccionada. Se ejecutarán todas.")
        return None

    # Construir set de índices de filas seleccionadas
    # Incluir header_idx y todos los row_indices de las secciones seleccionadas
    selected_row_indices: set[int] = set()
    selected_names: list[str] = []
    for n in sorted(valid):
        sec = sections[n - 1]
        selected_row_indices.add(sec["header_idx"])
        selected_row_indices.update(sec["row_indices"])
        selected_names.append(sec["name"])

    print(f"\n✅ Secciones seleccionadas ({len(valid)}/{len(sections)}):")
    for name in selected_names:
        print(f"   📂 {name}")

    return selected_row_indices


def opt_execute_queries(ctx: _AppContext, select_all: bool = False) -> None:
    """Opción 5: Ejecutar queries del CSV y alinear al orden maestro.

    Args:
        select_all: Si True, ejecuta todas las secciones sin preguntar
                    (usado por el flujo completo opción 7).
    """
    if not ctx.ensure_companies():
        return
    ctx.ensure_processor()

    companies = ctx.companies
    date_handler = ctx.date_handler
    processor = ctx.processor
    consolidated_csv_path = ctx.consolidated_csv_path

    # ── Auto-detección del CSV consolidado en disco ─────────────────────
    if not consolidated_csv_path:
        month_ranges = _get_month_ranges(date_handler)
        first_m_name = DateHandler.MESES[month_ranges[0][1]]
        first_m_year = month_ranges[0][0]
        last_m_name = DateHandler.MESES[month_ranges[-1][1]]
        last_m_year = month_ranges[-1][0]
        candidate = os.path.join(
            OUTPUT_DIR,
            f"logs_consolidado_{first_m_name}_{first_m_year}"
            f"_a_{last_m_name}_{last_m_year}.csv",
        )
        if os.path.isfile(candidate):
            consolidated_csv_path = candidate
            ctx.consolidated_csv_path = candidate

    # ── Selección de secciones ──────────────────────────────────────────
    rows = processor.rows
    sections = _build_section_index(rows)

    selected_indices: set[int] | None = None
    if not select_all:
        selected_indices = _ask_section_selection(sections, rows=rows)
    # selected_indices == None → ejecutar todo (sin filtro)

    # ── Encabezado general ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"⚙️  EJECUTAR QUERIES DEL CSV (KPIs)")
    print(f"{'='*65}")

    # Resumen de parámetros y fechas
    print(f"\n📅 Parámetros de fecha:")
    print(f"   Mes / Año seleccionado : {date_handler.nombre_mes} {date_handler.year}")
    print(f"   1 mes  (fecha_inicio)  : {date_handler.fecha_inicio} → {date_handler.fecha_fin}")
    print(f"   3 meses (fecha_inicio_3m): {date_handler.fecha_inicio_3m} → {date_handler.fecha_fin}")
    print(f"   6 meses (fecha_inicio_6m): {date_handler.fecha_inicio_6m} → {date_handler.fecha_fin}")

    # Resumen del CSV de entrada
    total_rows = len(processor.rows)
    exec_rows = len(processor.executable_rows)
    print(f"\n📄 CSV de queries: {CSV_PATH}")
    print(f"   Filas totales: {total_rows}  |  Ejecutables: {exec_rows}")

    # Fuente de datos para Step_1 de logs
    use_csv_for_logs = consolidated_csv_path and os.path.isfile(consolidated_csv_path)
    print(f"\n📂 Fuente de datos para Step_1 (origin=logs):")
    if use_csv_for_logs:
        print(f"   ✅ CSV consolidado disponible: {consolidated_csv_path}")
        print(f"      → Se leerán user_ids desde el CSV (sin consultar BD logs)")
    else:
        print(f"   ⚠️  CSV consolidado NO disponible → Se consultará la BD de logs directamente")
        print(f"      Motivo: No se ejecutó la opción 4 y no se encontró archivo previo en disco.")
        print(f"      Tip: Ejecute opción [4] (Consolidar logs) antes de [5], o use [7] (flujo completo).")

    # ── Preparar conexiones persistentes ────────────────────────────────
    print(f"\n🔌 Estableciendo conexiones a bases de datos...")

    mysql_main_cm = MySQLMainConnection()
    mysql_main_conn = mysql_main_cm.connect()
    main_exec = MySQLQueryExecutor(mysql_main_conn)
    print(f"   ✅ MySQL Principal (performance): conectado")

    mysql_logs_exec: MySQLQueryExecutor | None = None
    mysql_logs_cm = None
    try:
        mysql_logs_cm = MySQLLogsConnection()
        logs_conn = mysql_logs_cm.connect()
        mysql_logs_exec = MySQLQueryExecutor(logs_conn)
        print(f"   ✅ MySQL Logs: conectado")
    except Exception as e:
        print(f"   ⚠️  MySQL Logs: NO disponible — {e}")

    mongo_exec: MongoQueryExecutor | None = None
    mongo_cm = None
    try:
        mongo_cm = MongoConnection()
        mongo_db = mongo_cm.connect()
        mongo_exec = MongoQueryExecutor(mongo_db)
        print(f"   ✅ MongoDB: conectado")
    except Exception as e:
        print(f"   ⚠️  MongoDB: NO disponible — {e}")

    # Resumen de conexiones
    conns_disponibles = ["MySQL Performance"]
    if mysql_logs_exec:
        conns_disponibles.append("MySQL Logs")
    if mongo_exec:
        conns_disponibles.append("MongoDB")
    print(f"   Conexiones activas: {', '.join(conns_disponibles)}")

    # ── Modo de ejecución ───────────────────────────────────────────────
    if selected_indices is not None:
        # Contar cuántas filas ejecutables están seleccionadas
        exec_selected = sum(1 for r_idx in range(len(rows))
                           if r_idx in selected_indices and not rows[r_idx].is_header)
        print(f"\n🎯 Modo: ejecución selectiva ({exec_selected}/{exec_rows} queries seleccionados)")
        print(f"   Las columnas de secciones NO seleccionadas aparecerán con valor 0")
        print(f"   pero mantendrán su posición en el reporte final.")
    else:
        exec_selected = exec_rows

    # ── Ejecución fila por fila ─────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"🚀 INICIO DE EJECUCIÓN — {exec_selected} queries")
    print(f"{'='*65}")

    # Diccionario: kpi_label → lista de valores alineados al orden maestro
    kpi_columns: dict[str, list[Any]] = {}
    # user_ids compartidos entre Step_1 y filas dependientes
    current_user_ids: list[int | str] | None = None
    # Contadores para resumen final
    _count_ok = 0
    _count_err = 0
    _count_skip = 0
    _current_section = ""

    def _describe_date_filters(row: QueryRow, dh: DateHandler) -> list[str]:
        """Retorna líneas descriptivas con las fechas reales aplicadas a la fila."""
        combined = f"{row.query}{row.step_1}{row.step_2}"
        lines: list[str] = []
        has_6m = "{fecha_inicio_6m}" in combined
        has_3m = "{fecha_inicio_3m}" in combined
        # Para detectar {fecha_inicio} sin confundirlo con {fecha_inicio_3m}/{fecha_inicio_6m},
        # eliminamos las variantes extendidas y verificamos si queda el simple.
        cleaned = combined.replace("{fecha_inicio_3m}", "").replace("{fecha_inicio_6m}", "")
        has_1m = "{fecha_inicio}" in cleaned

        if has_6m:
            lines.append(f"     Filtro 6m  : {dh.fecha_inicio_6m} → {dh.fecha_fin}")
        if has_3m:
            lines.append(f"     Filtro 3m  : {dh.fecha_inicio_3m} → {dh.fecha_fin}")
        if has_1m:
            lines.append(f"     Filtro 1m  : {dh.fecha_inicio} → {dh.fecha_fin}")
        if not lines and "{fecha_fin}" in combined:
            lines.append(f"     Filtro fin : → {dh.fecha_fin}")
        return lines

    for i, row in enumerate(rows):
        if row.is_header:
            current_user_ids = None  # Resetear IDs al cambiar de sección
            _current_section = row.title or row.kpi
            # Si hay filtro de secciones, verificar si esta sección está seleccionada
            _section_selected = (selected_indices is None) or (i in selected_indices)
            if _section_selected:
                print(f"\n{'─'*65}")
                print(f"📂 Sección: {_current_section}")
                print(f"{'─'*65}")
            else:
                print(f"\n{'─'*65}")
                print(f"⏭️  Sección: {_current_section}  (NO seleccionada — columnas en 0)")
                print(f"{'─'*65}")
            continue

        # Determinar label único para la columna (C6 - C1 cuando C1 tiene valor)
        label = row.label
        row_num = i + 1

        # ── Verificar si la fila está seleccionada ──────────────────────
        if selected_indices is not None and i not in selected_indices:
            # Fila no seleccionada: registrar columna con 0 para mantener posición
            # (solo si la fila genera una columna KPI, NO proveedores de IDs)
            is_provider = row.step_1 and not row.step_2 and not row.query
            if not is_provider and label:
                kpi_columns[label] = [0] * len(companies)
                print(f"\n  ⏭️  [{row_num}] {label}  → columna en 0 (sección no seleccionada)")
            _count_skip += 1
            continue

        # --- Filas que son proveedoras de IDs (solo Step_1, sin Step_2 ni Query) ---
        if row.step_1 and not row.step_2 and not row.query:
            print(f"\n  🔗 [{row_num}] {row.kpi}")
            print(f"     Tipo       : Proveedor de IDs (solo Step_1)")
            print(f"     Origin     : {row.origin}")
            try:
                # Si origin=logs y tenemos el CSV consolidado → leer del CSV
                if row.origin == "logs" and use_csv_for_logs:
                    fecha_ini, fecha_end = _detect_date_range_for_step1(row, date_handler)
                    rango_tipo = "3 meses" if "{fecha_inicio_3m}" in row.step_1 else "1 mes"
                    print(f"     Fuente     : 📄 CSV consolidado (lectura local)")
                    print(f"     Filtro fecha: {fecha_ini} → {fecha_end}  ({rango_tipo})")
                    print(f"     Filtro msg  : {_LOGIN_MESSAGES}")
                    current_user_ids = _extract_user_ids_from_csv(
                        consolidated_csv_path, fecha_ini, fecha_end,
                    )
                    print(f"     ✅ Resultado : {len(current_user_ids)} user_ids obtenidos")
                else:
                    # Fallback: ejecutar contra la BD de logs
                    step1_sql = processor.get_processed_step1(row)
                    target_db = "MySQL Logs" if mysql_logs_exec else "MySQL Performance (fallback)"
                    print(f"     Fuente     : 🗄️  {target_db} (consulta SQL)")
                    for fl in _describe_date_filters(row, date_handler):
                        print(fl)
                    if mysql_logs_exec:
                        s1_results = mysql_logs_exec.fetch_all(step1_sql)
                    else:
                        s1_results = main_exec.fetch_all(step1_sql)

                    current_user_ids = []
                    for r in s1_results:
                        for v in r.values():
                            val = str(v).strip().rstrip(",")
                            if val:
                                try:
                                    current_user_ids.append(int(float(val)))
                                except (ValueError, TypeError):
                                    current_user_ids.append(val)
                    print(f"     ✅ Resultado : {len(current_user_ids)} user_ids obtenidos (desde BD)")
                _count_ok += 1
            except Exception as e:
                print(f"     ❌ Error    : {e}")
                current_user_ids = None
                _count_err += 1
            continue

        # --- Filas performance-social: Step_1 en MySQL + Step_2 en MongoDB ---
        if row.origin == "performance-social" and row.step_1 and row.step_2:
            print(f"\n  🔗🍃 [{row_num}] {row.kpi}")
            print(f"     Tipo       : Performance-Social (Step_1 MySQL → Step_2 MongoDB)")
            print(f"     Origin     : {row.origin}")
            print(f"     Label      : {label}")
            try:
                # Step_1: ejecutar SQL contra performance para obtener IDs
                step1_sql = processor.get_processed_step1(row)
                print(f"     ── Paso 1/2: Step_1 → MySQL Performance")
                for fl in _describe_date_filters(row, date_handler):
                    print(f"     {fl.strip()}")
                s1_results = main_exec.fetch_all(step1_sql)

                ids: list[int | str] = []
                for r in s1_results:
                    for v in r.values():
                        val = str(v).strip().rstrip(",")
                        if val:
                            try:
                                ids.append(int(float(val)))
                            except (ValueError, TypeError):
                                ids.append(val)
                print(f"        Resultado: {len(ids)} IDs obtenidos")

                if not mongo_exec:
                    print(f"     ⚠️  Sin conexión MongoDB → Step_2 omitido, valores en 0")
                    kpi_columns[label] = [0] * len(companies)
                    _count_skip += 1
                    continue

                # Step_2: parsear pipeline MongoDB, inyectar IDs y fechas
                step2_raw = row.step_2
                collection_name = _detect_mongo_collection(step2_raw)
                pipeline = _parse_mongo_pipeline(
                    step2_raw, ids,
                    date_handler.fecha_inicio, date_handler.fecha_fin,
                )
                print(f"     ── Paso 2/2: Step_2 → MongoDB (colección: '{collection_name}')")
                print(f"        IDs inyectados: {len(ids)}")
                fecha_fin_next = (date.fromisoformat(date_handler.fecha_fin) + timedelta(days=1)).isoformat()
                print(f"        Fechas filtro : $gte {date_handler.fecha_inicio} → $lt {fecha_fin_next}")

                mongo_results = mongo_exec.aggregate(collection_name, pipeline)
                aligned = _align_mongo_results_to_companies(companies, mongo_results)
                kpi_columns[label] = aligned
                print(f"     ✅ Resultado : {len(mongo_results)} docs MongoDB → alineados a {len(companies)} empresas")
                _count_ok += 1
            except Exception as e:
                print(f"     ❌ Error    : {e}")
                kpi_columns[label] = [0] * len(companies)
                _count_err += 1
            continue

        # --- Filas con Query + Step_2 (tienen su propia Query principal y un Step_2 con user_ids) ---
        if row.query and row.step_2:
            ids_count = len(current_user_ids) if current_user_ids else 0
            use_logs = row.origin == "logs" and mysql_logs_exec is not None
            print(f"\n  ⏳ [{row_num}] {row.kpi}")
            print(f"     Tipo       : Query (C3) + Step_2 (C5) → Suma")
            print(f"     Origin     : {row.origin}")
            print(f"     Label      : {label}")
            for fl in _describe_date_filters(row, date_handler):
                print(fl)
            try:
                # Query principal (C3) contra performance — chunked por empresas
                target_q = "MySQL Logs" if use_logs else "MySQL Performance"
                print(f"     ── Paso 1/2: Query (C3) → {target_q} (chunked por empresas)")
                sql = processor.get_processed_query(row)
                aligned_q = _execute_query_chunked(
                    sql, ctx.company_ids, companies,
                    use_logs_db=use_logs,
                )
                print(f"        Resultado: alineado a {len(companies)} empresas")

                # Step_2 (C5) con user_ids del Step_1 anterior — chunked si hay muchos IDs
                print(f"     ── Paso 2/2: Step_2 (C5) → MySQL Performance")
                print(f"        user_ids: {ids_count} IDs a inyectar en {{user_ids}}")
                # Obtener el template con fechas reemplazadas pero {user_ids} intacto
                step2_template = processor.replace_dates(row.step_2)
                aligned_s2 = _execute_step2_chunked(
                    step2_template, current_user_ids or [], companies,
                )
                print(f"        Resultado: alineado a {len(companies)} empresas")

                # Sumar C3 + C5 elemento a elemento por empresa
                aligned_sum = []
                for vq, vs in zip(aligned_q, aligned_s2):
                    try:
                        aligned_sum.append(int(vq) + int(vs))
                    except (ValueError, TypeError):
                        aligned_sum.append(vq)
                kpi_columns[label] = aligned_sum

                print(f"     ✅ Resultado : C3(chunked) + C5(chunked) → Sumados para {len(companies)} empresas")
                _count_ok += 1
            except Exception as e:
                print(f"     ❌ Error    : {e}")
                kpi_columns[label] = [0] * len(companies)
                _count_err += 1
            continue

        # --- Filas con solo Step_2 (dependen de los user_ids previos, sin Query en C3) ---
        if row.step_2 and not row.step_1:
            ids_count = len(current_user_ids) if current_user_ids else 0
            print(f"\n  ⏳ [{row_num}] {row.kpi}")
            print(f"     Tipo       : Step_2 (depende de user_ids previos)")
            print(f"     Origin     : {row.origin}")
            print(f"     Label      : {label}")
            print(f"     Destino BD : MySQL Performance")
            print(f"     user_ids   : {ids_count} IDs inyectados en {{user_ids}}")
            for fl in _describe_date_filters(row, date_handler):
                print(fl)
            try:
                # Obtener el template con fechas reemplazadas pero {user_ids} intacto
                step2_template = processor.replace_dates(row.step_2)
                aligned = _execute_step2_chunked(
                    step2_template, current_user_ids or [], companies,
                )
                kpi_columns[label] = aligned
                print(f"     ✅ Resultado : alineado a {len(companies)} empresas")
                _count_ok += 1
            except Exception as e:
                print(f"     ❌ Error    : {e}")
                kpi_columns[label] = [0] * len(companies)
                _count_err += 1
            continue

        # --- Filas csv-logs: KPIs sociales leídos desde el CSV consolidado ---
        if row.origin == "csv-logs" and row.query:
            print(f"\n  📄 [{row_num}] {row.kpi}")
            print(f"     Tipo       : Query leída desde CSV consolidado (sin BD de logs)")
            print(f"     Origin     : {row.origin}")
            print(f"     Label      : {label}")
            for fl in _describe_date_filters(row, date_handler):
                print(fl)
            try:
                if not use_csv_for_logs or not consolidated_csv_path:
                    print(f"     ⚠️  CSV consolidado no disponible → columna en 0")
                    kpi_columns[label] = [0] * len(companies)
                    _count_skip += 1
                    continue

                # Extraer filtros del SQL original
                raw_sql = processor.get_processed_query(row)
                messages_filter, user_types_filter = _parse_csv_logs_query(raw_sql)
                print(f"     Mensajes   : {messages_filter}")
                print(f"     userTypes  : {user_types_filter}")
                print(f"     Fuente     : 📄 {consolidated_csv_path}")

                aligned = _extract_social_kpi_from_csv(
                    consolidated_csv_path,
                    date_handler.fecha_inicio,
                    date_handler.fecha_fin,
                    messages_filter,
                    user_types_filter,
                    companies,
                    excluded_user_ids=_load_superadmin_user_ids(),
                )
                kpi_columns[label] = aligned
                print(f"     ✅ Resultado : alineado a {len(companies)} empresas")
                _count_ok += 1
            except Exception as e:
                print(f"     ❌ Error    : {e}")
                kpi_columns[label] = [0] * len(companies)
                _count_err += 1
            continue

        # --- Filas con solo Query simple ---
        if row.query and not row.query.lower().startswith("pasos"):
            use_logs = row.origin == "logs" and mysql_logs_exec is not None
            target_db = "MySQL Logs" if use_logs else "MySQL Performance"
            ids_count = len(current_user_ids) if current_user_ids else 0
            print(f"\n  ⏳ [{row_num}] {row.kpi}")
            print(f"     Tipo       : Query simple (C3) — chunked por empresas")
            print(f"     Origin     : {row.origin}")
            print(f"     Label      : {label}")
            print(f"     Destino BD : {target_db}")
            for fl in _describe_date_filters(row, date_handler):
                print(fl)
            if row.has_user_ids_placeholder:
                print(f"     user_ids   : {ids_count} IDs inyectados en {{user_ids}}")
            try:
                if row.has_user_ids_placeholder and current_user_ids:
                    # Query con {user_ids} → usar chunking por user_ids
                    query_template = processor.replace_dates(row.query)
                    aligned = _execute_step2_chunked(
                        query_template, current_user_ids, companies,
                    )
                    kpi_columns[label] = aligned
                    print(f"     ✅ Resultado : chunked (user_ids) → alineado a {len(companies)} empresas")
                else:
                    # Query sin {user_ids} → chunking por company_ids en paralelo
                    sql = processor.get_processed_query(row, user_ids=current_user_ids)
                    aligned = _execute_query_chunked(
                        sql, ctx.company_ids, companies,
                        use_logs_db=use_logs,
                    )
                    kpi_columns[label] = aligned
                    print(f"     ✅ Resultado : chunked (empresas) → alineado a {len(companies)} empresas")
                _count_ok += 1
            except Exception as e:
                print(f"     ❌ Error    : {e}")
                kpi_columns[label] = [0] * len(companies)
                _count_err += 1
            continue

        # --- Filas no ejecutables (sin query ni steps válidos) ---
        _count_skip += 1

    # ── Cerrar conexiones ───────────────────────────────────────────────
    mysql_main_cm.close()
    if mysql_logs_cm:
        mysql_logs_cm.close()
    if mongo_cm:
        mongo_cm.close()

    # ── Resumen final ───────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"📊 RESUMEN DE EJECUCIÓN DE QUERIES (KPIs)")
    print(f"{'='*65}")
    if selected_indices is not None:
        print(f"   🎯 Modo              : ejecución selectiva")
    else:
        print(f"   🎯 Modo              : todas las secciones")
    print(f"   Queries ejecutados OK : {_count_ok}")
    print(f"   Queries con error     : {_count_err}")
    print(f"   Queries omitidos/skip : {_count_skip}")
    print(f"   KPIs generados        : {len(kpi_columns)} columnas (todas mantienen posición)")
    print(f"   Empresas (maestro)    : {len(companies)}")
    if kpi_columns:
        print(f"\n   Columnas KPI generadas:")
        for idx, kpi_name in enumerate(kpi_columns, start=1):
            non_zero = sum(1 for v in kpi_columns[kpi_name] if v not in (0, "0", "", None))
            marker = "" if non_zero > 0 else " ⏭️"
            print(f"     {idx:>3}. {kpi_name}  ({non_zero}/{len(companies)} empresas con datos){marker}")
    print(f"{'='*65}")

    ctx.kpi_columns = kpi_columns


def opt_export_report(ctx: _AppContext) -> None:
    """Opción 6: Exportar reporte consolidado a CSV."""
    if ctx.companies is None:
        print("\n⚠️  No hay listado de empresas. Ejecute primero la opción 2.")
        return
    if ctx.kpi_columns is None or len(ctx.kpi_columns) == 0:
        print("\n⚠️  No hay KPIs calculados. Ejecute primero la opción 5 (Ejecutar queries).")
        return

    companies = ctx.companies
    kpi_columns = ctx.kpi_columns
    date_handler = ctx.date_handler

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_file = os.path.join(
        OUTPUT_DIR,
        f"report_{date_handler.nombre_mes}_{date_handler.year}.csv",
    )

    # Construir encabezados: empresa_id | empresa_nombre | hubspot_id | KPI_1 | KPI_2 | ...
    kpi_names = list(kpi_columns.keys())
    fieldnames = ["empresa_id", "empresa_nombre", "hubspot_id"] + kpi_names

    with open(output_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for idx, comp in enumerate(companies):
            row_data = [
                comp["empresa_id"],
                comp["empresa_nombre"],
                comp["hubspot_id"],
            ]
            for kpi in kpi_names:
                row_data.append(kpi_columns[kpi][idx])
            writer.writerow(row_data)

    print(f"\n✅ Reporte exportado: {output_file}")
    print(f"   {len(companies)} empresas × {len(kpi_names)} KPIs")


def opt_run_all(ctx: _AppContext) -> None:
    """Opción 7: Ejecutar todo el flujo completo."""
    opt_test_connections(ctx)
    opt_get_companies(ctx)
    if ctx.companies is None:
        return
    opt_export_logs(ctx)
    opt_consolidate_logs(ctx, auto=True)
    opt_execute_queries(ctx, select_all=True)
    opt_export_report(ctx)


# ---------------------------------------------------------------------------
# Menú interactivo
# ---------------------------------------------------------------------------

_MENU_OPTIONS = {
    "1": ("Probar conectividad a las bases de datos", opt_test_connections),
    "2": ("Obtener listado maestro de empresas", opt_get_companies),
    "3": ("Exportar logs del período (mes por mes)", opt_export_logs),
    "4": ("Consolidar logs en un solo CSV (o cargar existente)", opt_consolidate_logs),
    "5": ("Ejecutar queries del CSV (KPIs)", opt_execute_queries),
    "6": ("Exportar reporte consolidado a CSV", opt_export_report),
    "7": ("Ejecutar todo (flujo completo)", opt_run_all),
    "0": ("Salir", None),
}


def _print_menu() -> None:
    """Imprime el menú de opciones."""
    print(f"\n{'='*60}")
    print("📋 MENÚ PRINCIPAL — Report QPU Support")
    print(f"{'='*60}")
    for key, (desc, _) in _MENU_OPTIONS.items():
        emoji = "🚪" if key == "0" else "▶️"
        print(f"  {emoji} [{key}] {desc}")
    print(f"{'='*60}")


def _format_elapsed(seconds: float) -> str:
    """Convierte segundos en un string legible: HH:MM:SS.mmm"""
    hrs, remainder = divmod(seconds, 3600)
    mins, secs = divmod(remainder, 60)
    if hrs > 0:
        return f"{int(hrs)}h {int(mins)}m {secs:.2f}s"
    if mins > 0:
        return f"{int(mins)}m {secs:.2f}s"
    return f"{secs:.2f}s"


def main():
    log_file, log_path = _setup_logging()
    print(f"📝 Logging activo → {log_path}")

    session_start = datetime.now()
    print(f"🕐 Sesión iniciada: {session_start.strftime('%Y-%m-%d %H:%M:%S')}")

    ctx = _AppContext()

    try:
        # Solicitar mes y año al inicio
        ctx.ensure_params()

        while True:
            _print_menu()
            choice = input("\n🔹 Seleccione una opción: ").strip()

            if choice == "0":
                print("\n👋 ¡Hasta luego!")
                break

            if choice not in _MENU_OPTIONS:
                print("  ⚠️  Opción inválida. Intente de nuevo.")
                continue

            desc, func = _MENU_OPTIONS[choice]
            if func is None:
                break

            task_start = datetime.now()
            task_start_ts = time.perf_counter()

            print(f"\n{'─'*60}")
            print(f"▶️  Ejecutando: {desc}")
            print(f"🕐 Inicio: {task_start.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'─'*60}")

            try:
                func(ctx)
            except KeyboardInterrupt:
                print("\n\n⚠️  Operación interrumpida por el usuario.")
            except Exception as e:
                print(f"\n❌ Error inesperado: {e}")

            task_end = datetime.now()
            task_elapsed = time.perf_counter() - task_start_ts

            print(f"\n{'─'*60}")
            print(f"✅ Opción [{choice}] finalizada.")
            print(f"🕐 Inicio:             {task_start.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"🕐 Fin:                {task_end.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"⏱️  Tiempo transcurrido: {_format_elapsed(task_elapsed)}")
            print(f"{'─'*60}")
    finally:
        session_end = datetime.now()
        session_elapsed = (session_end - session_start).total_seconds()
        print(f"\n{'='*60}")
        print(f"📊 RESUMEN DE SESIÓN")
        print(f"{'='*60}")
        print(f"🕐 Inicio de sesión:   {session_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🕐 Fin de sesión:      {session_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️  Tiempo total:       {_format_elapsed(session_elapsed)}")
        print(f"{'='*60}")
        _teardown_logging(log_file, log_path)


if __name__ == "__main__":
    main()
