"""
Módulo para la entrada de parámetros por consola.
Utilizado por main.py para solicitar mes y año de forma interactiva.
"""


def ask_params() -> tuple[int, int | None]:
    """Solicita mes y año por consola de forma interactiva."""
    while True:
        mes_input = input("📅 Ingrese el mes a consultar (1-12): ").strip()
        if mes_input.isdigit() and 1 <= int(mes_input) <= 12:
            mes = int(mes_input)
            break
        print("  ⚠️  Mes inválido. Debe ser un número entre 1 y 12.")

    anio_input = input("📅 Ingrese el año (Enter para año actual): ").strip()
    anio: int | None = None
    if anio_input:
        if anio_input.isdigit() and int(anio_input) >= 2000:
            anio = int(anio_input)
        else:
            print("  ⚠️  Año inválido. Se usará el año actual.")

    return mes, anio

