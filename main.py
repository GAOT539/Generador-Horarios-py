import os
import sys
import threading
import webview
from time import sleep
from app import create_app

# Crea la instancia de Flask
app = create_app()

def run_server():
    # Ejecuta Flask en un hilo separado
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)

def create_desktop_shortcut():
    """
    Crea un acceso directo en el Escritorio de Windows apuntando a este ejecutable.
    """
    if sys.platform != 'win32':
        return

    try:
        import pythoncom
        from win32com.client import Dispatch
        import ctypes.wintypes

        pythoncom.CoInitialize()

        # 1. Obtener ruta del Escritorio (CSIDL_DESKTOPDIRECTORY = 16)
        CSIDL_DESKTOPDIRECTORY = 16
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_DESKTOPDIRECTORY, None, 0, buf)
        desktop_path = buf.value

        shortcut_name = "Sistema de Horarios.lnk"
        shortcut_path = os.path.join(desktop_path, shortcut_name)

        if not os.path.exists(shortcut_path):
            shell = Dispatch('WScript.Shell')
            shortcut = shell.CreateShortCut(shortcut_path)
            
            # Detectar si corremos como .exe o script .py
            if getattr(sys, 'frozen', False):
                target = sys.executable
                shortcut.TargetPath = target
                shortcut.WorkingDirectory = os.path.dirname(target)
            else:
                target = sys.executable
                shortcut.TargetPath = target
                shortcut.Arguments = f'"{os.path.abspath(sys.argv[0])}"'
                shortcut.WorkingDirectory = os.path.dirname(os.path.abspath(sys.argv[0]))
            
            shortcut.Description = "Acceso directo al Generador de Horarios"
            shortcut.save()
            print(f"Acceso directo creado en: {shortcut_path}")

    except Exception as e:
        print(f"No se pudo crear el acceso directo: {e}")

if __name__ == '__main__':
    # Crear acceso directo al inicio
    create_desktop_shortcut()

    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    sleep(1)

    webview.create_window(
        'Generador de Horarios', 
        'http://127.0.0.1:5000',
        width=1200,
        height=800,
        resizable=True
    )
    
    webview.start()