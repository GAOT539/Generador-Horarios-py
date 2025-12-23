from flask import Blueprint, render_template, request, jsonify, Response, current_app
from app.models import Profesor, Materia, ProfesorMateria, db, Horario, Curso
from app.engine.solver import generar_horario_automatico
import json
import traceback

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    return render_template('index.html')

@bp.route('/calendario')
def calendario():
    return render_template('calendario.html')

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
            # Convertimos el objeto JSON del frontend a string para guardarlo en la BD
            desglose_str = json.dumps(data['desglose'])
            
            Materia.create(
                nombre=data['nombre'],
                nivel=int(data['nivel']),
                desglose_horarios=desglose_str
            )
            return jsonify({'status': 'ok'})
        except Exception as e:
            current_app.logger.error(f"Error creando materia: {str(e)}")
            return jsonify({'error': str(e)}), 400
            
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
        # Recuperamos el desglose. Si es antiguo o falla, usamos default vacío.
        try:
            desglose = json.loads(m.desglose_horarios)
        except:
            desglose = {"PRESENCIAL":{}, "ONLINE_LJ":{}, "ONLINE_FDS":{}}

        # Calculamos totales al vuelo para visualización
        total_reg = sum(desglose.get('PRESENCIAL', {}).values())
        total_on_lj = sum(desglose.get('ONLINE_LJ', {}).values())
        total_on_fds = sum(desglose.get('ONLINE_FDS', {}).values())

        lista.append({
            'id': m.id,
            'nombre': m.nombre,
            'nivel': m.nivel,
            'cantidad_regular': total_reg,     # Calculado para la vista
            'cantidad_online_lj': total_on_lj, # Calculado para la vista
            'cantidad_online_fds': total_on_fds, # Calculado para la vista
            'nombre_completo': f"{m.nombre} (Nivel {m.nivel})",
            'desglose': desglose # Enviamos el detalle por si se necesita
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
            current_app.logger.error(f"Error creando profesor: {str(e)}")
            return jsonify({'error': str(e)}), 400

@bp.route('/api/profesores/<int:id>', methods=['PUT'])
def update_profesor(id):
    data = request.json
    try:
        query = Profesor.update(nombre=data['nombre']).where(Profesor.id == id)
        query.execute()
        return jsonify({'status': 'ok'})
    except Exception as e:
        current_app.logger.error(f"Error actualizando profesor {id}: {str(e)}")
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
        current_app.logger.error(f"Error eliminando profesor {id}: {str(e)}")
        return jsonify({'error': f"Error al borrar: {str(e)}"}), 400

# --- API CURSOS ---
@bp.route('/api/cursos', methods=['GET', 'POST', 'DELETE'])
def manage_cursos():
    if request.method == 'POST':
        data = request.json
        try:
            Curso.create(
                nivel=int(data['nivel']),
                nombre=data['letra'],
                turno=data['turno'],
                modalidad=data.get('modalidad', 'REGULAR')
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
    current_app.logger.info("Solicitud de generación de horario recibida.")
    try:
        resultado = generar_horario_automatico()
        
        if resultado['status'] == 'ok':
            current_app.logger.info("Horario generado exitosamente.")
            return jsonify(resultado)
        else:
            current_app.logger.warning(f"Fallo en generación: {resultado['message']}")
            return jsonify(resultado), 400
            
    except Exception as e:
        err_msg = f"Error no controlado en motor: {str(e)}"
        current_app.logger.critical(err_msg + "\n" + traceback.format_exc())
        # CORRECCIÓN: Devolver mensaje específico del error para que Swal lo muestre
        return jsonify({"status": "error", "message": f"Error interno: {str(e)}"}), 500

# --- API LEER HORARIO ---
@bp.route('/api/horario', methods=['GET'])
def get_horario():
    eventos = []
    horarios = Horario.select().join(Materia).switch(Horario).join(Profesor).switch(Horario).join(Curso)
    
    # Fechas Base (Semana Lunes 20 a Domingo 26)
    fechas_base = { 
        0: '2023-11-20', 1: '2023-11-21', 2: '2023-11-22', 
        3: '2023-11-23', 4: '2023-11-24', 5: '2023-11-25', 
        6: '2023-11-26'
    }

    for h in horarios:
        if h.dia not in fechas_base: continue
        
        start = f"{h.hora_inicio:02d}:00:00"
        end = f"{h.hora_fin:02d}:00:00"
        
        # --- FORMATO Y COLORES ---
        mod_tag = ""
        color = '#3788d8' # Default Azul

        if 'ONLINE' in h.curso.modalidad:
            mod_tag = "[ON]"
            if 'FDS' in h.curso.modalidad:
                color = '#fd7e14' # Naranja Online FDS
            else:
                color = '#6f42c1' # Morado Online LJ
        else:
            # Presencial
            if h.curso.turno == 'Vespertino':
                color = '#28a745' # Verde Tarde
            else:
                color = '#3788d8' # Azul Mañana

        tag_str = f"{mod_tag} " if mod_tag else ""
        titulo = f"{tag_str}{h.materia.nombre} - {h.materia.nivel} ({h.curso.nombre})\n{h.profesor.nombre}"
        
        eventos.append({
            'title': titulo,
            'start': f"{fechas_base[h.dia]}T{start}",
            'end': f"{fechas_base[h.dia]}T{end}",
            'color': color,
            'extendedProps': {
                'materia_id': h.materia.id,
                'profesor_id': h.profesor.id,
                'curso_turno': h.curso.turno,
                'modalidad': h.curso.modalidad,
                'curso_nombre': h.curso.nombre
            }
        })
        
    return jsonify(eventos)

# --- API ESTADISTICAS ---
@bp.route('/api/estadisticas', methods=['GET'])
def get_estadisticas():
    # 1. Datos base de profesores
    asignaciones = Horario.select()
    profesores = Profesor.select()
    reporte = []
    
    total_capacidad_horas = 0
    total_horas_asignadas = 0

    for p in profesores:
        horas_reales = 0
        mis_horarios = [x for x in asignaciones if x.profesor.id == p.id]
        for mh in mis_horarios:
            duracion = mh.hora_fin - mh.hora_inicio
            horas_reales += duracion

        total_capacidad_horas += p.max_horas_semana
        total_horas_asignadas += horas_reales

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

    # 2. Análisis Avanzado (Cursos Únicos)
    # Agrupar horarios por Curso ID para no contar bloques individuales como cursos distintos
    cursos_unicos_query = (Horario
                           .select(Horario.curso, Curso.modalidad, Curso.turno, Materia.nombre)
                           .join(Curso, on=(Horario.curso == Curso.id))
                           .switch(Horario)
                           .join(Materia, on=(Horario.materia == Materia.id))
                           .group_by(Horario.curso, Curso.modalidad, Curso.turno, Materia.nombre))

    stats_modalidad = {'REGULAR': 0, 'ONLINE_LJ': 0, 'ONLINE_FDS': 0}
    stats_turno = {'Matutino': 0, 'Vespertino': 0, 'Nocturno': 0, 'FDS': 0}
    stats_materias = {}

    for entry in cursos_unicos_query:
        # Modalidad
        mod = entry.curso.modalidad
        if mod in stats_modalidad:
            stats_modalidad[mod] += 1
        else:
            # Fallback para modalidades antiguas si existieran
            stats_modalidad[mod] = 1
        
        # Turno
        turno = entry.curso.turno
        if turno in stats_turno:
            stats_turno[turno] += 1
        else:
            stats_turno[turno] = 1
            
        # Materia
        mat_nombre = entry.materia.nombre
        stats_materias[mat_nombre] = stats_materias.get(mat_nombre, 0) + 1

    # Top 5 Materias
    top_materias = sorted(stats_materias.items(), key=lambda x: x[1], reverse=True)[:5]

    return jsonify({
        'profesores': reporte,
        'resumen': {
            'total_profesores': len(profesores),
            'total_materias': len(stats_materias),
            'total_cursos': cursos_unicos_query.count(),
            'ocupacion_global_pct': round((total_horas_asignadas / total_capacidad_horas * 100), 1) if total_capacidad_horas > 0 else 0,
            'distribucion_modalidad': stats_modalidad,
            'distribucion_turno': stats_turno,
            'top_materias': top_materias
        }
    })

# --- BACKUP ---
@bp.route('/api/backup', methods=['GET'])
def backup_data():
    try:
        # Recuperamos materias con su nuevo campo
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
    except Exception as e:
        current_app.logger.error(f"Error generando backup: {str(e)}")
        return jsonify({'error': str(e)}), 500

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
                # Restauración con soporte para el nuevo campo desglose
                Materia.create(
                    nombre=m['nombre'], nivel=m['nivel'],
                    desglose_horarios=m.get('desglose_horarios', '{}') 
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
    except Exception as e:
        current_app.logger.error(f"Error restaurando backup: {str(e)}")
        return jsonify({'error': str(e)}), 500