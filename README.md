# 📊 Report QPU Support

Herramienta CLI interactiva para generar reportes de KPIs de uso de la plataforma **Visma QPU**.  
Extrae datos de múltiples bases de datos (MySQL Performance, MySQL Logs, MongoDB), procesa queries definidas en un archivo CSV y exporta un reporte consolidado por empresa.

---

## 📋 Tabla de contenidos

- [Requisitos previos](#-requisitos-previos)
- [Instalación](#-instalación)
- [Configuración](#-configuración)
- [Ejecución](#-ejecución)
- [Menú principal](#-menú-principal)
- [Flujo completo paso a paso](#-flujo-completo-paso-a-paso)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [Archivo de queries (query.csv)](#-archivo-de-queries-querycsv)
- [Placeholders de fecha](#-placeholders-de-fecha)
- [Flujo de Steps (Step_1 → Step_2)](#-flujo-de-steps-step_1--step_2)
- [Bases de datos utilizadas](#-bases-de-datos-utilizadas)
- [Archivos de salida](#-archivos-de-salida)
- [Ejemplo de ejecución](#-ejemplo-de-ejecución)
- [Solución de problemas](#-solución-de-problemas)

---

## 🔧 Requisitos previos

| Requisito     | Versión mínima |
|---------------|----------------|
| **Python**    | 3.12+          |
| **pip**       | 23.0+          |
| Acceso a **MySQL** (Performance y Logs) | — |
| Acceso a **MongoDB** (Analytics) | — |

---

## 📦 Instalación

```bash
# 1. Clonar o descargar el proyecto
cd report_qpu_support

# 2. Crear un entorno virtual (recomendado)
python -m venv venv

# Windows PowerShell
.\venv\Scripts\Activate.ps1

# Linux / macOS
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

### Dependencias (`requirements.txt`)

| Paquete                    | Uso                                      |
|----------------------------|------------------------------------------|
| `mysql-connector-python`   | Conexión a MySQL (Performance y Logs)    |
| `pymongo`                  | Conexión a MongoDB (Analytics / Social)  |
| `python-dotenv`            | Carga de variables de entorno desde `.env` |
| `python-dateutil`          | Cálculo de rangos de fecha con `relativedelta` |
| `pandas` *(implícito)*     | Lectura/escritura de CSV, consolidación  |

> **Nota:** `pandas` se usa en el código pero no está en `requirements.txt`. Si falta, instálelo:
> ```bash
> pip install pandas
> ```

---

## ⚙️ Configuración

Cree un archivo **`.env`** en la raíz del proyecto con las credenciales de cada base de datos:

```env
# ── MySQL Principal (Performance) ──────────────────────
MYSQL_MAIN_HOST=your-performance-host.com
MYSQL_MAIN_PORT=3306
MYSQL_MAIN_USER=your_user
MYSQL_MAIN_PASSWORD=your_password
MYSQL_MAIN_DATABASE=performance

# ── MySQL Logs ─────────────────────────────────────────
MYSQL_LOGS_HOST=your-logs-host.com
MYSQL_LOGS_PORT=3307
MYSQL_LOGS_USER=your_user
MYSQL_LOGS_PASSWORD=your_password
MYSQL_LOGS_DATABASE=logs

# ── MongoDB (Analytics / Social) ──────────────────────
MONGO_HOST=your-mongo-host.com
MONGO_PORT=27017
MONGO_USER=your_user
MONGO_PASSWORD=your_password
MONGO_DATABASE=your_database
MONGO_AUTH_SOURCE=admin
```

> ⚠️ **Nunca suba el archivo `.env` al repositorio.** Agregue `.env` a su `.gitignore`.

---

## 🚀 Ejecución

```bash
python main.py
```

Al iniciar, el programa solicita:

```
📅 Ingrese el mes a consultar (1-12): 2
📅 Ingrese el año (Enter para año actual): 2026
```

Luego se presenta el **menú interactivo**.

---

## 📋 Menú principal

```
============================================================
📋 MENÚ PRINCIPAL — Report QPU Support
============================================================
  ▶️ [1] Probar conectividad a las bases de datos
  ▶️ [2] Obtener listado maestro de empresas
  ▶️ [3] Exportar logs del período (mes por mes)
  ▶️ [4] Consolidar logs en un solo CSV
  ▶️ [5] Ejecutar queries del CSV (KPIs)
  ▶️ [6] Exportar reporte consolidado a CSV
  ▶️ [7] Ejecutar todo (flujo completo)
  🚪 [0] Salir
============================================================
```

| Opción | Descripción | Depende de |
|--------|-------------|------------|
| **1** | Prueba la conectividad a MySQL Performance, MySQL Logs y MongoDB | — |
| **2** | Obtiene el listado maestro de empresas activas desde MySQL Performance | — |
| **3** | Exporta logs de la BD de Logs mes por mes (3 meses atrás → mes actual) usando workers paralelos | Opción 2 |
| **4** | Consolida todos los CSV de logs mensuales en un solo archivo | Opción 3 (o archivos previos en disco) |
| **5** | Ejecuta las queries del archivo `input/query.csv` y calcula los KPIs por empresa. **Permite seleccionar secciones específicas.** | Opción 2. Usa opción 4 si está disponible |
| **6** | Exporta el reporte final con empresas × KPIs a un CSV en `output/` | Opciones 2 y 5 |
| **7** | **Ejecuta todo el flujo completo** (opciones 1→2→3→4→5→6 en secuencia) | — |

---

## 🔄 Flujo completo paso a paso

### Opción 7 — Ejecutar todo

```
[1] Probar conectividad
 ↓
[2] Obtener empresas maestras (MySQL Performance)
 ↓
[3] Exportar logs mes por mes (MySQL Logs → CSV por mes)
 │   └─ output/2025/logs_Octubre_2025.csv
 │   └─ output/2025/logs_Noviembre_2025.csv
 │   └─ output/2025/logs_Diciembre_2025.csv
 │   └─ output/2026/logs_Febrero_2026.csv
 ↓
[4] Consolidar en un solo CSV
 │   └─ output/logs_consolidado_Octubre_2025_a_Febrero_2026.csv
 ↓
[5] Ejecutar queries del CSV (KPIs)
 │   ├─ Sección COLABORADORES → queries simples contra Performance
 │   ├─ Sección LOGIN 3 MESES → Step_1 desde CSV consolidado + Step_2 contra Performance
 │   ├─ Sección LOGIN ÚLTIMO MES → Step_1 desde CSV consolidado + Step_2 contra Performance
 │   ├─ Sección ENGAGEMENT → queries simples contra Performance
 │   └─ Sección SOCIAL → Step_1 MySQL + Step_2 MongoDB
 ↓
[6] Exportar reporte
     └─ output/report_Febrero_2026.csv
```

---

## 📁 Estructura del proyecto

```
report_qpu_support/
│
├── main.py                          # Punto de entrada — Menú interactivo y lógica principal
├── requirements.txt                 # Dependencias Python
├── .env                             # Variables de entorno (NO versionar)
├── README.md                        # Este archivo
│
├── config/
│   ├── __init__.py                  # Exporta las clases de configuración
│   ├── settings.py                  # Configuración de BD (lee .env)
│   └── queries.py                   # Query maestro de empresas (COMPANIES_QUERY)
│
├── db/
│   ├── __init__.py                  # Exporta conexiones y ejecutores
│   ├── connections.py               # Clases de conexión: MySQLMainConnection,
│   │                                #   MySQLLogsConnection, MongoConnection
│   └── executors.py                 # MySQLQueryExecutor, MongoQueryExecutor
│
├── services/
│   ├── __init__.py                  # Exporta servicios
│   ├── connection_tester.py         # Prueba conectividad a las 3 bases de datos
│   ├── date_handler.py              # Cálculo de rangos de fecha (1m, 3m, 6m)
│   ├── input_handler.py             # Solicita mes/año por consola
│   └── query_processor.py           # Lee query.csv, reemplaza placeholders,
│                                    #   expone queries listas para ejecución
│
├── input/
│   └── query.csv                    # Archivo de definición de KPIs y queries
│
└── output/                          # Archivos generados (auto-creado)
    ├── 2025/
    │   ├── logs_Octubre_2025.csv
    │   ├── logs_Noviembre_2025.csv
    │   └── logs_Diciembre_2025.csv
    ├── 2026/
    │   ├── logs_Enero_2026.csv
    │   └── logs_Febrero_2026.csv
    ├── logs_consolidado_Octubre_2025_a_Febrero_2026.csv
    └── report_Febrero_2026.csv
```

---

## 📄 Archivo de queries (`query.csv`)

El archivo `input/query.csv` define los KPIs a calcular. Usa **pipe (`|`)** como delimitador y tiene 6 columnas:

| Columna | Campo     | Descripción |
|---------|-----------|-------------|
| C1      | **KPIs**    | Nombre del KPI (vacío = fila de encabezado de sección) |
| C2      | **Origin**  | Base de datos destino: `performance`, `logs`, `performance-social` |
| C3      | **Query**   | Query SQL principal (ejecuta contra C2) |
| C4      | **Step_1**  | Query previa para obtener `user_ids` (generalmente en `logs`) |
| C5      | **Step_2**  | Query que usa `{user_ids}` del Step_1 (generalmente en `performance`) |
| C6      | **Title**   | Título de sección/agrupación |

### Ejemplo de fila

```
KPIs|Origin|Query|Step_1|Step_2|Title
""|performance||||COLABORADORES
TOTAL DE LÍDERES|performance|select c.id, ... |||COLABORADORES
""|logs||select distinct ... from logs where ...||LOGIN 3 MESES
ADMINISTRADORES|performance|select ... |  |select ... where u.id in ({user_ids}) ...|LOGIN 3 MESES
```

### Tipos de filas

| Tipo | C1 | C3 (Query) | C4 (Step_1) | C5 (Step_2) | Comportamiento |
|------|-----|------------|-------------|-------------|----------------|
| **Encabezado** | vacío | — | — | — | Marca inicio de sección, resetea `user_ids` |
| **Query simple** | ✓ | ✓ | — | — | Ejecuta C3 contra la BD indicada en C2 |
| **Proveedor de IDs** | — | — | ✓ | — | Ejecuta Step_1, guarda `user_ids` para filas siguientes |
| **Step_2 dependiente** | ✓ | — | — | ✓ | Usa `{user_ids}` previos, ejecuta C5 contra Performance |
| **Query + Step_2** | ✓ | ✓ | — | ✓ | Ejecuta C3 + C5 y **suma** ambos resultados |
| **Performance-Social** | ✓ | — | ✓ | ✓ | Step_1 en MySQL → Step_2 como pipeline en MongoDB |

---

## 📅 Placeholders de fecha

Las queries en `query.csv` usan placeholders que se reemplazan dinámicamente según el mes/año ingresado:

| Placeholder           | Significado | Ejemplo (Febrero 2026) |
|-----------------------|-------------|------------------------|
| `{fecha_inicio}`      | Primer día del mes seleccionado (1 mes) | `2026-02-01` |
| `{fecha_fin}`         | Último día del mes seleccionado | `2026-02-28` |
| `{fecha_inicio_3m}`   | 3 meses atrás desde el mes seleccionado | `2025-11-01` |
| `{fecha_inicio_6m}`   | 6 meses atrás desde el mes seleccionado | `2025-08-01` |
| `{user_ids}`          | Lista de IDs de usuario obtenidos de un Step_1 previo | `101,205,309,...` |

---

## 🔗 Flujo de Steps (Step_1 → Step_2)

Algunas filas del CSV usan un mecanismo de dos pasos:

```
┌─────────────────────────────────────────────────────────┐
│  Step_1 (Proveedor de IDs)                              │
│  - Se ejecuta en MySQL Logs o se lee del CSV consolidado│
│  - Filtra por mensajes: 'Cambiar de usuario',           │
│    'Cambiar de plataforma'                              │
│  - Filtra por rango de fechas (1m o 3m)                 │
│  - Retorna lista de users_id distintos                  │
└──────────────────┬──────────────────────────────────────┘
                   │ user_ids
                   ▼
┌─────────────────────────────────────────────────────────┐
│  Step_2 / Query+Step_2 (Dependiente)                    │
│  - Inyecta {user_ids} en la query                       │
│  - Se ejecuta en MySQL Performance                      │
│  - Retorna conteos por empresa                          │
└─────────────────────────────────────────────────────────┘
```

> **Optimización:** Si existe el CSV consolidado de logs (`output/logs_consolidado_*.csv`), el Step_1 se resuelve leyendo el CSV local en vez de consultar la BD de logs, lo cual es significativamente más rápido.

---

## 🗄️ Bases de datos utilizadas

### MySQL Performance (principal)

| Aspecto | Detalle |
|---------|---------|
| **Propósito** | Datos de empresas, usuarios, sesiones, módulos |
| **BD** | `performance` |
| **Tablas clave** | `companies`, `users`, `sessions`, `user_roles`, `teams_collaborators` |
| **Usado en** | Query maestro de empresas, queries simples de KPIs, Step_2 |

### MySQL Logs

| Aspecto | Detalle |
|---------|---------|
| **Propósito** | Registros de actividad (login, cambio de usuario/plataforma) |
| **BD** | `logs` |
| **Tablas clave** | `logs` (date, users_id, message, companies_id) |
| **Usado en** | Exportación de logs (opción 3), Step_1 (obtener user_ids) |

### MongoDB (Analytics / Social)

| Aspecto | Detalle |
|---------|---------|
| **Propósito** | Datos de funcionalidades sociales (reacciones, grupos) |
| **Colecciones** | `reactions`, `groups` |
| **Usado en** | Step_2 de filas `performance-social` (pipelines de agregación) |

---

## 📤 Archivos de salida

Todos los archivos se generan en la carpeta `output/`:

| Archivo | Generado por | Contenido |
|---------|-------------|-----------|
| `output/{año}/logs_{Mes}_{Año}.csv` | Opción 3 | Logs crudos de un mes específico |
| `output/logs_consolidado_{MesIni}_{AñoIni}_a_{MesFin}_{AñoFin}.csv` | Opción 4 | Logs de los últimos 3-4 meses unificados |
| `output/report_{Mes}_{Año}.csv` | Opción 6 | **Reporte final** con columnas: `empresa_id`, `empresa_nombre`, `hubspot_id`, y una columna por cada KPI |

### Formato del reporte final

```csv
empresa_id,empresa_nombre,hubspot_id,COLABORADORES - TOTAL DE LÍDERES,COLABORADORES - TOTAL DE COLABORADORES,...
123,Empresa ABC,hs_001,15,120,...
456,Empresa XYZ,hs_002,8,85,...
```

---

## 💻 Ejemplo de ejecución

### Flujo completo (opción 7)

```powershell
python main.py
```

```
📅 Ingrese el mes a consultar (1-12): 2
📅 Ingrese el año (Enter para año actual): 2026

📅 Mes seleccionado: Febrero 2026
   1 mes:   2026-02-01 → 2026-02-28
   3 meses: 2025-11-01 → 2026-02-28
   6 meses: 2025-08-01 → 2026-02-28

🔹 Seleccione una opción: 7
```

### Solo ejecutar KPIs (opción 5)

Si ya tiene los logs exportados y consolidados de una sesión anterior:

```powershell
python main.py
```

```
📅 Ingrese el mes a consultar (1-12): 2
📅 Ingrese el año (Enter para año actual): 2026

🔹 Seleccione una opción: 5
```

La opción 5 **auto-detecta** el CSV consolidado en disco si existe, sin necesidad de ejecutar las opciones 3 y 4 nuevamente.

#### Selección de secciones (KPIs)

Al elegir la opción **5** se muestra un sub-menú con todas las secciones del archivo `query.csv`:

```
=================================================================
📋 SECCIONES DISPONIBLES EN query.csv
=================================================================
  [ 1] COLABORADORES  (2 KPIs)
        • COLABORADORES - TOTAL DE LÍDERES
        • COLABORADORES - TOTAL DE COLABORADORES
  [ 2] LOGIN 3 MESES 🔗  (4 KPIs)
        🔗 (proveedor de IDs)
        • LOGIN 3 MESES - ADMINISTRADORES
        • LOGIN 3 MESES - BUSINESS PARTNERS
        • LOGIN 3 MESES - LÍDERES
        • LOGIN 3 MESES - COLABORADORES
  [ 3] LOGIN ÚLTIMO MES 🔗  (4 KPIs)
        ...
  [ 4] REPORTES ULTIMO MES 🔗  (1 KPIs)
        ...
  [ 5] USUARIOS ASIGNADOS  (4 KPIs)
        ...
  ...
  [ A] Ejecutar TODAS las secciones
=================================================================

🔹 Seleccione secciones (ej: 1,3,5  o  2-6  o  A para todas):
```

**Formatos de selección soportados:**

| Entrada | Resultado |
|---------|-----------|
| `A` o Enter | Ejecuta **todas** las secciones |
| `1` | Solo la sección 1 (COLABORADORES) |
| `1,3,5` | Secciones 1, 3 y 5 |
| `2-6` | Secciones 2, 3, 4, 5 y 6 |
| `1,3-5,8` | Secciones 1, 3, 4, 5 y 8 |

**Comportamiento:**

- Las secciones **seleccionadas** se ejecutan normalmente contra las bases de datos.
- Las secciones **no seleccionadas** generan sus columnas KPI con **valor 0**, pero **mantienen su posición** en el CSV de salida.
- Esto permite re-ejecutar solo las secciones que fallaron o que necesitan actualizarse, sin perder la estructura del reporte.
- Los proveedores de IDs (`🔗`) se ejecutan automáticamente si su sección está seleccionada.
- La opción **7** (flujo completo) ejecuta todas las secciones sin preguntar.

### Solo probar conexiones (opción 1)

```powershell
python main.py
```

```
🔹 Seleccione una opción: 1

🔌 Probando conexiones...

  ✅ MySQL Principal (performance): conexión exitosa
  ✅ MySQL Logs (logs): conexión exitosa
  ✅ MongoDB (main): conexión exitosa

✅ Resultado: 3/3 conexiones exitosas.
```

---

## 🐛 Solución de problemas

### "CSV consolidado NO disponible"

```
📂 Fuente de datos para Step_1 (origin=logs):
   ⚠️  CSV consolidado NO disponible → Se consultará la BD de logs directamente
```

**Causa:** No se ejecutó la opción 4 (Consolidar logs) y no existe un archivo `logs_consolidado_*.csv` previo en `output/`.

**Solución:**
- Ejecute la opción **4** antes de la **5**, o
- Use la opción **7** (flujo completo), o
- Si ya tiene los CSV mensuales en `output/{año}/`, ejecute solo la opción **4** y luego **5**

### Error de conexión a MySQL Logs

```
⚠️  MySQL Logs: NO disponible — Can't connect to MySQL server
```

**Causa:** Las credenciales en `.env` son incorrectas o el servidor no es accesible.

**Impacto:** Los Step_1 que dependen de la BD de logs intentarán usar el CSV consolidado como fallback. Si tampoco existe el CSV, esos KPIs quedarán en 0.

### Error de conexión a MongoDB

```
⚠️  MongoDB: NO disponible — ...
```

**Impacto:** Las filas con `origin=performance-social` (KPIs sociales como reacciones y grupos) se omitirán y quedarán en 0.

### "No se obtuvieron empresas del query maestro"

**Causa:** La conexión a MySQL Performance falló o no hay empresas que cumplan los filtros del query maestro (`active=1`, `is_demo=0`, etc.).

**Solución:** Verifique la conexión con la opción **1** y revise las credenciales en `.env`.

### El mes ingresado da resultados vacíos

**Causa:** El mes/año seleccionado puede estar en el futuro o no existir data para ese período.

**Solución:** Verifique que existen registros en las bases de datos para el rango de fechas esperado.

---

## 📐 Parámetros de configuración en `main.py`

| Constante | Valor por defecto | Descripción |
|-----------|-------------------|-------------|
| `LOGS_CHUNK_SIZE` | `25000` | Registros por chunk al exportar logs desde la BD |
| `LOGS_MAX_WORKERS` | `4` | Workers paralelos para descarga de logs |
| `USER_IDS_CHUNK_SIZE` | `5000` | IDs por chunk en `WHERE IN ({user_ids})` para evitar queries pesadas |
| `USER_IDS_MAX_WORKERS` | `4` | Workers paralelos para ejecutar Step_2 / queries con user_ids particionados |
| `CSV_READ_CHUNK_SIZE` | `50000` | Filas por chunk al leer el CSV consolidado de logs |
| `CSV_READ_MAX_WORKERS` | `4` | Workers paralelos para procesar chunks del CSV consolidado |
| `CSV_PATH` | `input/query.csv` | Ruta al archivo de definición de KPIs |
| `OUTPUT_DIR` | `output/` | Directorio de salida de archivos generados |

---

## 📝 Notas adicionales

- El **orden de las empresas** en el reporte final corresponde al orden alfabético por nombre (`ORDER BY c.name`) definido en el query maestro.
- Las filas del CSV se procesan en orden secuencial. Los `user_ids` obtenidos por un Step_1 se mantienen vigentes hasta el siguiente encabezado de sección.
- Si un KPI retorna 0 para una empresa, significa que no se encontraron datos o que hubo un error en esa query específica.
- La herramienta es **idempotente**: ejecutar varias veces con el mismo mes/año sobrescribe los archivos de salida existentes.

