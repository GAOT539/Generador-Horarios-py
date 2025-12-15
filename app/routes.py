from flask import Blueprint, render_template, request, jsonify
from app.models import Profesor, Materia, ProfesorMateria, db, Horario, Curso
from app.engine.solver import generar_horario_automatico

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/config')
def config():
    return render_template('config.html')

# --- API MATERIAS ---
@bp.route('/api/materias', methods=['GET', 'POST', 'DELETE'])
def manage_materias():
    if request.method == 'POST':
        data = request.json
        try:
            Materia.create(
                nombre=data['nombre'],
                nivel=int(data['nivel']),
                cantidad_grupos=int(data['cantidad'])
            )
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'error': 'Duplicado o error de datos'}), 400
            
    if request.method == 'DELETE':
        materia_id = request.args.get('id')
        ProfesorMateria.delete().where(ProfesorMateria.materia == materia_id).execute()
        Materia.delete().where(Materia.id == materia_id).execute()
        return jsonify({'status': 'ok'})

    materias = Materia.select().order_by(Materia.nombre, Materia.nivel)
    lista = []
    for m in materias:
        lista.append({
            'id': m.id,
            'nombre': m.nombre,
            'nivel': m.nivel,
            'cantidad_grupos': m.cantidad_grupos,
            'nombre_completo': f"{m.nombre} (Nivel {m.nivel})"
        })
    return jsonify(lista)

# --- API PROFESORES ---
@bp.route('/api/profesores', methods=['GET'])
def get_profesores():
    profes = []
    for p in Profesor.select():
        # CAMBIO AQUÍ: Agregamos el nivel al texto (Ej: "INGLES 1")
        materias_asignadas = [f"{pm.materia.nombre} {pm.materia.nivel}" for pm in p.competencias]
        
        profes.append({
            'id': p.id,
            'nombre': p.nombre,
            'max_horas_semana': p.max_horas_semana,
            'max_horas_dia': p.max_horas_dia,
            'materias': ", ".join(materias_asignadas)
        })
    return jsonify(profes)

@bp.route('/api/profesores', methods=['POST'])
def create_profesor():
    data = request.json
    with db.atomic():
        try:
            p = Profesor.create(
                nombre=data['nombre'],
                max_horas_semana=int(data['max_horas_semana']),
                max_horas_dia=int(data['max_horas_dia'])
            )
            for materia_id in data.get('materias_ids', []):
                ProfesorMateria.create(profesor=p, materia_id=materia_id)
            return jsonify({'status': 'ok'})
        except Exception as e:
            return jsonify({'error': str(e)}), 400

@bp.route('/api/profesores/<int:id>', methods=['DELETE'])
def delete_profesor(id):
    ProfesorMateria.delete().where(ProfesorMateria.profesor == id).execute()
    Profesor.delete().where(Profesor.id == id).execute()
    return jsonify({'status': 'ok'})

# --- API CURSOS ---
@bp.route('/api/cursos', methods=['GET', 'POST', 'DELETE'])
def manage_cursos():
    if request.method == 'POST':
        data = request.json
        try:
            Curso.create(
                nivel=int(data['nivel']),
                nombre=data['letra'],
                turno=data['turno']
            )
            return jsonify({'status': 'ok'})
        except Exception:
            return jsonify({'error': 'Duplicado'}), 400

    if request.method == 'DELETE':
        Curso.delete().where(Curso.id == request.args.get('id')).execute()
        return jsonify({'status': 'ok'})

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

# --- API LEER HORARIO ---
@bp.route('/api/horario', methods=['GET'])
def get_horario():
    eventos = []
    horarios = Horario.select().join(Materia).switch(Horario).join(Profesor).switch(Horario).join(Curso)
    
    fechas_base = { 0: '2023-11-20', 1: '2023-11-21', 2: '2023-11-22', 3: '2023-11-23', 4: '2023-11-24' }

    for h in horarios:
        start = f"{h.hora_inicio:02d}:00:00"
        end = f"{h.hora_fin:02d}:00:00"
        
        # Formato (A) INGLES 1 JUAN PEREZ
        titulo = f"({h.curso.nombre}) {h.materia.nombre} {h.materia.nivel}\n{h.profesor.nombre}"
        
        eventos.append({
            'title': titulo,
            'start': f"{fechas_base[h.dia]}T{start}",
            'end': f"{fechas_base[h.dia]}T{end}",
            'color': '#3788d8' if h.curso.turno == 'Matutino' else '#28a745'
        })
        
    return jsonify(eventos)