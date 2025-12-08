from flask import Blueprint, render_template, request, jsonify
from app.models import Profesor, Materia, Aula, ProfesorMateria, db, Horario, Curso
from app.engine.solver import generar_horario_automatico

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/config')
def config():
    return render_template('config.html')

# --- API AULAS ---
@bp.route('/api/aulas', methods=['GET', 'POST', 'DELETE'])
def manage_aulas():
    if request.method == 'POST':
        data = request.json
        try:
            Aula.create(nombre=data['nombre'])
            return jsonify({'status': 'ok'})
        except:
            return jsonify({'error': 'Duplicado'}), 400
    
    if request.method == 'DELETE':
        # Para borrar se usa ID en query param o ruta, simplificado aquí:
        Aula.delete().where(Aula.id == request.args.get('id')).execute()
        return jsonify({'status': 'ok'})

    return jsonify(list(Aula.select().dicts()))

# --- API MATERIAS (ACTUALIZADA) ---
@bp.route('/api/materias', methods=['GET', 'POST', 'DELETE'])
def manage_materias():
    if request.method == 'POST':
        data = request.json
        try:
            # Ahora guardamos nombre, nivel y cuántos grupos se necesitan
            Materia.create(
                nombre=data['nombre'],     # Ej: "Inglés"
                nivel=int(data['nivel']),  # Ej: 1
                cantidad_grupos=int(data['cantidad']) # Ej: 3
            )
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'error': 'Duplicado o error de datos'}), 400
            
    if request.method == 'DELETE':
        # Borrar materia (y sus relaciones con profesores)
        materia_id = request.args.get('id')
        ProfesorMateria.delete().where(ProfesorMateria.materia == materia_id).execute()
        Materia.delete().where(Materia.id == materia_id).execute()
        return jsonify({'status': 'ok'})

    # Al listar, ordenamos por Nombre y luego Nivel
    materias = Materia.select().order_by(Materia.nombre, Materia.nivel)
    lista = []
    for m in materias:
        lista.append({
            'id': m.id,
            'nombre': m.nombre,
            'nivel': m.nivel,
            'cantidad_grupos': m.cantidad_grupos,
            # Generamos un nombre completo para mostrarlo fácil: "Inglés (Nivel 1)"
            'nombre_completo': f"{m.nombre} (Nivel {m.nivel})"
        })
    return jsonify(lista)

# --- API PROFESORES (COMPLEJO) ---
@bp.route('/api/profesores', methods=['GET'])
def get_profesores():
    # Obtenemos profes con sus materias
    profes = []
    for p in Profesor.select():
        # Buscamos qué materias sabe dar este profe
        materias_asignadas = [pm.materia.nombre for pm in p.competencias]
        profes.append({
            'id': p.id,
            'cedula': p.cedula,
            'nombre': p.nombre,
            'max_horas_semana': p.max_horas_semana,
            'max_horas_dia': p.max_horas_dia,
            'materias': ", ".join(materias_asignadas)
        })
    return jsonify(profes)

@bp.route('/api/profesores', methods=['POST'])
def create_profesor():
    data = request.json
    with db.atomic(): # Transacción para asegurar que se guarde todo o nada
        try:
            # 1. Crear el Profesor
            p = Profesor.create(
                cedula=data['cedula'],
                nombre=data['nombre'],
                max_horas_semana=int(data['max_horas_semana']),
                max_horas_dia=int(data['max_horas_dia'])
            )
            
            # 2. Asignarle las materias seleccionadas
            # data['materias_ids'] debe ser una lista de IDs: [1, 3]
            for materia_id in data.get('materias_ids', []):
                ProfesorMateria.create(profesor=p, materia_id=materia_id)
                
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'error': str(e)}), 400
# --- API CURSOS (NUEVO) ---
from app.models import Curso # Asegúrate de importar Curso arriba

@bp.route('/api/cursos', methods=['GET', 'POST', 'DELETE'])
def manage_cursos():
    if request.method == 'POST':
        data = request.json
        try:
            # Creamos el curso combinando Nivel + Letra + Turno
            # Ej: Nivel 1, Letra A, Turno Matutino
            Curso.create(
                nivel=int(data['nivel']),
                nombre=data['letra'], # Usamos 'nombre' para la letra (A, B, C)
                turno=data['turno']
            )
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'error': 'Duplicado o error de datos'}), 400

    if request.method == 'DELETE':
        Curso.delete().where(Curso.id == request.args.get('id')).execute()
        return jsonify({'status': 'ok'})

    # Al devolver la lista, ordenamos para que se vea bonito
    cursos = Curso.select().order_by(Curso.nivel, Curso.nombre)
    return jsonify(list(cursos.dicts()))

# --- API GENERACIÓN ---
@bp.route('/api/generar', methods=['POST'])
def generar():
    resultado = generar_horario_automatico()
    if resultado['status'] == 'ok':
        return jsonify(resultado)
    else:
        return jsonify(resultado), 400

# --- API LEER HORARIO (Para el calendario) ---
@bp.route('/api/horario', methods=['GET'])
def get_horario():
    # FullCalendar necesita un formato específico
    eventos = []
    horarios = Horario.select()
    
    # Mapeo de días para fecha ficticia (FullCalendar necesita fechas tipo 2023-01-01)
    # Usaremos una semana ficticia de Lunes a Viernes
    fechas_base = {
        0: '2023-11-20', # Lunes
        1: '2023-11-21', # Martes
        2: '2023-11-22',
        3: '2023-11-23',
        4: '2023-11-24'  # Viernes
    }

    for h in horarios:
        # Formatear hora (ej: 7 -> "07:00:00")
        start = f"{h.hora_inicio:02d}:00:00"
        end = f"{h.hora_fin:02d}:00:00"
        
        titulo = f"{h.materia.nombre} ({h.aula.nombre})\n{h.profesor.nombre}\n{h.curso.nombre}"
        
        eventos.append({
            'title': titulo,
            'start': f"{fechas_base[h.dia]}T{start}",
            'end': f"{fechas_base[h.dia]}T{end}",
            'color': '#3788d8' if h.curso.turno == 'Matutino' else '#28a745'
        })
        
    return jsonify(eventos)

@bp.route('/api/profesores/<int:id>', methods=['DELETE'])
def delete_profesor(id):
    # Primero borramos sus relaciones
    ProfesorMateria.delete().where(ProfesorMateria.profesor == id).execute()
    Profesor.delete().where(Profesor.id == id).execute()
    return jsonify({'status': 'ok'})