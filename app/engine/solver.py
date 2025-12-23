import logging
import traceback
import json
from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria, db

# Configurar logger
logger = logging.getLogger(__name__)

def generar_etiqueta_curso(n):
    """Genera letras A, B... AA, AB... para los cursos."""
    result = ""
    while n >= 0:
        result = chr(65 + (n % 26)) + result
        n = (n // 26) - 1
    return result

def generar_horario_automatico():
    logger.info("--- Iniciando Motor de Asignación (Horarios Fijos) ---")
    
    try:
        # ==========================================
        # FASE 1: PREPARACIÓN Y GENERACIÓN DE INSTANCIAS
        # ==========================================
        logger.info("--- 1. Limpiando y Generando Cursos basados en Demanda ---")
        
        with db.atomic():
            Horario.delete().execute()
            Curso.delete().execute()

        materias = list(Materia.select())
        if not materias:
            return {"status": "error", "message": "No hay materias configuradas."}

        # Lista maestra para el solver: Tuplas (ObjetoCurso, ObjetoMateria)
        cursos_a_asignar = []

        with db.atomic():
            for m in materias:
                try:
                    desglose = json.loads(m.desglose_horarios)
                except:
                    logger.error(f"Error leyendo JSON de materia {m.nombre}")
                    continue
                
                idx_curso = 0 

                # 1.1 Procesar PRESENCIAL (Lunes a Jueves, Bloques de 2h)
                for hora_str, cantidad in desglose.get("PRESENCIAL", {}).items():
                    cant = int(cantidad)
                    hora = int(hora_str)
                    for _ in range(cant):
                        nuevo_curso = Curso.create(
                            nombre=generar_etiqueta_curso(idx_curso),
                            nivel=m.nivel,
                            turno='Matutino' if hora < 13 else 'Vespertino',
                            modalidad='PRESENCIAL',
                            bloque_horario=hora,
                            dias_clase='L-J'
                        )
                        cursos_a_asignar.append({'curso': nuevo_curso, 'materia': m})
                        idx_curso += 1

                # 1.2 Procesar ONLINE L-J (Lunes a Jueves, Bloques de 2h)
                for hora_str, cantidad in desglose.get("ONLINE_LJ", {}).items():
                    cant = int(cantidad)
                    hora = int(hora_str)
                    for _ in range(cant):
                        turno = 'Nocturno' if hora >= 19 else ('Matutino' if hora < 13 else 'Vespertino')
                        nuevo_curso = Curso.create(
                            nombre=generar_etiqueta_curso(idx_curso),
                            nivel=m.nivel,
                            turno=turno,
                            modalidad='ONLINE_LJ',
                            bloque_horario=hora,
                            dias_clase='L-J'
                        )
                        cursos_a_asignar.append({'curso': nuevo_curso, 'materia': m})
                        idx_curso += 1

                # 1.3 Procesar ONLINE FDS (Solo Sábado, Bloque único 8h)
                for hora_str, cantidad in desglose.get("ONLINE_FDS", {}).items():
                    cant = int(cantidad)
                    hora = int(hora_str)
                    for _ in range(cant):
                        nuevo_curso = Curso.create(
                            nombre=generar_etiqueta_curso(idx_curso),
                            nivel=m.nivel,
                            turno='FDS',
                            modalidad='ONLINE_FDS',
                            bloque_horario=hora,
                            dias_clase='S' # Solo Sábado
                        )
                        cursos_a_asignar.append({'curso': nuevo_curso, 'materia': m})
                        idx_curso += 1

        if not cursos_a_asignar:
            return {"status": "error", "message": "No se crearon cursos. Revise la configuración de demanda en 'Materias'."}

        # ==========================================
        # FASE 2: MODELADO MATEMÁTICO (CP-SAT)
        # ==========================================
        logger.info(f"--- 2. Configurando Modelo para {len(cursos_a_asignar)} cursos ---")
        
        profesores = list(Profesor.select())
        model = cp_model.CpModel()
        
        asignaciones = {} 
        
        # Estructuras de control
        mapa_choques = {p.id: {} for p in profesores}
        
        # CORRECCIÓN: Separamos carga semanal (total) y carga diaria (solo L-J)
        carga_semanal = {p.id: [] for p in profesores}
        carga_diaria_lj = {p.id: [] for p in profesores}

        competencias_cache = {}
        for p in profesores:
            competencias_cache[p.id] = {pm.materia.id for pm in p.competencias}

        for item in cursos_a_asignar:
            c = item['curso']
            m = item['materia']
            
            candidatos = [p for p in profesores if m.id in competencias_cache[p.id]]
            
            if not candidatos:
                msg = f"ERROR CRÍTICO: El curso {m.nombre} Nivel {m.nivel} ({c.dias_clase} {c.bloque_horario}:00) no tiene profesores aptos disponibles."
                logger.error(msg)
                return {"status": "error", "message": msg}

            vars_este_curso = []
            
            for p in candidatos:
                var = model.NewBoolVar(f'c{c.id}_p{p.id}')
                asignaciones[(c.id, p.id)] = var
                vars_este_curso.append(var)
                
                # Choques
                clave_horario = f"{c.dias_clase}_{c.bloque_horario}"
                if clave_horario not in mapa_choques[p.id]:
                    mapa_choques[p.id][clave_horario] = []
                mapa_choques[p.id][clave_horario].append(var)
                
                # Carga Semanal (Todos los cursos suman 8 horas a la semana)
                # L-J: 2h * 4 dias = 8h
                # S: 8h * 1 dia = 8h
                carga_semanal[p.id].append(var)

                # Carga Diaria (Solo cursos L-J suman horas al día laboral)
                if c.dias_clase == 'L-J':
                    carga_diaria_lj[p.id].append(var)

            model.Add(sum(vars_este_curso) == 1)

        # RESTRICCIONES POR PROFESOR
        for p in profesores:
            # 1. Evitar Choques
            for clave, lista_vars in mapa_choques[p.id].items():
                if len(lista_vars) > 1:
                    model.Add(sum(lista_vars) <= 1)
            
            # 2. Carga Semanal Máxima (32h)
            if carga_semanal[p.id]:
                model.Add(sum(carga_semanal[p.id]) * 8 <= p.max_horas_semana)

            # 3. Carga Diaria Máxima (Solo Lunes a Jueves)
            # Cada curso L-J aporta 2 horas al día
            if carga_diaria_lj[p.id]:
                model.Add(sum(carga_diaria_lj[p.id]) * 2 <= p.max_horas_dia)
            # NOTA: Los cursos de Sábado ('S') NO entran en esta restricción diaria

        # ==========================================
        # FASE 3: RESOLUCIÓN
        # ==========================================
        logger.info("--- 3. Ejecutando Solver ---")
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0
        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            logger.info(f"¡Solución encontrada! ({solver.StatusName(status)})")
            
            count = 0
            with db.atomic():
                for (c_id, p_id), var in asignaciones.items():
                    if solver.Value(var) == 1:
                        item = next(x for x in cursos_a_asignar if x['curso'].id == c_id)
                        curso = item['curso']
                        materia = item['materia']
                        
                        dias_db = []
                        duracion_bloque = 0
                        
                        if curso.dias_clase == 'L-J':
                            dias_db = [0, 1, 2, 3] 
                            duracion_bloque = 2
                        elif curso.dias_clase == 'S': 
                            dias_db = [5] # Sábado
                            duracion_bloque = 8 # 08:00 a 16:00 interno
                        
                        for dia_num in dias_db:
                            Horario.create(
                                dia=dia_num,
                                hora_inicio=curso.bloque_horario,
                                hora_fin=curso.bloque_horario + duracion_bloque,
                                profesor_id=p_id,
                                materia_id=materia.id,
                                curso_id=curso.id
                            )
                        count += 1
            
            msg = f"Horario generado exitosamente. {count} cursos asignados."
            logger.info(msg)
            return {"status": "ok", "message": msg}
        
        elif status == cp_model.INFEASIBLE:
            msg = "Imposible generar: No hay suficientes profesores con disponibilidad horaria o de carga para cubrir la demanda."
            logger.error(msg)
            return {"status": "error", "message": msg}
        else:
            return {"status": "error", "message": "Tiempo de espera agotado sin solución."}

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.critical(f"Excepción en solver: {str(e)}\n{error_detail}")
        return {"status": "error", "message": f"Error interno en motor: {str(e)}"}