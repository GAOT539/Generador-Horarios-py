# 📅 Generador de Horarios Escolares Automatizado

Sistema de escritorio desarrollado en Python para la generación automática y optimizada de horarios académicos. Utiliza inteligencia artificial (Constraint Programming) para asegurar que no existan choques de horarios, aulas o profesores, respetando estrictas reglas pedagógicas.

## 🛠 Tecnologías Utilizadas

| Componente                 | Tecnología                    | Por qué se eligió                                                          |
| :------------------------- | :----------------------------- | :--------------------------------------------------------------------------- |
| **Lenguaje Backend** | **Python 3.12**          | Líder mundial en ciencia de datos y librerías de optimización.            |
| **Framework Web**    | **Flask**                | Ligero, modular y excelente compatibilidad para convertir en `.exe`.       |
| **Base de Datos**    | **SQLite + Peewee**      | Almacenamiento local (archivo único), sin instalar servidores complejos.    |
| **Algoritmo**        | **Google OR-Tools**      | Motor matemático de Google para resolver problemas de restricción (CSP).   |
| **Frontend**         | **Vue.js 3 + Bootstrap** | Interfaz reactiva y moderna sin necesidad de compilación Node.js (Offline). |
| **Visualización**   | **FullCalendar**         | Estándar de la industria para visualizar agendas y cronogramas.             |
| **Empaquetado**      | **PyInstaller**          | Convierte todo el código Python en un solo ejecutable portable.             |

---

## 📋 Requerimientos y Reglas de Negocio (Lógica del Sistema)

Este proyecto está diseñado para cumplir estrictamente con las siguientes reglas. **(No olvidar al programar el algoritmo):**

### 1. Estructura Académica

* **Materias:** Definidas por nombre (Ej: Inglés, Italiano, Francés).
* **Cursos y Niveles:** Combinación de letra y nivel (Ej: Nivel 1 - Curso A).
* **Aulas:** Espacios físicos limitados. El sistema no puede asignar más clases que aulas disponibles. (Se omite aulas)

### 2. Jornadas (Turnos)

* **Matutina:** 07:00 AM - 13:00 PM.
* **Vespertina:** 14:00 PM - 22:00 PM.
* *Restricción:* Ciertos cursos solo existen en una jornada específica (Ej: Inglés A1 solo es matutino).

### 3. Restricciones del Profesor

* **Competencia:** Un profesor **solo** puede ser asignado a materias que tiene registradas en su perfil. (No asignar Matemáticas a un profe de Inglés).
* **Carga Horaria:**
  * No exceder el **Máximo de horas por semana**.
  * No exceder el **Máximo de horas por día**.
* **Horas Libres:** El sistema debe permitir huecos (horas libres) si es necesario para cuadrar el horario.

### 4. Reglas Críticas de Asignación (Algoritmo)

* **Bloques Mínimos:** Las clases deben ser de **mínimo 2 horas consecutivas**. (Prohibido asignar horas sueltas o "huérfanas" de 1 hora).
* **Anti-Colisión (Aulas):** Un aula no puede tener dos cursos a la misma hora.
* **Anti-Colisión (Profesores):** Un profesor no puede estar en dos aulas a la misma hora.
* **Duplicidad:** No se pueden agendar duplicados de la misma materia para el mismo grupo en el mismo horario.

---

## 🚀 Instalación y Puesta en Marcha

Sigue estos pasos para ejecutar el proyecto en modo desarrollo en tu máquina local.

### 1. Prerrequisitos

* Tener instalado **Python 3.12** (Asegurarse de marcar "Add to PATH").
* Sistema Operativo: Windows 10/11 (Recomendado).

### 2. Configuración del Entorno

```bash
# 1. Crear entorno virtual
python -m venv .venv

# 2. Activar entorno
.venv\Scripts\activate

# 3. Actualizar PIP (Importante para compatibilidad)
python -m pip install --upgrade pip

# 4. Instalar dependencias
pip install -r requirements.txt
```

### 3. Ejecución

```bash
python run_debug.py
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

## ⚠️ Notas Importantes

* No usar CDNs: todo funciona offline.
* Si se cambian modelos, borrar `data/horarios.db`.
* Las horas deben ser las mismas. (luneas a jueves)
* Se elimino el modulo de Aulas.(Cambio en requerimientos)

**📋 Aclaraciones**

* El sistema asigna a los profesores conforme están enlistados en el panel de profesores (Existe la posibilidad de que un profesor no sea asignado a ningún horario).
* Los cursos no están balanceados; es decir, no existe la misma cantidad en el horario matutino que en el vespertino.

## 📋 PLAN DE MODIFICACIONES Y NUEVOS REQUERIMIENTOS

### * GESTIÓN DE MODALIDADES EN MATERIAS

---

El sistema debe distinguir explícitamente entre dos modalidades académicas:
   A. PROGRAMA REGULAR (Presencial) - Opción por defecto.
   B. MODALIDAD EN LÍNEA (Online).

- Configuración de la Demanda:
  En el apartado de configuración de materias, se debe permitir definir la cantidad de cursos por separado para cada modalidad.
  Ejemplo: "INGLES Nivel 1" puede tener configurado:
  - 5 cursos para PROGRAMA REGULAR.
  - 2 cursos para MODALIDAD EN LÍNEA.
    (Puede existir una materia que solo tenga cursos presenciales, solo online, o ambos).

### * REGLAS DE HORARIOS Y TURNOS

---

- Horario Vespertino General:
  Se ajusta el rango vespertino para operar de 13:00 a 19:00 (1 PM a 7 PM).
- Distribución de Cursos (Balanceo de Horarios):
  Se debe evitar agrupar todos los cursos en el primer horario de la mañana. La asignación debe alternar los bloques horarios disponibles.
  Ejemplo de distribución deseada:

  - Curso 1: Mañana (07:00 - 09:00)
  - Curso 2: Tarde  (13:00 - 15:00)
  - Curso 3: Mañana (09:00 - 11:00)
  - Curso 4: Tarde  (15:00 - 17:00)
- Preferencia Horaria para MODALIDAD EN LÍNEA:
  Los cursos online deben priorizar los siguientes bloques:

  - Mañana: 07:00 - 09:00
  - Noche:  19:00 - 21:00
- Horarios de Fin de Semana (Exclusivo Online):
  Si un curso es MODALIDAD EN LÍNEA, debe tener la posibilidad de asignarse a Sábados y Domingos.

  - Restricción: Máximo 4 horas por día en fin de semana.
  - Bloque permitido: 07:00 a 11:00.

### * REGLAS DE ASIGNACIÓN DOCENTE Y RESTRICCIONES

---

- Asignación de Carga Óptima:
  El algoritmo debe garantizar que ningún profesor quede "Sin Asignación" o con "Baja Carga" si hay demanda disponible, respetando siempre su límite máximo de horas semanales (no exceder bajo ninguna circunstancia).
- Preferencia de Horarios Consecutivos:
  El sistema debe priorizar asignar clases seguidas al mismo profesor para evitar huecos innecesarios.
  Ejemplo ideal:

  - 07:00 a 09:00: (A) Inglés 1
  - 09:00 a 11:00: (B) Inglés 2
- REGLA CRÍTICA DE DESPLAZAMIENTO (Gap de 2 Horas):
  Si un profesor tiene asignados cursos de ambas modalidades (Presencial y Online) en el MISMO DÍA, debe existir obligatoriamente un intervalo mínimo de 2 horas entre el cambio de modalidad para permitir el desplazamiento.
  Ejemplo:

  - 07:00 - 09:00: MODALIDAD EN LÍNEA (Casa)
  - [Descanso/Traslado obligatorio de 09:00 a 11:00]
  - 11:00 - 13:00: PROGRAMA REGULAR (Universidad)

### * VISUALIZACIÓN EN CALENDARIO

---

El módulo de calendario debe presentar la información dividida claramente según la modalidad:

- Vista o sección para PROGRAMA REGULAR.
- Vista o sección para MODALIDAD EN LÍNEA.
  Esto permitirá identificar rápidamente la carga presencial vs. la virtual.


### **Observación**

**(Máximo horas semana):** El algoritmo actual  **no valida explícitamente el máximo de horas semanales dentro del solver** .

Configurar el Solver para que, si el día es Sábado (`dia=5`), trate el bloque como "Indivisible".
Modificar y asignar cuantos cursos son necesarios en la mañana y en la tarde de forma manual.
