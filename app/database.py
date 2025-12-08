# app/database.py
from peewee import SqliteDatabase
import os

# Definimos la ruta donde se guardará el archivo .db
# Se guardará en la carpeta 'data' en la raíz del proyecto
DB_FOLDER = 'data'
DB_FILE = 'horarios.db'

# Aseguramos que la carpeta data exista
if not os.path.exists(DB_FOLDER):
    os.makedirs(DB_FOLDER)

# Ruta completa
db_path = os.path.join(DB_FOLDER, DB_FILE)

# Inicializamos la base de datos SQLite
# pragmas={'journal_mode': 'wal'} ayuda a que sea más rápido y seguro contra fallos
db = SqliteDatabase(db_path, pragmas={'foreign_keys': 1, 'journal_mode': 'wal'})