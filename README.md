# 📅 Generador de Horarios Escolares Automatizado

Sistema de escritorio desarrollado en Python para la generación automática y optimizada de horarios académicos. Utiliza inteligencia artificial (Constraint Programming) para asegurar que no existan choques de horarios, aulas o profesores, respetando estrictas reglas pedagógicas.

## 🛠 Tecnologías Utilizadas

| Componente | Tecnología | Por qué se eligió |
| :--- | :--- | :--- |
| **Lenguaje Backend** | **Python 3.12** | Líder mundial en ciencia de datos y librerías de optimización. |
| **Framework Web** | **Flask** | Ligero, modular y excelente compatibilidad para convertir en `.exe`. |
| **Base de Datos** | **SQLite + Peewee** | Almacenamiento local (archivo único), sin instalar servidores complejos. |
| **Algoritmo** | **Google OR-Tools** | Motor matemático de Google para resolver problemas de restricción (CSP). |
| **Frontend** | **Vue.js 3 + Bootstrap** | Interfaz reactiva y moderna sin necesidad de compilación Node.js (Offline). |
| **Visualización** | **FullCalendar** | Estándar de la industria para visualizar agendas y cronogramas. |
| **Empaquetado** | **PyInstaller** | Convierte todo el código Python en un solo ejecutable portable. |

---

## 📋 Requerimientos y Reglas de Negocio (Lógica del Sistema)

Este proyecto está diseñado para cumplir estrictamente con las siguientes reglas. **(No olvidar al programar el algoritmo):**

### 1. Estructura Académica
* **Materias:** Definidas por nombre (Ej: Inglés, Italiano, Francés).
* **Cursos y Niveles:** Combinación de letra y nivel (Ej: Nivel 1 - Curso A).
* **Aulas:** Espacios físicos limitados. El sistema no puede asignar más clases que aulas disponibles.

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
