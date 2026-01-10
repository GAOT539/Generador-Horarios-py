from flask import Flask
# Importamos db y SYSTEM_ROOT para saber donde guardar los logs
from app.database import db, SYSTEM_ROOT
import logging
from logging.handlers import RotatingFileHandler
import os
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui'

    # --- CONFIGURACIÓN DE LOGS (Integrada con Documentos) ---
    LOG_FOLDER = os.path.join(SYSTEM_ROOT, 'logs')
    
    if not os.path.exists(LOG_FOLDER):
        try:
            os.makedirs(LOG_FOLDER)
        except OSError:
            # Fallback a carpeta local 'logs' si falla la creación en documentos
            LOG_FOLDER = 'logs'
            if not os.path.exists(LOG_FOLDER):
                os.mkdir(LOG_FOLDER)

    log_file_path = os.path.join(LOG_FOLDER, 'sistema_horarios.log')

    file_handler = RotatingFileHandler(log_file_path, maxBytes=1024 * 1024, backupCount=5)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)

    app.logger.setLevel(logging.INFO)
    app.logger.info(f'Iniciando Sistema de Horarios. Raíz de datos: {SYSTEM_ROOT}')
    
    # ---INICIALIZACIÓN DE TABLAS ---
    try:
        if db.is_closed():
            db.connect()
        db.create_tables([Profesor, Materia, Curso, Horario, ProfesorMateria], safe=True)
        app.logger.info("Base de datos inicializada: Tablas verificadas.")
    except Exception as e:
        app.logger.critical(f"Error crítico creando tablas: {str(e)}")
    finally:
        if not db.is_closed():
            db.close()

    @app.before_request
    def before_request():
        if db.is_closed():
            db.connect()

    @app.teardown_request
    def teardown_request(exc):
        if not db.is_closed():
            db.close()

    from app.routes import bp
    app.register_blueprint(bp)

    return app