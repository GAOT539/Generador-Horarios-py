# Generador de Horarios Académicos Automatizado

Sistema web inteligente desarrollado en Python (Flask) para la planificación y optimización de horarios académicos. Utiliza Programación por Restricciones (CP-SAT de Google OR-Tools) para asignar profesores a cursos basándose en demanda, competencias y reglas de negocio estrictas.

## 🚀 Características Principales

* **Motor de Asignación Inteligente**: Algoritmo capaz de resolver conflictos complejos de horarios, carga horaria y modalidades.
* **Gestión de Demanda Matricial**: Interfaz visual para definir la cantidad exacta de cursos necesarios por franja horaria y modalidad.
* **Validación Previa**: Sistema de detección de errores antes de la ejecución (ej. "Faltan profesores para cubrir la demanda de Inglés Nivel 1 a las 07:00").
* **Reportes Avanzados**: Generación de estadísticas, gráficos de ocupación, listados completos y horarios individuales en PDF.
* **Calendario Interactivo**: Visualización gráfica con filtros por modalidad (Presencial/Online) y detalles de clase.

---

## ⚙️ Requerimientos y Reglas de Negocio

El núcleo del sistema se basa en un conjunto estricto de reglas que el algoritmo debe cumplir para generar un horario válido y óptimo.

### 1. Definición de Modalidades y Horarios

El sistema gestiona tres tipos de bloques horarios:

* **🏫 Presencial (Lunes a Jueves)**: Bloques de 2 horas.
  * Franjas: 07:00-09:00, 09:00-11:00, ..., 19:00-21:00.
* **💻 Online L-J (Lunes a Jueves)**: Bloques de 2 horas (mismas franjas que presencial).
* **📅 Online FDS (Sábado)**: Bloque intensivo único.
  * Horario Visual: 08:00 - 17:00.
  * Carga Interna: Computa como 8 horas de carga laboral.

### 2. Restricciones Duras (Hard Constraints)

Estas reglas son inviolables; si no se pueden cumplir, el sistema no generará el horario e indicará el error.

* **Competencia Docente**: Un profesor solo puede ser asignado a materias y niveles para los que está explícitamente habilitado (ej. "Inglés Nivel 3").
* **Unicidad**: Un profesor no puede estar en dos clases al mismo tiempo.
* **Carga Horaria Máxima**:
  * **Semanal**: No exceder el límite configurado por profesor (ej. 32 horas).
  * **Diaria (L-J)**: No exceder el límite diario (ej. 8 horas) en días laborables. *Nota: La carga del sábado no cuenta para el límite diario, solo para el semanal.*
* **Regla Crítica de Desplazamiento (Gap 2 Horas)**:
  * Si un profesor imparte clases **Presenciales** y **Online** en el **mismo día**, es obligatorio que exista un intervalo de **exactamente 2 horas** entre el cambio de modalidad para permitir el traslado.
  * *Ejemplo Válido*: 07-09 (Online) -> [09-11 Hueco] -> 11-13 (Presencial).
  * *Ejemplo Inválido*: 07-09 (Online) -> 09-11 (Presencial).

### 3. Objetivos de Optimización (Soft Constraints)

El sistema busca la "mejor" solución posible basándose en estos criterios de calidad:

* **⚡ Asignación de Carga Óptima**: Se busca maximizar la cantidad de profesores con asignación activa, evitando que docentes queden con 0 horas si hay demanda disponible (distribución equitativa).
* **🔄 Preferencia de Horarios Consecutivos**: El algoritmo premia la asignación de bloques seguidos (ej. 07-09 y 09-11) para reducir "huecos" innecesarios en la agenda del docente.
* **⚖️ Prioridad de Modalidad Mixta**: Se penaliza la creación de horarios "Solo Virtuales". El sistema intentará asignar al menos un curso presencial a cada docente si su disponibilidad y competencias lo permiten.

---

## 🛠️ Estructura del Proyecto

### Backend (Python/Flask)

* **`app/models.py`**: Definición de base de datos (SQLite) usando ORM Peewee (Profesores, Materias, Cursos, Horarios).
* **`app/engine/solver.py`**: **Cerebro del sistema**. Contiene la lógica del solver CP-SAT, las restricciones matemáticas y la función de pre-validación de recursos.
* **`app/routes.py`**: Endpoints API para la gestión de datos, ejecución del generador y exportación de reportes.

### Frontend (Vue.js + Bootstrap)

* **`config.html`**:
  * Matriz de inputs para definir la demanda de cursos por hora.
  * Gestión de profesores con scroll y filtros.
  * Respaldo y restauración de base de datos (JSON).
* **`calendario.html`**:
  * Vista de calendario semanal/lista.
  * Filtros dinámicos por Modalidad (Presencial/Online), Materia y Profesor.
* **`reportes.html`**:
  * Reporte General: Resumen de oferta académica agrupada.
  * Horarios Completos: Lista detallada.
  * Estadísticas: Gráficos de ocupación y barras de carga docente (con detalle de competencias).
  * Horario Individual: Generación de PDF por profesor con agrupación de horas.

---

## 📦 Instalación y Ejecución

1. **Clonar el repositorio**:

   ```bash
   git clone [https://github.com/tu-usuario/generador-horarios-py.git](https://github.com/tu-usuario/generador-horarios-py.git)
   cd generador-horarios-py
   ```
2. **Crear entorno virtual** (Recomendado):

   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   ```
3. **Instalar dependencias**:

   ```bash
   pip install -r requirements.txt
   ```
4. **Ejecutar la aplicación**:

   ```bash
   python run_debug.py
   ```

   El sistema estará disponible en `http://127.0.0.1:5000`.
5. ##### Crear ejecutable:

```
pyinstaller --name "Sistema_Horarios" --windowed --onefile --add-data "app/templates;app/templates" --add-data "app/static;app/static" --collect-all ortools main.py
```



---

## 📂 Estructura del Proyecto

```
school-scheduler-ortools/
├── app/
│   ├── engine/
│   ├── static/
│   ├── templates/
│   ├── database.py
│   ├── models.py
│   └── routes.py
├── data/
├── main.py
├── run_debug.py
└── requirements.txt
```

---

## 📋 Uso del Sistema

1. **Configuración**:
   * Vaya a la pestaña **Configuración**.
   * Cree las **Materias** y defina la demanda (cantidad de cursos) en la matriz de horas.
   * Registre los **Profesores**, defina sus horas máximas y asigne qué materias/niveles pueden impartir.
2. **Generación**:
   * Desde el **Dashboard** (Inicio), haga clic en "Generar Horarios".
   * El sistema validará primero si hay suficientes recursos. Si falta personal, mostrará un error específico indicando qué materia y hora falla.
   * Si todo es correcto, el algoritmo optimizará la distribución.
3. **Visualización y Reportes**:
   * Revise el resultado en el **Calendario**.
   * Consulte la carga horaria y descargue los PDF en **Reportes**.

---

## ⚠️ Notas Técnicas

* **Base de Datos**: Utiliza SQLite (`data/horarios.db`). Se reinicia automáticamente al generar un nuevo horario (los datos de configuración persisten, las asignaciones se recalculan).
* **Solver**: Utiliza Google OR-Tools. El tiempo límite de búsqueda está configurado a 70 segundos por defecto.
