from flask import Blueprint, render_template, request, jsonify, Response
from app.models import Profesor, Materia, ProfesorMateria, db, Horario, Curso
from app.engine.solver import generar_horario_automatico
import json

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/config')
def config():
    return render_template('config.html')

@bp.route('/reportes')
def reportes():
    return render_template('reportes.html')

# --- API MATERIAS ---
@bp.route('/api/materias', methods=['GET', 'POST', 'DELETE'])
def manage_materias():
    if request.method == 'POST':
        data = request.json
        try:
            # CAMBIO: Guardamos regular y online por separado
            Materia.create(
                nombre=data['nombre'],
                nivel=int(data['nivel']),
                cantidad_regular=int(data['cantidad_regular']),
                cantidad_online=int(data['cantidad_online'])
            )
            return jsonify({'status': 'ok'})
        except Exception:
            return jsonify({'error': 'Duplicado o error de datos'}), 400
            
    if request.method == 'DELETE':
        materia_id = request.args.get('id')
        with db.atomic():
            Horario.delete().where(Horario.materia == materia_id).execute()
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
            # CAMBIO: Enviamos los dos valores al frontend
            'cantidad_regular': m.cantidad_regular,
            'cantidad_online': m.cantidad_online,
            'nombre_completo': f"{m.nombre} (Nivel {m.nivel})"
        })
    return jsonify(lista)

# --- API PROFESORES ---
@bp.route('/api/profesores', methods=['GET'])
def get_profesores():
    profes = []
    for p in Profesor.select():
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
    if Profesor.select().where(Profesor.nombre == data['nombre']).exists():
        return jsonify({'error': f"El profesor {data['nombre']} ya existe."}), 400

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

@bp.route('/api/profesores/<int:id>', methods=['PUT'])
def update_profesor(id):
    data = request.json
    try:
        query = Profesor.update(nombre=data['nombre']).where(Profesor.id == id)
        query.execute()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@bp.route('/api/profesores/<int:id>', methods=['DELETE'])
def delete_profesor(id):
    try:
        with db.atomic():
            Horario.delete().where(Horario.profesor == id).execute()
            ProfesorMateria.delete().where(ProfesorMateria.profesor == id).execute()
            Profesor.delete().where(Profesor.id == id).execute()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': f"Error al borrar: {str(e)}"}), 400

# --- API CURSOS ---
@bp.route('/api/cursos', methods=['GET', 'POST', 'DELETE'])
def manage_cursos():
    # Nota: Esta ruta es para gestión manual, el solver usa su propia lógica.
    # Actualizaremos la creación manual si es necesario, pero el solver es el principal.
    if request.method == 'POST':
        data = request.json
        try:
            Curso.create(
                nivel=int(data['nivel']),
                nombre=data['letra'],
                turno=data['turno'],
                modalidad=data.get('modalidad', 'REGULAR') # Default
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
    
    fechas_base = { 
        0: '2023-11-20', 1: '2023-11-21', 2: '2023-11-22', 3: '2023-11-23'
    }

    for h in horarios:
        if h.dia not in fechas_base: continue
        
        start = f"{h.hora_inicio:02d}:00:00"
        end = f"{h.hora_fin:02d}:00:00"
        
        # Mostramos la modalidad en el título para diferenciar
        mod_tag = "[OL]" if h.curso.modalidad == 'ONLINE' else ""
        titulo = f"{mod_tag} ({h.curso.nombre}) {h.materia.nombre} {h.materia.nivel}\n{h.profesor.nombre}"
        
        # Color diferente para online si se desea, o mantenemos turno
        color = '#3788d8' if h.curso.turno == 'Matutino' else '#28a745'
        if h.curso.modalidad == 'ONLINE':
            color = '#6f42c1' # Morado para Online (opcional, visual)

        eventos.append({
            'title': titulo,
            'start': f"{fechas_base[h.dia]}T{start}",
            'end': f"{fechas_base[h.dia]}T{end}",
            'color': color,
            'extendedProps': {
                'materia_id': h.materia.id,
                'profesor_id': h.profesor.id,
                'curso_turno': h.curso.turno,
                'modalidad': h.curso.modalidad
            }
        })
        
    return jsonify(eventos)

# --- API ESTADISTICAS ---
@bp.route('/api/estadisticas', methods=['GET'])
def get_estadisticas():
    conteo_bloques = {}
    asignaciones = Horario.select()
    
    for h in asignaciones:
        p_id = h.profesor.id
        if p_id not in conteo_bloques: conteo_bloques[p_id] = 0
        conteo_bloques[p_id] += 1

    profesores = Profesor.select()
    reporte = []
    
    for p in profesores:
        bloques_asignados = conteo_bloques.get(p.id, 0)
        horas_reales = bloques_asignados * 2 
        
        estado = "OK"
        if horas_reales == 0: estado = "SIN_CARGA"
        elif horas_reales > p.max_horas_semana: estado = "SOBRECARGA"
        elif horas_reales < (p.max_horas_semana * 0.5): estado = "SUBUTILIZADO"

        reporte.append({
            'id': p.id, 'nombre': p.nombre,
            'horas_asignadas': horas_reales, 'horas_maximas': p.max_horas_semana,
            'estado': estado,
            'porcentaje': round((horas_reales / p.max_horas_semana) * 100, 1) if p.max_horas_semana > 0 else 0
        })

    return jsonify({
        'profesores': reporte,
        'resumen': {
            'total_profesores': len(profesores),
            'total_clases_semanales': len(asignaciones),
            'profesores_sin_carga': len([x for x in reporte if x['estado'] == 'SIN_CARGA'])
        }
    })

# --- BACKUP ---
@bp.route('/api/backup', methods=['GET'])
def backup_data():
    materias = list(Materia.select().dicts())
    profesores_data = []
    for p in Profesor.select():
        competencias = [f"{pm.materia.nombre}|{pm.materia.nivel}" for pm in p.competencias]
        profesores_data.append({
            'nombre': p.nombre,
            'max_horas_semana': p.max_horas_semana,
            'max_horas_dia': p.max_horas_dia,
            'competencias': competencias
        })

    backup = {
        'system_signature': 'GENERADOR_HORARIOS_V1',
        'materias': materias,
        'profesores': profesores_data
    }
    
    return Response(json.dumps(backup, indent=2), mimetype="application/json",
        headers={"Content-disposition": "attachment; filename=respaldo_configuracion.json"})

@bp.route('/api/restore', methods=['POST'])
def restore_data():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['file']
    try:
        data = json.load(file)
        if data.get('system_signature') != 'GENERADOR_HORARIOS_V1':
            return jsonify({'error': 'Firma inválida.'}), 400
        
        with db.atomic():
            Horario.delete().execute()
            ProfesorMateria.delete().execute()
            Profesor.delete().execute()
            Materia.delete().execute()
            Curso.delete().execute()

            for m in data['materias']:
                Materia.create(
                    nombre=m['nombre'], nivel=m['nivel'],
                    # CAMBIO: Restaurar nuevos campos (con fallback por si es backup viejo)
                    cantidad_regular=m.get('cantidad_regular', m.get('cantidad_grupos', 0)),
                    cantidad_online=m.get('cantidad_online', 0)
                )

            for p in data['profesores']:
                nuevo_profe = Profesor.create(
                    nombre=p['nombre'],
                    max_horas_semana=p['max_horas_semana'],
                    max_horas_dia=p['max_horas_dia']
                )
                for comp_str in p['competencias']:
                    nombre_mat, nivel_mat = comp_str.split('|')
                    materia_obj = Materia.get_or_none((Materia.nombre == nombre_mat) & (Materia.nivel == int(nivel_mat)))
                    if materia_obj:
                        ProfesorMateria.create(profesor=nuevo_profe, materia=materia_obj)
        
        return jsonify({'status': 'ok', 'message': 'Restaurado.'})
    except Exception as e: return jsonify({'error': str(e)}), 500