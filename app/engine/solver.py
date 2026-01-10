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

def validar_recursos(cursos, profesores):
    """
    Verifica disponibilidad de profesores antes de intentar resolver.
    Lanza excepción con mensaje detallado si faltan recursos.
    """
    demanda_por_slot = {}
    demanda_horas_total = {}

    for item in cursos:
        c = item['curso']
        m = item['materia']
        key_horario = f"{c.dias_clase}_{c.bloque_horario}"
        
        if key_horario not in demanda_por_slot: 
            demanda_por_slot[key_horario] = {}
        
        mat_key = (m.nombre, m.nivel)
        demanda_por_slot[key_horario][mat_key] = demanda_por_slot[key_horario].get(mat_key, 0) + 1

        horas_curso = 8 # Estándar semanal
        demanda_horas_total[mat_key] = demanda_horas_total.get(mat_key, 0) + horas_curso

    # Validación 1: Cobertura por Slot
    for slot, demandas in demanda_por_slot.items():
        for (nombre_mat, nivel_mat), requeridos in demandas.items():
            aptos = 0
            for p in profesores:
                tiene_comp = any(pm.materia.nombre == nombre_mat and pm.materia.nivel == nivel_mat for pm in p.competencias)
                if tiene_comp:
                    aptos += 1
            
            if aptos < requeridos:
                dias, hora = slot.split('_')
                hora_fmt = f"{hora}:00"
                raise Exception(f"Imposible generar: No hay suficientes profesores con disponibilidad para cubrir la demanda en {nombre_mat} Nivel {nivel_mat} en el horario {dias} {hora_fmt}. (Se necesitan {requeridos}, hay {aptos} competentes en total).")

    # Validación 2: Capacidad Total
    for (nombre_mat, nivel_mat), horas_necesarias in demanda_horas_total.items():
        capacidad_total_materia = 0
        for p in profesores:
             if any(pm.materia.nombre == nombre_mat and pm.materia.nivel == nivel_mat for pm in p.competencias):
                 capacidad_total_materia += p.max_horas_semana
        
        if capacidad_total_materia < horas_necesarias:
             raise Exception(f"Imposible generar: La carga horaria solicitada para {nombre_mat} Nivel {nivel_mat} ({horas_necesarias} horas) supera la capacidad máxima combinada de los profesores disponibles ({capacidad_total_materia} horas). Es necesario subir horas a los profesores.")

def generar_horario_automatico():
    logger.info("--- Iniciando Motor de Asignación Optima ---")
    
    try:
        # ==========================================
        # FASE 1: LIMPIEZA Y GENERACIÓN DE INSTANCIAS
        # ==========================================
        logger.info("--- 1. Generando Cursos basados en Demanda ---")
        
        with db.atomic():
            Horario.delete().execute()
            Curso.delete().execute()

        materias = list(Materia.select())
        if not materias:
            return {"status": "error", "message": "No hay materias configuradas."}

        cursos_a_asignar = []

        with db.atomic():
            for m in materias:
                try:
                    desglose = json.loads(m.desglose_horarios)
                except:
                    logger.error(f"Error leyendo JSON de materia {m.nombre}")
                    continue
                
                idx_curso = 0 

                # 1.1 PRESENCIAL (Lunes-Jueves)
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

                # 1.2 ONLINE L-J
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

                # 1.3 ONLINE FDS
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
                            dias_clase='S'
                        )
                        cursos_a_asignar.append({'curso': nuevo_curso, 'materia': m})
                        idx_curso += 1

        if not cursos_a_asignar:
            return {"status": "error", "message": "No se crearon cursos. Revise la configuración de demanda."}

        # ==========================================
        # FASE 2: PRE-VALIDACIÓN
        # ==========================================
        profesores = list(Profesor.select())
        validar_recursos(cursos_a_asignar, profesores)

        # ==========================================
        # FASE 3: MODELADO CP-SAT
        # ==========================================
        logger.info(f"--- 3. Configurando Modelo para {len(cursos_a_asignar)} cursos ---")
        
        model = cp_model.CpModel()
        
        # Variables de asignación: asignaciones[(id_curso, id_profe)]
        asignaciones = {} 
        
        # Estructuras auxiliares
        # Mapa de Slots L-J para validación de huecos/modalidad
        # Indices: 7:0, 9:1, 11:2, 13:3, 15:4, 17:5, 19:6
        slots_lj_map = {7:0, 9:1, 11:2, 13:3, 15:4, 17:5, 19:6}
        num_slots_lj = 7
        
        # Variables por profesor para controlar carga y modalidad
        # prof_vars[p_id]['lj_pres'][slot_idx] = BoolVar
        prof_vars = {p.id: {
            'lj_pres': [model.NewBoolVar(f'p{p.id}_pres_{t}') for t in range(num_slots_lj)],
            'lj_onl': [model.NewBoolVar(f'p{p.id}_onl_{t}') for t in range(num_slots_lj)],
            'semanal': [], # lista de vars de cursos para sumar horas
            'diaria': [],  # lista de vars de cursos L-J
            'has_presencial': model.NewBoolVar(f'p{p.id}_has_pres'),
            'has_online': model.NewBoolVar(f'p{p.id}_has_onl'),
            'assigned_any': model.NewBoolVar(f'p{p.id}_assigned_any')
        } for p in profesores}

        competencias_cache = {p.id: {pm.materia.id for pm in p.competencias} for p in profesores}

        # 1. Crear variables de asignación y vincular con auxiliares
        for item in cursos_a_asignar:
            c = item['curso']
            m = item['materia']
            
            candidatos = [p for p in profesores if m.id in competencias_cache[p.id]]
            
            if not candidatos:
                # Esto debería saltar en validar_recursos, pero por seguridad:
                return {"status": "error", "message": f"Error: Curso {m.nombre} sin candidatos."}

            vars_curso = []
            
            for p in candidatos:
                var = model.NewBoolVar(f'c{c.id}_p{p.id}')
                asignaciones[(c.id, p.id)] = var
                vars_curso.append(var)
                
                # Carga
                prof_vars[p.id]['semanal'].append(var)
                if c.dias_clase == 'L-J':
                    prof_vars[p.id]['diaria'].append(var)
                    
                    # Vincular con grids de horario L-J
                    if c.bloque_horario in slots_lj_map:
                        slot_idx = slots_lj_map[c.bloque_horario]
                        if c.modalidad == 'PRESENCIAL':
                            # Si asigno este curso, el slot presencial se activa (se suman, max 1 por restricción posterior)
                            # Usamos AddImplication para eficiencia o sumas directas.
                            # Como solo puede haber 1 curso por slot, podemos sumar en la restricción de definición.
                            pass 
                        elif 'ONLINE' in c.modalidad:
                            pass

            model.Add(sum(vars_curso) == 1)

        # 2. Restricciones por Profesor
        for p in profesores:
            p_data = prof_vars[p.id]
            
            # A) Definir variables de slot L-J
            # Sumar todos los cursos presenciales para el slot t
            for t in range(num_slots_lj):
                # Buscar cursos presenciales L-J de este profe en este slot
                # Esto es costoso de iterar, mejor optimizar.
                # Lo haremos acumulando listas.
                pass 

            # Optimización de construcción de restricciones
            # Agrupar variables por slot para el profesor
            # slot_vars[t]['pres'] = [var_curso1, var_curso2...]
            slot_vars = {t: {'pres': [], 'onl': []} for t in range(num_slots_lj)}
            
            # Recorrer asignaciones globales para llenar slot_vars local
            # (Esto es lineal sobre el total de aristas, aceptable)
            for item in cursos_a_asignar:
                c = item['curso']
                if c.dias_clase == 'L-J' and c.bloque_horario in slots_lj_map:
                    slot_idx = slots_lj_map[c.bloque_horario]
                    if (c.id, p.id) in asignaciones:
                        var = asignaciones[(c.id, p.id)]
                        if c.modalidad == 'PRESENCIAL':
                            slot_vars[slot_idx]['pres'].append(var)
                        elif 'ONLINE' in c.modalidad:
                            slot_vars[slot_idx]['onl'].append(var)

            # Restricciones L-J Slot a Slot
            for t in range(num_slots_lj):
                # 1. Definir booleano de ocupación
                model.Add(sum(slot_vars[t]['pres']) == p_data['lj_pres'][t])
                model.Add(sum(slot_vars[t]['onl']) == p_data['lj_onl'][t])
                
                # 2. No puede estar en dos lugares a la vez (Choque simple)
                model.Add(p_data['lj_pres'][t] + p_data['lj_onl'][t] <= 1)

            # B) REGLA CRÍTICA DE DESPLAZAMIENTO Y MIXTO
            # Para cada par de slots (t1, t2), si modalidad es distinta, distancia debe ser 2 (hueco de 2h)
            for t1 in range(num_slots_lj):
                for t2 in range(num_slots_lj):
                    if t1 == t2: continue
                    
                    distancia = abs(t1 - t2)
                    # Slot 0(7), Slot 1(9), Slot 2(11).
                    # Distancia 1 = Consecutivo (Gap 0h).
                    # Distancia 2 = Gap 2h.
                    # Distancia > 2 = Gap > 2h.
                    
                    # REGLA: Si las modalidades son distintas, la distancia DEBE SER EXACTAMENTE 2.
                    # Si distancia != 2, prohibido mezclar.
                    if distancia != 2:
                        # Si tengo Presencial en t1, NO puedo tener Online en t2
                        model.Add(p_data['lj_pres'][t1] + p_data['lj_onl'][t2] <= 1)
                        # Viceversa
                        model.Add(p_data['lj_onl'][t1] + p_data['lj_pres'][t2] <= 1)

            # C) Carga Horaria (Semanal y Diaria)
            if p_data['semanal']:
                model.Add(sum(p_data['semanal']) * 8 <= p.max_horas_semana)
            if p_data['diaria']:
                model.Add(sum(p_data['diaria']) * 2 <= p.max_horas_dia)

            # D) Definir variables de uso para Objetivos
            # assigned_any
            all_vars = p_data['semanal'] # Lista de todas las asignaciones posibles
            if all_vars:
                model.Add(sum(all_vars) > 0).OnlyEnforceIf(p_data['assigned_any'])
                model.Add(sum(all_vars) == 0).OnlyEnforceIf(p_data['assigned_any'].Not())
            else:
                model.Add(p_data['assigned_any'] == 0)

            # has_presencial / has_online (Globales, incluyendo FDS si aplica, o solo L-J?)
            # El usuario dice "No quiero profesor dando solo virtual".
            # Usaremos todas las variables asignadas clasificadas.
            all_pres_vars = []
            all_onl_vars = []
            for item in cursos_a_asignar:
                c = item['curso']
                if (c.id, p.id) in asignaciones:
                    v = asignaciones[(c.id, p.id)]
                    if 'PRESENCIAL' in c.modalidad: all_pres_vars.append(v)
                    else: all_onl_vars.append(v)
            
            if all_pres_vars:
                model.Add(sum(all_pres_vars) > 0).OnlyEnforceIf(p_data['has_presencial'])
                model.Add(sum(all_pres_vars) == 0).OnlyEnforceIf(p_data['has_presencial'].Not())
            else:
                model.Add(p_data['has_presencial'] == 0)
                
            if all_onl_vars:
                model.Add(sum(all_onl_vars) > 0).OnlyEnforceIf(p_data['has_online'])
                model.Add(sum(all_onl_vars) == 0).OnlyEnforceIf(p_data['has_online'].Not())
            else:
                model.Add(p_data['has_online'] == 0)

        # ==========================================
        # FASE 4: OBJETIVOS (OPTIMIZACIÓN)
        # ==========================================
        
        # 1. Maximizar Clases Consecutivas (Solo L-J tiene sentido de consecutividad)
        consecutive_vars = []
        for p in profesores:
            p_data = prof_vars[p.id]
            for t in range(num_slots_lj - 1):
                # Crear variable que sea 1 si t y t+1 están activos (cualquier modalidad)
                is_active_t = model.NewBoolVar(f'act_{p.id}_{t}')
                is_active_next = model.NewBoolVar(f'act_{p.id}_{t+1}')
                
                # Vincular active con pres/onl
                model.Add(p_data['lj_pres'][t] + p_data['lj_onl'][t] == 1).OnlyEnforceIf(is_active_t)
                model.Add(p_data['lj_pres'][t] + p_data['lj_onl'][t] == 0).OnlyEnforceIf(is_active_t.Not())
                
                model.Add(p_data['lj_pres'][t+1] + p_data['lj_onl'][t+1] == 1).OnlyEnforceIf(is_active_next)
                model.Add(p_data['lj_pres'][t+1] + p_data['lj_onl'][t+1] == 0).OnlyEnforceIf(is_active_next.Not())
                
                # Bonificar si ambos activos
                cons_var = model.NewBoolVar(f'cons_{p.id}_{t}')
                model.Add(is_active_t + is_active_next == 2).OnlyEnforceIf(cons_var)
                model.Add(is_active_t + is_active_next < 2).OnlyEnforceIf(cons_var.Not())
                consecutive_vars.append(cons_var)

        # 2. Penalizar "Solo Virtual"
        # Estrategia: Penalizar si has_online es 1 Y has_presencial es 0.
        # O equivalentemente: Maximizar has_presencial si has_online es true.
        # Vamos a sumar penalizaciones.
        penalty_virtual_only_vars = []
        for p in profesores:
            is_virtual_only = model.NewBoolVar(f'v_only_{p.id}')
            # is_virtual_only <=> has_online AND NOT has_presencial
            model.AddBoolAnd([prof_vars[p.id]['has_online'], prof_vars[p.id]['has_presencial'].Not()]).OnlyEnforceIf(is_virtual_only)
            model.AddBoolOr([prof_vars[p.id]['has_online'].Not(), prof_vars[p.id]['has_presencial']]).OnlyEnforceIf(is_virtual_only.Not())
            penalty_virtual_only_vars.append(is_virtual_only)

        # 3. Maximizar Profesores Asignados (Evitar 0 carga)
        assigned_vars = [prof_vars[p.id]['assigned_any'] for p in profesores]

        # FUNCIÓN OBJETIVO COMPUESTA
        # Pesos:
        # +10 por cada par consecutivo
        # +20 por cada profesor asignado (Spread load)
        # -100 por cada profesor "Solo Virtual" (Evitar fuerte)
        
        score_consecutive = sum(consecutive_vars)
        score_assigned = sum(assigned_vars)
        score_virtual_penalty = sum(penalty_virtual_only_vars)
        
        model.Maximize(
            (score_consecutive * 10) + 
            (score_assigned * 20) - 
            (score_virtual_penalty * 100)
        )

        # ==========================================
        # FASE 5: SOLUCIÓN
        # ==========================================
        logger.info("--- 4. Ejecutando Solver ---")
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 120.0
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
                            dias_db = [5]
                            duracion_bloque = 8 
                        
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
            msg = "Imposible generar: Conflicto insalvable de restricciones (Gap de Desplazamiento o Disponibilidad). Intente añadir profesores."
            logger.error(msg)
            return {"status": "error", "message": msg}
        else:
            return {"status": "error", "message": "Tiempo de espera agotado sin solución óptima."}

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.critical(f"Excepción en solver: {str(e)}\n{error_detail}")
        return {"status": "error", "message": str(e)}