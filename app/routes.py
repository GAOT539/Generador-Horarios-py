from flask import Blueprint, render_template, request, jsonify
from app.models import Profesor, Materia, Aula, ProfesorMateria, db

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

# --- API MATERIAS ---
@bp.route('/api/materias', methods=['GET', 'POST', 'DELETE'])
def manage_materias():
    if request.method == 'POST':
        try:
            Materia.create(nombre=request.json['nombre'])
            return jsonify({'status': 'ok'})
        except:
            return jsonify({'error': 'Duplicado'}), 400
            
    if request.method == 'DELETE':
        Materia.delete().where(Materia.id == request.args.get('id')).execute()
        return jsonify({'status': 'ok'})

    return jsonify(list(Materia.select().dicts()))

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

@bp.route('/api/profesores/<int:id>', methods=['DELETE'])
def delete_profesor(id):
    # Primero borramos sus relaciones
    ProfesorMateria.delete().where(ProfesorMateria.profesor == id).execute()
    Profesor.delete().where(Profesor.id == id).execute()
    return jsonify({'status': 'ok'})