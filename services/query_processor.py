"""
Procesador de queries desde el archivo CSV.
Lee query.csv y reemplaza los placeholders de fecha y {user_ids}
con los valores calculados dinámicamente.

Placeholders soportados:
  - {fecha_inicio}    → Primer día del mes indicado (1 mes)
  - {fecha_inicio_3m} → 3 meses atrás desde el mes indicado
  - {fecha_inicio_6m} → 6 meses atrás desde el mes indicado
  - {fecha_fin}        → Último día del mes indicado
  - {user_ids}         → IDs de usuarios obtenidos de un Step_1 previo
"""

import csv
import os
from dataclasses import dataclass, field

from services.date_handler import DateHandler


PLACEHOLDER_USER_IDS = "{user_ids}"


@dataclass
class QueryRow:
    """Representa una fila del archivo query.csv.

    Los campos ``kpi``, ``origin``, ``query``, ``step_1``, ``step_2`` y
    ``title`` corresponden a las columnas obligatorias del CSV.
    El campo ``extras`` almacena cualquier columna adicional que se haya
    agregado al CSV (clave = nombre de la columna del header).
    """
    kpi: str
    origin: str
    query: str = ""
    step_1: str = ""
    step_2: str = ""
    title: str = ""
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Retorna el label concatenando Title (C6) y KPI (C1) cuando C1 tiene valor."""
        if self.kpi:
            return f"{self.title} - {self.kpi}" if self.title else self.kpi
        return self.title or ""

    @property
    def is_header(self) -> bool:
        """Indica si la fila es un encabezado de sección (sin query ni steps)."""
        return not self.query and not self.step_1 and not self.step_2

    @property
    def has_date_placeholders(self) -> bool:
        """Indica si alguna columna contiene placeholders de fecha."""
        combined = f"{self.query}{self.step_1}{self.step_2}"
        return (
            "{fecha_inicio}" in combined
            or "{fecha_inicio_3m}" in combined
            or "{fecha_inicio_6m}" in combined
            or "{fecha_fin}" in combined
        )

    @property
    def has_user_ids_placeholder(self) -> bool:
        """Indica si alguna columna necesita inyección de IDs de usuarios."""
        combined = f"{self.query}{self.step_1}{self.step_2}"
        return PLACEHOLDER_USER_IDS in combined


@dataclass
class QueryGroup:
    """Agrupa filas por secciones lógicas del CSV."""
    section: str
    rows: list[QueryRow] = field(default_factory=list)


class QueryProcessor:
    """
    Lee el archivo query.csv, reemplaza placeholders de fecha
    y expone las queries listas para ejecución.

    El parser es **dinámico**: mapea las columnas por nombre del header,
    no por posición fija.  Esto permite agregar columnas nuevas al CSV
    en cualquier posición sin romper la funcionalidad existente.

    Columnas obligatorias (deben existir en el header):
      - KPIs, Origin

    Columnas opcionales reconocidas:
      - Query, Step_1, Step_2, Title

    Cualquier otra columna se almacena en ``QueryRow.extras``.

    Flujo de Steps:
      - Step_1 se ejecuta en logs/otra DB y retorna IDs de usuarios.
      - Step_2 usa esos IDs en el placeholder {user_ids} para ejecutarse
        en performance.
    """

    PLACEHOLDER_START_1M = "{fecha_inicio}"
    PLACEHOLDER_START_3M = "{fecha_inicio_3m}"
    PLACEHOLDER_START_6M = "{fecha_inicio_6m}"
    PLACEHOLDER_END = "{fecha_fin}"

    # Nombres canónicos de las columnas del CSV (case-insensitive al mapear)
    _COL_KPI = "KPIs"
    _COL_ORIGIN = "Origin"
    _COL_QUERY = "Query"
    _COL_STEP1 = "Step_1"
    _COL_STEP2 = "Step_2"
    _COL_TITLE = "Title"

    # Columnas obligatorias — si faltan, se lanza un error claro
    _REQUIRED_COLUMNS = {_COL_KPI, _COL_ORIGIN}

    # Todas las columnas conocidas (las que se mapean a campos de QueryRow)
    _KNOWN_COLUMNS = {_COL_KPI, _COL_ORIGIN, _COL_QUERY, _COL_STEP1, _COL_STEP2, _COL_TITLE}

    def __init__(self, csv_path: str, date_handler: DateHandler):
        self._csv_path = csv_path
        self._date_handler = date_handler
        self._rows: list[QueryRow] = []
        self._col_map: dict[str, int] = {}        # nombre_columna → índice
        self._extra_columns: list[str] = []         # nombres de columnas no-conocidas

    # -------------------------------------------------------------------------
    # Helpers internos
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_column_map(header: list[str]) -> dict[str, int]:
        """Construye un mapeo nombre_columna → índice a partir del header.

        La búsqueda es **case-insensitive** y tolera espacios al inicio/final.
        Si hay nombres duplicados, gana el primero.
        """
        col_map: dict[str, int] = {}
        for idx, raw_name in enumerate(header):
            name = raw_name.strip()
            if not name:
                continue
            # Buscar coincidencia case-insensitive con las columnas conocidas
            matched = False
            for known in QueryProcessor._KNOWN_COLUMNS:
                if name.lower() == known.lower():
                    if known not in col_map:
                        col_map[known] = idx
                    matched = True
                    break
            if not matched:
                # Columna extra — guardar con su nombre original
                col_map[name] = idx
        return col_map

    def _get_col(self, row: list[str], col_name: str) -> str:
        """Obtiene el valor de una columna por nombre, retornando '' si no existe."""
        idx = self._col_map.get(col_name)
        if idx is None or idx >= len(row):
            return ""
        return row[idx].strip()

    def load(self) -> "QueryProcessor":
        """Carga y parsea el archivo CSV con mapeo dinámico de columnas.

        Lee la primera fila como header, construye un mapeo
        ``nombre_columna → índice`` y luego extrae cada campo por nombre.
        Columnas extra (no conocidas) se almacenan en ``QueryRow.extras``.
        """
        if not os.path.isfile(self._csv_path):
            raise FileNotFoundError(f"No se encontró el archivo: {self._csv_path}")

        self._rows = []
        with open(self._csv_path, encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="|")
            header = next(reader, None)
            if header is None:
                raise ValueError("El archivo CSV está vacío.")

            # Construir mapeo dinámico desde el header
            self._col_map = self._build_column_map(header)

            # Validar que las columnas obligatorias existan
            missing = self._REQUIRED_COLUMNS - set(self._col_map.keys())
            if missing:
                raise ValueError(
                    f"Faltan columnas obligatorias en el header del CSV: "
                    f"{', '.join(sorted(missing))}. "
                    f"Header encontrado: {[h.strip() for h in header]}"
                )

            # Detectar columnas extra (no conocidas)
            self._extra_columns = [
                name for name in self._col_map
                if name not in self._KNOWN_COLUMNS
            ]

            if self._extra_columns:
                print(f"   ℹ️  Columnas extra detectadas en el CSV: {self._extra_columns}")

            for row in reader:
                if not row or len(row) < 2:
                    continue

                # Saltar filas completamente vacías
                if all(not col.strip() for col in row):
                    continue

                # Extraer campos conocidos por nombre (no por índice fijo)
                kpi = self._get_col(row, self._COL_KPI)
                origin = self._get_col(row, self._COL_ORIGIN)
                query = self._get_col(row, self._COL_QUERY)
                step_1 = self._get_col(row, self._COL_STEP1)
                step_2 = self._get_col(row, self._COL_STEP2)
                title = self._get_col(row, self._COL_TITLE)

                # Extraer columnas extra
                extras: dict[str, str] = {}
                for extra_name in self._extra_columns:
                    val = self._get_col(row, extra_name)
                    if val:
                        extras[extra_name] = val

                self._rows.append(QueryRow(
                    kpi=kpi,
                    origin=origin,
                    query=query,
                    step_1=step_1,
                    step_2=step_2,
                    title=title,
                    extras=extras,
                ))
        return self

    # -------------------------------------------------------------------------
    # Propiedades de acceso
    # -------------------------------------------------------------------------

    @property
    def rows(self) -> list[QueryRow]:
        """Retorna todas las filas cargadas."""
        return self._rows

    @property
    def column_map(self) -> dict[str, int]:
        """Retorna el mapeo nombre_columna → índice construido desde el header."""
        return dict(self._col_map)

    @property
    def extra_columns(self) -> list[str]:
        """Retorna los nombres de columnas extra (no conocidas) detectadas en el CSV."""
        return list(self._extra_columns)

    @property
    def executable_rows(self) -> list[QueryRow]:
        """Retorna solo filas que tienen al menos una query/step ejecutable."""
        return [r for r in self._rows if not r.is_header]

    @property
    def date_segmentable_rows(self) -> list[QueryRow]:
        """Retorna solo filas que contienen placeholders de fecha."""
        return [r for r in self._rows if r.has_date_placeholders]

    # -------------------------------------------------------------------------
    # Reemplazo de placeholders
    # -------------------------------------------------------------------------

    def replace_dates(self, text: str) -> str:
        """Reemplaza los placeholders de fecha en un texto dado.
        Orden: primero los más específicos (3m, 6m) y luego el genérico (1m),
        para evitar reemplazos parciales."""
        if not text:
            return text
        return (
            text
            .replace(self.PLACEHOLDER_START_3M, self._date_handler.fecha_inicio_3m)
            .replace(self.PLACEHOLDER_START_6M, self._date_handler.fecha_inicio_6m)
            .replace(self.PLACEHOLDER_START_1M, self._date_handler.fecha_inicio)
            .replace(self.PLACEHOLDER_END, self._date_handler.fecha_fin)
        )

    @staticmethod
    def inject_user_ids(text: str, user_ids: list[int | str]) -> str:
        """Reemplaza {user_ids} por la lista de IDs separados por coma.

        Todos los IDs se convierten a enteros (sin decimales) antes de inyectarlos.

        Ejemplo:
            inject_user_ids("u.id in ( {user_ids} )", [10, 20, 30])
            → "u.id in ( 10,20,30 )"
        """
        if not text or PLACEHOLDER_USER_IDS not in text:
            return text
        int_ids: list[str] = []
        for uid in user_ids:
            try:
                int_ids.append(str(int(float(uid))))
            except (ValueError, TypeError):
                int_ids.append(str(uid))
        ids_str = ",".join(int_ids)
        return text.replace(PLACEHOLDER_USER_IDS, ids_str)

    # -------------------------------------------------------------------------
    # Procesamiento de queries
    # -------------------------------------------------------------------------

    def get_processed_query(self, row: QueryRow, user_ids: list[int | str] | None = None) -> str:
        """Retorna la query principal con fechas y user_ids reemplazados."""
        text = self.replace_dates(row.query)
        if user_ids is not None:
            text = self.inject_user_ids(text, user_ids)
        return text

    def get_processed_step1(self, row: QueryRow) -> str:
        """Retorna Step_1 con fechas reemplazadas.
        Step_1 nunca necesita user_ids (es quien los provee)."""
        return self.replace_dates(row.step_1)

    def get_processed_step2(self, row: QueryRow, user_ids: list[int | str] | None = None) -> str:
        """Retorna Step_2 con fechas y user_ids reemplazados.

        Args:
            row: La fila del CSV.
            user_ids: Lista de IDs obtenidos previamente del Step_1
                      de la fila proveedora correspondiente.
        """
        text = self.replace_dates(row.step_2)
        if user_ids is not None:
            text = self.inject_user_ids(text, user_ids)
        return text

    # -------------------------------------------------------------------------
    # Resumen
    # -------------------------------------------------------------------------

    def print_summary(self) -> None:
        """Imprime un resumen del procesamiento de queries."""
        total = len(self._rows)
        headers = sum(1 for r in self._rows if r.is_header)
        executable = len(self.executable_rows)
        segmentable = len(self.date_segmentable_rows)
        with_user_ids = sum(1 for r in self._rows if r.has_user_ids_placeholder)
        dh = self._date_handler

        print(f"\n📄 Archivo: {self._csv_path}")
        print(f"🗂️  Mapeo dinámico de columnas:")
        for col_name, col_idx in sorted(self._col_map.items(), key=lambda x: x[1]):
            marker = " ✅" if col_name in self._KNOWN_COLUMNS else " 🆕"
            print(f"   [{col_idx}] {col_name}{marker}")
        if self._extra_columns:
            print(f"   Columnas extra: {self._extra_columns}")
        print(f"📅 Rangos de fecha calculados ({dh.nombre_mes} {dh.year}):")
        print(f"   1 mes:   {dh.fecha_inicio} → {dh.fecha_fin}")
        print(f"   3 meses: {dh.fecha_inicio_3m} → {dh.fecha_fin}")
        print(f"   6 meses: {dh.fecha_inicio_6m} → {dh.fecha_fin}")
        print(f"📊 Total filas: {total}")
        print(f"   🏷️  Encabezados/secciones: {headers}")
        print(f"   ⚙️  Queries ejecutables: {executable}")
        print(f"   📅 Queries con fecha dinámica: {segmentable}")
        print(f"   🔗 Queries con {{user_ids}} (dependen de Step_1): {with_user_ids}")

        if segmentable > 0:
            print(f"\n📅 Queries segmentadas por fecha ({dh.nombre_mes} {dh.year}):")
            for row in self.date_segmentable_rows:
                dep = " 🔗" if row.has_user_ids_placeholder else ""
                print(f"   • [{row.origin}] {row.label}{dep}")
