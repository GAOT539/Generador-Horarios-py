from flask import Flask
from app.database import db
import logging
from logging.handlers import RotatingFileHandler
import os

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui'

    # --- CONFIGURACIÓN DE LOGS ---
    if not os.path.exists('logs'):
        os.mkdir('logs')

    file_handler = RotatingFileHandler('logs/sistema_horarios.log', maxBytes=1024 * 1024, backupCount=5)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)

    app.logger.setLevel(logging.INFO)
    app.logger.info('Iniciando Sistema de Horarios')
    # -----------------------------

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