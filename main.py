# main.py
import os
import sys
import threading
import webview
from time import sleep
from app import create_app

# Crea la instancia de Flask
app = create_app()

def run_server():
    # Ejecuta Flask en un hilo separado, sin modo debug/reloader para evitar errores en el exe
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

if __name__ == '__main__':
    # Iniciar el servidor Flask en un hilo aparte
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    # Esperar un momento para asegurar que el servidor arranque
    sleep(1)

    # Crear la ventana nativa apuntando al servidor local
    webview.create_window(
        'Generador de Horarios', 
        'http://127.0.0.1:5000',
        width=1200,
        height=800,
        resizable=True
    )
    
    # Iniciar el loop gráfico
    webview.start()