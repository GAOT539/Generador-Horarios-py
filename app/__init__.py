from flask import Blueprint, Flask
from app.models import inicializar_db

def create_app():
    app = Flask(__name__)
    
    app.config['SECRET_KEY'] = 'clave_secreta_para_sesiones'

    # Inicializar la DB al arrancar
    inicializar_db()

    # --- AQUÍ REGISTRAMOS EL BLUEPRINT ---
    from app.routes import bp
    app.register_blueprint(bp)

    return app