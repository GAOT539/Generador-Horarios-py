from peewee import SqliteDatabase
import os
import sys
import ctypes.wintypes

# --- Lógica para obtener rutas del sistema (Documentos) ---
def get_documents_path():
    """Obtiene la ruta de 'Mis Documentos' de forma independiente del idioma."""
    try:
        # CSIDL_PERSONAL = 0x0005 (My Documents)
        CSIDL_PERSONAL = 5
        # SHGFP_TYPE_CURRENT = 0 (Obtener valor actual)
        SHGFP_TYPE_CURRENT = 0
        
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        # Usamos shell32.dll para obtener la ruta real del sistema
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
        return buf.value
    except Exception:
        # Fallback seguro: Usar la carpeta Documents del usuario actual si falla ctypes
        return os.path.join(os.path.expanduser('~'), 'Documents')

# --- Configuración de Directorios ---
# Definimos SYSTEM_ROOT aquí para poder importarlo en __init__.py (para logs)
try:
    DOCS_PATH = get_documents_path()
    SYSTEM_NAME = "SistemaHorarios"
    
    # Ruta base: .../Documentos/SistemaHorarios
    SYSTEM_ROOT = os.path.join(DOCS_PATH, SYSTEM_NAME)
except Exception:
    # Si todo falla, usar carpeta local actual
    SYSTEM_ROOT = os.getcwd()

# Configuración específica de Base de Datos
DB_FOLDER = os.path.join(SYSTEM_ROOT, 'data')
DB_FILE = 'horarios.db'

# Aseguramos que la carpeta data exista
if not os.path.exists(DB_FOLDER):
    try:
        os.makedirs(DB_FOLDER)
    except OSError:
        # Si no hay permisos en Documentos, volver a estructura local 'data'
        SYSTEM_ROOT = os.getcwd() # Revertimos root a local
        DB_FOLDER = 'data'
        if not os.path.exists(DB_FOLDER):
            os.makedirs(DB_FOLDER)

db_path = os.path.join(DB_FOLDER, DB_FILE)

# Inicializamos la base de datos
db = SqliteDatabase(db_path, pragmas={'foreign_keys': 1, 'journal_mode': 'wal'})