# 📊 Guía Detallada de Consultas — Reporte QPU Support

> **¿Qué es este documento?**
> Este documento explica, paso a paso y en lenguaje sencillo, qué información obtiene cada consulta del archivo `query.csv` y qué filtros aplica para obtener esa información. Está pensado para personas que **no** necesitan saber programación.

---

## 📌 Índice

1. [Conceptos generales](#conceptos-generales)
2. [Filtros comunes a casi todas las consultas](#filtros-comunes)
3. [Sección 1 — COLABORADORES (Conteo total)](#sección-1--colaboradores-conteo-total)
4. [Sección 2 — LOGIN 3 MESES](#sección-2--login-3-meses)
5. [Sección 3 — LOGIN ÚLTIMO MES](#sección-3--login-último-mes)
6. [Sección 4 — REPORTES ÚLTIMO MES](#sección-4--reportes-último-mes)
7. [Sección 5 — USUARIOS ASIGNADOS](#sección-5--usuarios-asignados)
8. [Sección 6 — EVALUACIONES ÚLTIMOS 6 MESES](#sección-6--evaluaciones-últimos-6-meses)
9. [Sección 7 — FEEDBACK EN SU ÚLTIMA EVALUACIÓN OFICIALIZADA](#sección-7--feedback-en-su-última-evaluación-oficializada)
10. [Sección 8 — PERIODO ACTIVO](#sección-8--periodo-activo)
11. [Sección 9 — ÚLTIMO PERIODO](#sección-9--último-periodo)
12. [Sección 10 — ÚLTIMA EVALUACIÓN / ÚLTIMA REVISIÓN](#sección-10--última-evaluación--última-revisión)
13. [Sección 11 — PLANES DE DESARROLLO](#sección-11--planes-de-desarrollo)
14. [Sección 12 — ALCANCE (Módulos contratados)](#sección-12--alcance-módulos-contratados)
15. [Sección 13 — USO EN SOCIAL](#sección-13--uso-en-social)
16. [Sección 14 — PERSONALIZADO](#sección-14--personalizado)

---

## Conceptos generales

### ¿Qué tipos de usuarios existen?
La plataforma maneja **4 roles de usuario**, cada uno con un número identificador:

| Rol | ID | Descripción sencilla |
|---|---|---|
| **Administrador** | 1 | Persona de Recursos Humanos que gestiona la plataforma |
| **Business Partner (BP)** | 2 | Socio de negocio, rol intermedio entre RRHH y los equipos |
| **Líder** | 3 | Jefe directo de un equipo de personas |
| **Colaborador** | 4 | Empleado que no tiene personas a cargo |

### ¿Qué bases de datos se consultan?
- **`performance`** → Base de datos principal de la plataforma (MySQL). Contiene empresas, usuarios, evaluaciones, objetivos, etc.
- **`logs`** → Base de datos de registros de actividad (MySQL). Guarda cada acción que los usuarios hacen en la plataforma.
- **`csv-logs`** → Similar a logs pero se exporta en CSV.
- **`performance-social`** → Combina datos de la base principal con una base de datos MongoDB para la funcionalidad "Social".

### ¿Qué significan las fechas dinámicas?
Las consultas usan "comodines" de fechas que se reemplazan automáticamente al ejecutar el reporte:

| Comodín | Significado |
|---|---|
| `{fecha_inicio}` | Primer día del mes que se está reportando |
| `{fecha_fin}` | Último día del mes que se está reportando |
| `{fecha_inicio_3m}` | Primer día de hace 3 meses (para medir actividad trimestral) |
| `{fecha_inicio_6m}` | Primer día de hace 6 meses (para medir actividad semestral) |

---

## Filtros comunes

> ⚠️ **Casi todas las consultas aplican estos mismos filtros sobre las empresas.** Esto garantiza que solo se obtengan datos de clientes reales.

| # | Filtro | ¿Qué significa en español? |
|---|---|---|
| 1 | La empresa debe estar **activa** | Solo se incluyen empresas que están actualmente usando la plataforma (no dadas de baja) |
| 2 | La empresa **NO** es de demostración | Se excluyen las cuentas creadas solo para mostrar la plataforma a posibles clientes |
| 3 | El nombre **NO** contiene "QA" | Se excluyen cuentas usadas para pruebas internas de calidad |
| 4 | El nombre **NO** contiene "Demo" | Se excluyen cuentas de demostración identificadas por nombre |
| 5 | El nombre **NO** contiene "Ronald" | Se excluye una cuenta específica de pruebas |
| 6 | La empresa **tiene** un ID de HubSpot | Solo empresas registradas en el CRM de ventas (HubSpot), es decir, clientes reales |

**Resultado:** Solo aparecen empresas que son clientes reales y activos.

Adicionalmente, en muchas consultas de login y reportes, se excluyen usuarios de soporte:
| Filtro | ¿Qué significa? |
|---|---|
| El email **NO** sigue el patrón `soporte...@visma.com` | Se excluyen las sesiones generadas por el equipo de soporte de Visma, ya que no son uso real del cliente |

---

## Sección 1 — COLABORADORES (Conteo total)

### 1.1 📋 TOTAL DE LÍDERES

**¿Qué obtiene?** La cantidad de líderes activos en cada empresa.

**Filtros paso a paso:**
1. Se toman todas las empresas reales y activas *(filtros comunes)*.
2. Para cada empresa, se buscan personas en la tabla de equipos (`teams_collaborators`).
3. Se verifica que cada persona:
   - ✅ Esté **activa** como colaborador en el equipo (status = activo).
   - ✅ Tenga un **usuario** activo en la plataforma.
   - ✅ Tenga el **rol de Líder** (rol 3) asignado y activo.
4. Se cuentan personas **únicas** (sin duplicados).

---

### 1.2 📋 TOTAL DE COLABORADORES

**¿Qué obtiene?** La cantidad total de líderes + colaboradores activos en cada empresa.

**Filtros paso a paso:**
1. Mismos filtros comunes de empresa.
2. Se buscan personas en equipos que:
   - ✅ Estén **activas** en el equipo.
   - ✅ Tengan **usuario** activo.
   - ✅ Tengan rol de **Líder (3) o Colaborador (4)** activo.
3. Se cuentan personas únicas.

> 💡 **Diferencia con el anterior:** Este KPI incluye tanto líderes como colaboradores, no solo líderes.

---

## Sección 2 — LOGIN 3 MESES

> **Objetivo:** Medir cuántas personas de cada rol han ingresado a la plataforma en los últimos 3 meses.

### 2.0 🔍 Paso previo: Detección de cambio de usuario/plataforma

**¿Qué obtiene?** Una lista de IDs de usuarios que hicieron "Cambiar de usuario" o "Cambiar de plataforma" en los últimos 3 meses.

**Filtros:**
1. Se busca en la tabla de **logs** (registros de actividad).
2. Solo registros donde la acción sea:
   - `"Cambiar de usuario"`, o
   - `"Cambiar de plataforma"`.
3. La fecha del registro debe estar **entre hace 3 meses y hoy**.
4. Se obtienen usuarios **únicos**.

> 💡 **¿Para qué sirve esto?** Estos usuarios se usan en un segundo paso para descontarlos, ya que "cambiar de usuario" puede generar sesiones falsas (un admin que entra como otro usuario para hacer pruebas).

---

### 2.1 👤 ADMINISTRADORES — Login 3 meses

**¿Qué obtiene?** Cantidad de administradores que iniciaron sesión en los últimos 3 meses, por empresa.

**Filtros paso a paso (Consulta principal):**
1. Filtros comunes de empresa.
2. Para cada empresa, se buscan sesiones de usuario donde:
   - ✅ El usuario pertenece a esa empresa.
   - ✅ El usuario está **activo**.
   - ✅ El rol asignado es **Administrador (1)** y está activo.
   - ✅ El módulo del rol está activo en la empresa.
   - ✅ La **última actividad** de la sesión es **posterior** al inicio de los 3 meses.
3. Se cuentan usuarios **únicos** que cumplan todo lo anterior.

**Filtros paso a paso (Consulta de ajuste — Step_2):**
1. Mismos filtros comunes de empresa.
2. Para cada empresa, se cuentan los administradores que:
   - ✅ Tienen rol **Administrador (1)** activo.
   - ✅ Su email **NO** es de soporte Visma.
   - ✅ **SÍ** aparecen en la lista de "cambio de usuario" (paso previo).
   - ❌ Pero **NO** tienen una sesión propia creada entre hace 3 meses y hoy.
3. Esto permite **restar** a los administradores cuya sesión fue generada solo por un cambio de usuario, no por un login real.

---

### 2.2 👤 BUSINESS PARTNERS — Login 3 meses

**Idéntico al anterior** pero filtrando por **rol 2 (Business Partner)** en lugar de rol 1.

---

### 2.3 👤 LÍDERES — Login 3 meses

**Idéntico al anterior** pero filtrando por **rol 3 (Líder)**.

---

### 2.4 👤 COLABORADORES — Login 3 meses

**Idéntico al anterior** pero filtrando por **rol 4 (Colaborador)**.

---

## Sección 3 — LOGIN ÚLTIMO MES

> **Objetivo:** Exactamente lo mismo que la Sección 2, pero midiendo solo el **último mes** en vez de 3 meses.

### 3.0 🔍 Paso previo: Detección de cambio de usuario/plataforma (último mes)

Igual que el paso 2.0 pero con `{fecha_inicio}` a `{fecha_fin}` (solo un mes).

### 3.1–3.4 Administradores, BPs, Líderes, Colaboradores

La lógica es **exactamente la misma** que en Login 3 meses, con la única diferencia:
- Se usa `{fecha_inicio}` en lugar de `{fecha_inicio_3m}`.

| KPI | Rol filtrado |
|---|---|
| ADMINISTRADORES | Rol 1 |
| BUSINESS PARTNERS | Rol 2 |
| LÍDERES | Rol 3 |
| COLABORADORES | Rol 4 |

---

## Sección 4 — REPORTES ÚLTIMO MES

### 4.0 🔍 Paso previo: Obtener usuarios que descargaron reportes

**¿Qué obtiene?** Lista de IDs únicos de usuarios que descargaron reportes en el último mes.

**Filtros:**
1. Se busca en la tabla de **logs**.
2. Solo registros con canal = `'REPORT'` (actividad de reportes).
3. El campo `context` debe ser un JSON válido.
4. La fecha debe estar en el **último mes**.
5. Se obtienen usuarios **únicos** (sin duplicados).

---

### 4.1 📋 ADMINISTRADORES QUE HAN DESCARGADO AL MENOS UN REPORTE

**¿Qué obtiene?** Por cada empresa, cuántos administradores descargaron al menos un reporte en el último mes.

**Filtros paso a paso:**
1. Filtros comunes de empresa.
2. Para cada empresa, se buscan usuarios con:
   - ✅ Rol **Administrador (1)** activo.
   - ✅ Email **NO** es de soporte Visma.
   - ✅ El usuario aparece en la **lista de IDs del paso previo** (descargó al menos un reporte).
3. Se cuentan usuarios únicos.

---

## Sección 5 — USUARIOS ASIGNADOS

> **Objetivo:** Contar cuántos usuarios de cada rol tienen acceso a al menos un módulo de la plataforma.

### 5.1 👤 ADMINISTRADORES con usuario asignado

**Filtros paso a paso:**
1. Filtros comunes de empresa.
2. Se buscan usuarios con:
   - ✅ Pertenecen a la empresa.
   - ✅ Estado **activo**.
   - ✅ Rol **Administrador (1)** activo.
   - ✅ Email **NO** es de soporte Visma.
   - ✅ Aparecen en la tabla `users_modules` (tienen al menos un módulo asignado).
3. Se cuentan usuarios únicos.

### 5.2 👤 BUSINESS PARTNERS con usuario asignado

Igual que el anterior con **rol 2**. 
> Nota: aquí NO se filtra por email de soporte.

### 5.3 👤 LÍDERES con usuario asignado

**Filtros:**
- Se buscan en `teams_collaborators` (tabla de equipos).
- ✅ Activos en el equipo.
- ✅ Tienen usuario activo.
- ✅ Rol **Líder (3)** activo.
- ✅ Aparecen en `users_modules`.

### 5.4 👤 COLABORADORES con usuario asignado

Igual que líderes pero con **rol 4**.

---

## Sección 6 — EVALUACIONES ÚLTIMOS 6 MESES

### 6.1 📋 EVALUACIONES oficializadas

**¿Qué obtiene?** Cantidad de evaluaciones de desempeño que fueron completamente oficializadas en los últimos 6 meses, por empresa.

**Filtros paso a paso:**
1. Filtros comunes de empresa.
2. Para cada empresa, se buscan evaluaciones donde:
   - ✅ La evaluación está **activa**.
   - ✅ El tipo es `'EVALUACION'` (no revisión).
   - ✅ Fue creada entre **hace 6 meses y hoy**.
   - ✅ **Todos** los colaboradores dentro de esa evaluación tienen estado `'OFICIALIZADO'` (es decir, la evaluación está 100% terminada).
   - ✅ El periodo al que pertenece es **visible** y de esa empresa.
3. Se cuentan evaluaciones únicas.

---

### 6.2 📋 REVISIONES oficializadas

**Idéntico al anterior** pero el tipo es `'REVISION'` en lugar de `'EVALUACION'`.

> 💡 **Diferencia entre Evaluación y Revisión:** Una **evaluación** es el proceso completo de evaluar el desempeño del colaborador. Una **revisión** es un seguimiento intermedio (check-in) que se hace durante el periodo.

---

## Sección 7 — FEEDBACK EN SU ÚLTIMA EVALUACIÓN OFICIALIZADA

### 7.1 📋 Colaboradores con encuesta de feedback ENVIADA

**¿Qué obtiene?** Cuántos colaboradores tienen la encuesta de feedback marcada como "enviada" en su última evaluación oficializada.

**Filtros paso a paso:**
1. Filtros comunes de empresa.
2. Para cada empresa, se buscan colaboradores del equipo donde:
   - ✅ El colaborador tiene al menos una evaluación con estado `'OFICIALIZADO'`.
   - ✅ La evaluación es de tipo `'EVALUACION'`.
   - ✅ Se toma la **última evaluación oficializada** (la más reciente por fecha de fin).
   - ✅ En esa evaluación, el campo `feedback = 1` (la encuesta fue enviada/marcada).
3. Se cuentan colaboradores únicos.

---

### 7.2 📋 Colaboradores que RESPONDIERON la encuesta de feedback

**Idéntico al anterior** con un filtro adicional:
- ✅ `feedback_value != 0` → El colaborador efectivamente **respondió** la encuesta (no solo la recibió).

---

## Sección 8 — PERIODO ACTIVO

> **¿Qué es un "Periodo Activo"?** Es el periodo de evaluación que está en curso actualmente. Se determina porque la fecha de hoy cae entre la fecha de inicio y la fecha de fin del periodo.

### 8.1 📋 Colaboradores en al menos un ciclo de objetivos

**Filtros paso a paso:**
1. Filtros comunes de empresa.
2. Se buscan colaboradores activos o en proceso (`status 1 o 2`).
3. El colaborador debe estar asignado a un **ciclo de objetivos** que:
   - ✅ Esté **activo**.
   - ✅ Pertenezca a un periodo **visible**.
   - ✅ La **fecha actual** esté **dentro** del rango del periodo.

---

### 8.2 📋 Colaboradores con 100% de objetivos definidos

**¿Qué obtiene?** Colaboradores que tienen sus objetivos completos en al menos un ciclo del periodo activo.

**Filtros paso a paso:**
1. Filtros comunes de empresa.
2. Colaboradores activos o en proceso.
3. Se verifican **dos escenarios** (uno u otro):
   - **Escenario A (con pesos):** El ciclo tiene pesos habilitados (`set_percent = 1`). Se verifica que la **suma de porcentajes** de los objetivos activos (no rechazados) sea **exactamente 100%**.
   - **Escenario B (sin pesos):** El ciclo no usa pesos (`set_percent = 0`). Basta con que el colaborador tenga **al menos 1 objetivo** activo y no rechazado.
4. Todo esto dentro de un periodo cuya **fecha actual esté dentro del rango**.

---

### 8.3 📋 Colaboradores en al menos una revisión

**Filtros:**
- El colaborador aparece en una evaluación de tipo `'REVISION'` activa, dentro de un periodo visible y activo actualmente.

### 8.4 📋 Colaboradores con al menos una revisión finalizada

**Filtros adicionales:** Igual que 8.3 pero el estado del colaborador en la revisión es `'OFICIALIZADO'`.

### 8.5 📋 Colaboradores en al menos una evaluación de desempeño

**Filtros:** Igual que 8.3 pero tipo `'EVALUACION'`.

### 8.6 📋 Colaboradores con al menos una evaluación finalizada

**Filtros adicionales:** El estado **NO** es `'PENDIENTE'` ni `'BORRADOR'` (es decir, ya fue procesada de alguna forma).

### 8.7 📋 Colaboradores con al menos una evaluación oficializada

**Filtros adicionales:** El estado es exactamente `'OFICIALIZADO'` (la evaluación fue completamente cerrada y firmada).

> 💡 **Diferencia entre "Finalizada" y "Oficializada":**
> - **Finalizada** = ya no está pendiente ni en borrador (puede estar en revisión, firmada, etc.).
> - **Oficializada** = está completamente cerrada y firmada. Es el estado final.

---

## Sección 9 — ÚLTIMO PERIODO

> **¿Qué es el "Último Periodo"?** Es el periodo de evaluación más reciente que **ya terminó** (la fecha actual ya NO está dentro de su rango). Se busca como el periodo con el ID más alto que ya pasó.

Las métricas son **exactamente las mismas** que en la Sección 8 (Periodo Activo), pero en vez de buscar un periodo donde hoy esté dentro del rango, se busca el **periodo más reciente ya finalizado**.

| # | KPI | Descripción |
|---|---|---|
| 9.1 | Colaboradores en ciclo de objetivos | Misma lógica que 8.1, periodo pasado |
| 9.2 | Colaboradores con 100% objetivos | Misma lógica que 8.2, periodo pasado |
| 9.3 | Colaboradores en revisión | Misma lógica que 8.3, periodo pasado |
| 9.4 | Colaboradores con revisión finalizada | Misma lógica que 8.4, periodo pasado |
| 9.5 | Colaboradores en evaluación | Misma lógica que 8.5, periodo pasado |
| 9.6 | Colaboradores con evaluación finalizada | Misma lógica que 8.6, periodo pasado |
| 9.7 | Colaboradores con evaluación oficializada | Misma lógica que 8.7, periodo pasado |
| 9.8 | Colaboradores con feedback enviado | Misma lógica que 7.1, pero limitado al último periodo pasado |

---

## Sección 10 — ÚLTIMA EVALUACIÓN / ÚLTIMA REVISIÓN

### 10.1 📅 Fecha de la última evaluación

**¿Qué obtiene?** La fecha de cierre de la evaluación de desempeño más reciente de cada empresa.

**Filtros:**
1. Filtros comunes de empresa.
2. Se buscan evaluaciones de tipo `'EVALUACION'`, activas, en periodos visibles.
3. Se toma la **más reciente** por fecha de fin (`date_end`).
4. Se muestra la fecha en formato `DD/MM/AAAA`.

### 10.2 📅 Fecha de la última revisión

**Igual que el anterior** pero con tipo `'REVISION'`.

---

## Sección 11 — PLANES DE DESARROLLO

### 11.1 📋 Total de planes de desarrollo

**¿Qué obtiene?** Cuántos planes de desarrollo activos existen por empresa.

**Filtros:**
1. Filtros comunes de empresa.
2. Se cuentan planes donde:
   - ✅ El plan está **activo**.
   - ✅ El colaborador asignado al plan está **activo** en el equipo.

### 11.2 📋 Total de planes completados

**Igual que el anterior** con un filtro adicional:
- ✅ El plan está marcado como **completado** (`completed = 1`).

---

## Sección 12 — ALCANCE (Módulos contratados)

> **Objetivo:** Determinar qué funcionalidades tiene activadas cada empresa. El resultado es **SÍ** o **NO** por cada empresa.

| # | KPI | ¿Qué verifica? | ¿Dónde busca? |
|---|---|---|---|
| 12.1 | TIENE DESEMPEÑO | ¿La empresa tiene el módulo de Desempeño activado? | Tabla `companies_modules`, módulo 1 |
| 12.2 | TIENE DESARROLLO | ¿La empresa tiene el módulo de Desarrollo activado? | Tabla `companies_modules`, módulo 2 |
| 12.3 | TIENE POTENCIAL | ¿La empresa tiene la opción de Potencial activada? | Tabla `companies_options`, opción `'potential'` con valor `'1'` |
| 12.4 | TIENE SOCIAL | ¿La empresa tiene el módulo Social activado? | Tabla `companies_modules`, módulo 3 |
| 12.5 | TIENE CHAT | ¿La empresa tiene el Chat habilitado? | Tabla `companies_options`, opción `'showChat'` con valor `1` |
| 12.6 | TIENE EVIDENCIAS | ¿La empresa tiene Evidencias de objetivos? | Tabla `companies_options`, opción `'evidenceObjectives'` con valor `1` |
| 12.7 | TIENE LMS | ¿La empresa tiene el sistema de formación (LMS)? | Tabla `companies_options`, opción `'showFormacionDevelopment'` con valor `1` |
| 12.8 | TIENE iFrame ENG | ¿La empresa tiene la conexión con Clima/Engagement? | Tabla `companies_options`, opción `'linkAccountClimateEngagement'` con valor `1` |
| 12.9 | TIENE Directorio | ¿La empresa tiene el Directorio habilitado? | Tabla `companies_options`, opción `'showDirectory'` con valor `1` |

**Filtros en todos los casos:** Solo empresas reales y activas (filtros comunes).

---

## Sección 13 — USO EN SOCIAL

> **Objetivo:** Medir la actividad en el módulo Social (publicaciones, comentarios, likes, grupos).

### 13.1 👥 Usuarios con acceso a Social

**¿Qué obtiene?** Total de usuarios (líderes + colaboradores) que tienen acceso al módulo Social.

**Filtros:**
1. Filtros comunes de empresa.
2. Se buscan usuarios con:
   - ✅ Estado activo.
   - ✅ Rol activo.
   - ✅ Módulo asignado activo.
   - ✅ El módulo es **Social (módulo 3)**.
   - ✅ El rol es **Líder (3) o Colaborador (4)**.

---

### 13.2 📝 Publicaciones (Administradores y BPs)

**¿Qué obtiene?** Cuántos administradores/BPs publicaron al menos una vez en Social en el último mes.

**Filtros:**
1. Se busca en **logs** del último mes.
2. El mensaje de actividad indica que se creó una **publicación** o un **reconocimiento** (clic al botón "Publicar").
3. El tipo de usuario en el contexto es `'RRHH'` (administradores/BPs).
4. Se agrupan por empresa y se cuentan usuarios **únicos**.

---

### 13.3 📝 Publicaciones (Líderes y Colaboradores)

**¿Qué obtiene?** Cuántos líderes/colaboradores publicaron al menos una vez en Social en el último mes.

**Filtros:**
1. Se busca en **logs** del último mes.
2. El mensaje de actividad indica que se creó una **publicación** o un **reconocimiento** (clic al botón "Publicar").
3. El tipo de usuario en el contexto es `'Jefe'` o `'Colaborador'`.
4. Se agrupan por empresa y se cuentan usuarios **únicos**.

---

### 13.4 💬 Comentarios (Administradores y BPs)

**Filtros:** Busca en logs la acción de **"Crear comentario — Clic al botón Comentar"** con tipo de usuario `'RRHH'`.

### 13.5 💬 Comentarios (Líderes y Colaboradores)

Igual que el anterior pero con tipo de usuario `'Jefe'` o `'Colaborador'`.

---

### 13.6 👍 Likes (Administradores y BPs)

**¿Qué obtiene?** Cantidad de "likes" dados por administradores y BPs en publicaciones activas.

**Proceso en 2 pasos:**
1. **Paso 1 (MySQL):** Se obtienen los IDs de todos los usuarios con rol **Administrador (1) o BP (2)**, activos.
2. **Paso 2 (MongoDB):** En la base de datos Social, se buscan reacciones donde:
   - ✅ El tipo es `"like"`.
   - ✅ La reacción está **activa**.
   - ✅ La fecha está en el **último mes**.
   - ✅ El usuario está en la lista del paso 1.
   - ✅ La publicación asociada está **activa**.
3. Se agrupan por empresa y se suma el total de likes.

### 13.7 👍 Likes (Líderes y Colaboradores)

**Idéntico** al anterior pero con roles **Líder (3) y Colaborador (4)**.

---

### 13.8 📂 Grupos creados

**Proceso en 2 pasos:**
1. **Paso 1 (MySQL):** Se obtienen los IDs de todas las empresas reales y activas.
2. **Paso 2 (MongoDB):** En la base Social, se buscan grupos donde:
   - ✅ El grupo está **activo**.
   - ✅ Fue creado en el **último mes**.
   - ✅ La empresa está en la lista del paso 1.
3. Se agrupan por empresa y se cuenta el total.

---

### 13.9 🧩 Widget personalizable

**¿Qué obtiene?** Si la empresa tiene un widget personalizable configurado y cuántos enlaces tiene.

**Filtros:**
1. Filtros comunes de empresa.
2. Se busca la opción `'customizableWidget'` en las opciones de empresa.
3. El valor debe ser un **JSON válido**.
4. El campo `widgetName` dentro del JSON **no debe estar vacío** (el widget tiene nombre).
5. Se cuenta cuántos **links** tiene configurados.

---

## Sección 14 — PERSONALIZADO

> **Objetivo:** Obtener información adicional de configuración y ubicación de cada empresa.

### 14.1 📋 Módulo "Tu Recibo"

**¿Qué obtiene?** Si la empresa tiene el módulo "Tu Recibo" activado o inactivado.

**Filtros:**
1. Filtros comunes de empresa.
2. Se busca la opción `'isTREnabled'` en la tabla `companies_options`.
3. Si el valor es `'0'` o no existe → `Inactivo`.
4. Cualquier otro valor → `Activo`.

### 14.2 🌍 País

**¿Qué obtiene?** El país asignado a cada empresa.

**Filtros:**
1. Filtros comunes de empresa.
2. Se hace un cruce con la tabla `countries` usando el `country_id` de la empresa.
3. Se obtiene el nombre del país.

---

## 📊 Resumen visual del flujo de datos

```
┌─────────────────────────────────────────────────────────────┐
│                    EMPRESAS REALES                           │
│  (activas, no demo, no QA, no Ronald, con HubSpot ID)       │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────────┐
   │ Conteos │  │  Logins  │  │ Evaluaciones │
   │ totales │  │ (1m, 3m) │  │ y Objetivos  │
   └─────────┘  └──────────┘  └──────────────┘
        │             │             │
        ▼             ▼             ▼
   ┌─────────────────────────────────────────┐
   │         REPORTE FINAL POR EMPRESA       │
   │  (ID, Nombre, HubSpot ID, métricas...) │
   └─────────────────────────────────────────┘
```

---

## ❓ Preguntas frecuentes

**¿Por qué se excluyen empresas con "QA", "Demo" o "Ronald" en el nombre?**
> Son cuentas internas de prueba. No representan clientes reales y sus datos distorsionarían las métricas.

**¿Por qué se excluyen los emails de soporte@visma.com?**
> El equipo de soporte a veces ingresa a las cuentas de los clientes para ayudarlos. Esas sesiones no deben contarse como uso real del cliente.

**¿Qué pasa con el "Cambiar de usuario"?**
> Cuando un administrador "cambia de usuario" para ver la plataforma como un colaborador, se genera una sesión falsa. El sistema detecta estos casos y los resta del conteo de login real.

**¿Qué diferencia hay entre "Periodo Activo" y "Último Periodo"?**
> El **Periodo Activo** es el que está en curso HOY. El **Último Periodo** es el más reciente que ya terminó. Esto permite comparar el estado actual vs. el estado al cierre anterior.

**¿De dónde salen los datos de Social (likes, grupos)?**
> De una base de datos MongoDB separada, porque el módulo Social utiliza una arquitectura diferente al resto de la plataforma.

---

*Documento actualizado el 23 de marzo de 2026.*

