"""
Módulo para el manejo de rangos de fecha dinámicos.
Calcula fecha_inicio y fecha_fin a partir de un mes (y opcionalmente año).
Soporta intervalos de 1, 3 y 6 meses hacia atrás desde el mes indicado.
"""

import calendar
from datetime import date
from dateutil.relativedelta import relativedelta


class DateHandler:
    """Calcula el rango de fechas basado en el mes y año ingresados."""

    MESES = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }

    def __init__(self, month: int, year: int | None = None):
        if not 1 <= month <= 12:
            raise ValueError(f"El mes debe estar entre 1 y 12. Recibido: {month}")

        self.year = year or date.today().year
        self.month = month
        last_day = calendar.monthrange(self.year, self.month)[1]
        self.start_date = date(self.year, self.month, 1)
        self.end_date = date(self.year, self.month, last_day)

    @property
    def fecha_inicio(self) -> str:
        """Retorna el primer día del mes indicado (intervalo 1 mes)."""
        return self.start_date.strftime("%Y-%m-%d")

    @property
    def fecha_inicio_3m(self) -> str:
        """Retorna la fecha 3 meses antes del inicio del mes indicado.
        Ej: mes=1 (enero 2026) → 2025-10-01 (octubre del año anterior)."""
        d = self.start_date - relativedelta(months=3)
        return date(d.year, d.month, 1).strftime("%Y-%m-%d")

    @property
    def fecha_inicio_6m(self) -> str:
        """Retorna la fecha 6 meses antes del inicio del mes indicado.
        Ej: mes=6 (junio 2026) → 2025-12-01."""
        d = self.start_date - relativedelta(months=6)
        return date(d.year, d.month, 1).strftime("%Y-%m-%d")

    @property
    def fecha_fin(self) -> str:
        """Retorna el último día del mes indicado."""
        return self.end_date.strftime("%Y-%m-%d")

    @property
    def fecha_fin_datetime(self) -> str:
        """Retorna la fecha de fin con hora 23:59:59."""
        return f"{self.end_date.strftime('%Y-%m-%d')} 23:59:59"

    @property
    def nombre_mes(self) -> str:
        """Retorna el nombre del mes en español."""
        return self.MESES[self.month]

    def __repr__(self) -> str:
        return (
            f"DateHandler(mes={self.month} [{self.nombre_mes}], "
            f"año={self.year}, "
            f"1m='{self.fecha_inicio}' → '{self.fecha_fin}', "
            f"3m='{self.fecha_inicio_3m}' → '{self.fecha_fin}', "
            f"6m='{self.fecha_inicio_6m}' → '{self.fecha_fin}')"
        )

