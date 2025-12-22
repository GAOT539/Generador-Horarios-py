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
        print("--- 1. Limpiando y Generando Cursos basados en Demanda ---")
        
        with db.atomic():
            Horario.delete().execute()
            Curso.delete().execute()

        materias = list(Materia.select())
        if not materias:
            return {"status": "error", "message": "No hay materias configuradas."}

        # Lista maestra para el solver: Tuplas (ObjetoCurso, ObjetoMateria)
        # Necesitamos guardar la materia en memoria porque Curso ya no tiene FK directa en este paso
        cursos_a_asignar = []

        with db.atomic():
            for m in materias:
                try:
                    desglose = json.loads(m.desglose_horarios)
                except:
                    logger.error(f"Error leyendo JSON de materia {m.nombre}")
                    continue
                
                idx_curso = 0 # Para generar letras A, B, C...

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

                # 1.3 Procesar ONLINE FDS (Sábado y Domingo, Bloques de 4h)
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
                            dias_clase='S-D'
                        )
                        cursos_a_asignar.append({'curso': nuevo_curso, 'materia': m})
                        idx_curso += 1

        if not cursos_a_asignar:
            return {"status": "error", "message": "No se crearon cursos. Revise la configuración de demanda en 'Materias'."}

        # ==========================================
        # FASE 2: MODELADO MATEMÁTICO (CP-SAT)
        # ==========================================
        print(f"--- 2. Configurando Modelo para {len(cursos_a_asignar)} cursos ---")
        
        profesores = list(Profesor.select())
        model = cp_model.CpModel()
        
        # Estructuras de datos
        # asignaciones[(id_curso, id_profe)] = variable_bool
        asignaciones = {} 
        
        # Para controlar choques: profe_id -> clave_horario -> [lista de vars]
        # clave_horario ejemplo: "L-J_7" (LunesJueves a las 7)
        mapa_choques = {p.id: {} for p in profesores}
        
        # Para controlar carga horaria: profe_id -> [lista de vars con peso 8h]
        mapa_carga = {p.id: [] for p in profesores}

        # Cache de competencias para rapidez: {profe_id: {id_materia1, id_materia2...}}
        competencias_cache = {}
        for p in profesores:
            competencias_cache[p.id] = {pm.materia.id for pm in p.competencias}

        # CREACIÓN DE VARIABLES Y RESTRICCIONES BÁSICAS
        for item in cursos_a_asignar:
            c = item['curso']
            m = item['materia']
            
            # Buscar candidatos (Profes que sepan la materia)
            candidatos = [p for p in profesores if m.id in competencias_cache[p.id]]
            
            if not candidatos:
                msg = f"ERROR CRÍTICO: El curso {m.nombre} Nivel {m.nivel} ({c.dias_clase} {c.bloque_horario}:00) no tiene profesores aptos disponibles."
                logger.error(msg)
                return {"status": "error", "message": msg}

            vars_este_curso = []
            
            for p in candidatos:
                # Variable principal: ¿El profe P da el curso C?
                var = model.NewBoolVar(f'c{c.id}_p{p.id}')
                asignaciones[(c.id, p.id)] = var
                vars_este_curso.append(var)
                
                # Agrupar para validación de choques
                clave_horario = f"{c.dias_clase}_{c.bloque_horario}" # Ej: L-J_7 o S-D_7
                if clave_horario not in mapa_choques[p.id]:
                    mapa_choques[p.id][clave_horario] = []
                mapa_choques[p.id][clave_horario].append(var)
                
                # Agrupar para carga horaria (Cada curso = 8 horas semanales aprox)
                mapa_carga[p.id].append(var)

            # R1: Todo curso debe tener EXACTAMENTE un profesor
            model.Add(sum(vars_este_curso) == 1)

        # RESTRICCIONES POR PROFESOR
        for p in profesores:
            # R2: Cruce de Horarios (Un profe no puede estar en 2 lugares a la vez)
            for clave, lista_vars in mapa_choques[p.id].items():
                if len(lista_vars) > 1:
                    # Si hay varios cursos posibles en el mismo hueco (L-J_7), solo puede tomar 1
                    model.Add(sum(lista_vars) <= 1)
            
            # R3: Carga Horaria Máxima
            # Asumimos peso estándar de 8 horas por curso (4 días x 2h o 2 días x 4h)
            if mapa_carga[p.id]:
                model.Add(sum(mapa_carga[p.id]) * 8 <= p.max_horas_semana)

        # ==========================================
        # FASE 3: RESOLUCIÓN
        # ==========================================
        print("--- 3. Ejecutando Solver ---")
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60.0
        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print(f"¡Solución encontrada! ({solver.StatusName(status)})")
            
            count = 0
            with db.atomic():
                for (c_id, p_id), var in asignaciones.items():
                    if solver.Value(var) == 1:
                        # Recuperar datos originales de la lista
                        item = next(x for x in cursos_a_asignar if x['curso'].id == c_id)
                        curso = item['curso']
                        materia = item['materia']
                        
                        # Determinar días y duración según el tipo de curso
                        dias_db = []
                        duracion_bloque = 0
                        
                        if curso.dias_clase == 'L-J':
                            dias_db = [0, 1, 2, 3] # Lunes, Martes, Miercoles, Jueves
                            duracion_bloque = 2
                        elif curso.dias_clase == 'S-D':
                            dias_db = [5, 6] # Sabado, Domingo
                            duracion_bloque = 4
                        
                        # Guardar en tabla Horario (Desglosado por día para el calendario)
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
            
            print(f"--- Proceso Finalizado. {count} cursos asignados. ---")
            return {"status": "ok", "message": f"Horario generado exitosamente. {count} cursos asignados."}
        
        elif status == cp_model.INFEASIBLE:
            msg = "Imposible generar horario: Faltan profesores para cubrir la demanda en ciertas franjas horarias."
            logger.error(msg)
            return {"status": "error", "message": msg}
        else:
            return {"status": "error", "message": "Tiempo de espera agotado sin solución."}

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.critical(f"Excepción en solver: {str(e)}\n{error_detail}")
        return {"status": "error", "message": f"Error interno: {str(e)}"}