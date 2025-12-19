import logging
import traceback
from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria, db

# Configurar logger local para este módulo
logger = logging.getLogger(__name__)

def generar_horario_automatico():
    logger.info("--- Iniciando proceso de generación de horarios ---")
    
    try:
        print("--- 1. Preparando entorno y Generando Cursos ---")
        
        with db.atomic():
            Horario.delete().execute()
            Curso.delete().execute()

        # ORDEN CRÍTICO: Aseguramos que se creen y se lean en el mismo orden (por ID)
        materias = list(Materia.select().order_by(Materia.id))
        letras = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']
        
        # --- FASE 1: CREACIÓN DE CURSOS ---
        with db.atomic():
            for m in materias:
                # 1. Crear Cursos REGULARES
                cant_reg = min(m.cantidad_regular, 14)
                for i in range(cant_reg):
                    letra = letras[i]
                    turno = 'Matutino' if i % 2 == 0 else 'Vespertino' 
                    Curso.create(nombre=letra, nivel=m.nivel, turno=turno, modalidad='REGULAR')
                    
                # 2. Crear Cursos ONLINE L-J
                cant_online_lj = min(m.cantidad_online_lj, 10)
                for i in range(cant_online_lj):
                    letra = letras[i] 
                    turno = 'Matutino' if i % 2 == 0 else 'Nocturno'
                    Curso.create(nombre=letra, nivel=m.nivel, turno=turno, modalidad='ONLINE_LJ')
                    # print(f"DEBUG: Creado {m.nombre} Curso {letra} (ONLINE L-J)") 

                # 3. Crear Cursos ONLINE Fin de Semana
                cant_online_fds = min(m.cantidad_online_fds, 5)
                for i in range(cant_online_fds):
                    letra = letras[i]
                    Curso.create(nombre=letra, nivel=m.nivel, turno='FDS', modalidad='ONLINE_FDS')
                    # print(f"DEBUG: Creado {m.nombre} Curso {letra} (ONLINE FDS)")

        # --- CARGA DE DATOS ---
        profesores = list(Profesor.select())
        profesores_map = {p.id: p.nombre for p in profesores}
        cursos = list(Curso.select().order_by(Curso.id)) 
        
        materias_planificadas = []
        for m in materias: 
            if m.cantidad_regular > 0 or m.cantidad_online_lj > 0 or m.cantidad_online_fds > 0:
                materias_planificadas.append(m)

        if not materias_planificadas:
            err_msg = "No hay materias configuradas con cursos (paralelos > 0)."
            logger.warning(err_msg)
            return {"status": "error", "message": err_msg}

        # --- FASE 2: VALIDACIONES ESPECÍFICAS DE ERRORES ---
        # Antes de crear el modelo, verificamos viabilidad básica
        print("--- 1.5 Validando Recursos Docentes ---")
        for materia in materias_planificadas:
            # 1. Buscar profesores aptos
            profes_aptos = (Profesor.select()
                            .join(ProfesorMateria)
                            .where(ProfesorMateria.materia == materia))
            
            lista_profes = list(profes_aptos)
            
            # ERROR 1: No hay profesores para la materia
            if not lista_profes:
                err_msg = f"ERROR CRÍTICO: No existen profesores asignados para '{materia.nombre}' Nivel {materia.nivel}. Imposible generar horario."
                logger.error(err_msg)
                return {"status": "error", "message": err_msg}

            # Cálculo de demanda vs oferta
            horas_necesarias = 0
            # Regular: 4 horas semana (2 bloques de 2h)
            horas_necesarias += materia.cantidad_regular * 4 
            # Online LJ: 4 horas semana
            horas_necesarias += materia.cantidad_online_lj * 4
            # Online FDS: 4 horas semana
            horas_necesarias += materia.cantidad_online_fds * 4

            # Capacidad total de los profesores aptos (aproximada, ya que comparten tiempo con otras materias)
            capacidad_docente_total = sum([p.max_horas_semana for p in lista_profes])

            # ERROR 2: Matemáticamente imposible por falta de horas
            # Nota: Esta es una validación "blanda" porque los profes pueden dar otras materias,
            # pero si la demanda SOLO de esta materia supera la oferta TOTAL, es imposible seguro.
            if horas_necesarias > capacidad_docente_total:
                err_msg = (f"INSUFICIENCIA DOCENTE: '{materia.nombre}' Nivel {materia.nivel} requiere {horas_necesarias} horas, "
                           f"pero los docentes asignados solo suman {capacidad_docente_total} horas disponibles totales.")
                logger.error(err_msg)
                return {"status": "error", "message": err_msg}


        # --- CONFIGURACIÓN DEL MODELO ---
        model = cp_model.CpModel()
        
        SLOTS_LJ_MAT = [7, 9, 11]
        SLOTS_LJ_VESP = [13, 15, 17] 
        SLOTS_LJ_NOCHE = [19]        
        ALL_SLOTS_LJ = sorted(SLOTS_LJ_MAT + SLOTS_LJ_VESP + SLOTS_LJ_NOCHE)
        SLOT_FDS_INICIO = [7] 

        shifts = {}
        clases_a_programar = []

        cursos_por_nivel = {}
        for c in cursos:
            if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
            cursos_por_nivel[c.nivel].append(c)

        print("--- 2. Creando Variables del Modelo ---")

        for materia in materias_planificadas:
            cursos_disponibles = cursos_por_nivel.get(materia.nivel, [])
            necesarios = materia.cantidad_regular + materia.cantidad_online_lj + materia.cantidad_online_fds
            
            cursos_objetivo = []
            if len(cursos_disponibles) >= necesarios:
                for _ in range(necesarios):
                    cursos_objetivo.append(cursos_disponibles.pop(0)) # FIFO
            else:
                # Esto no debería pasar gracias a la creación previa, pero por seguridad:
                msg = f"Error interno: Inconsistencia en cursos creados vs requeridos para {materia.nombre}"
                logger.error(msg)
                return {"status": "error", "message": msg}

            profes_aptos = (Profesor.select().join(ProfesorMateria).where(ProfesorMateria.materia == materia))
            profes_ids = [p.id for p in profes_aptos]
            
            # Validación redundante pero segura
            if not profes_ids: continue 

            for curso in cursos_objetivo:
                clases_a_programar.append({
                    'materia': materia,
                    'curso': curso,
                    'profes_ids': profes_ids,
                    'modalidad': curso.modalidad
                })

        for c_idx, clase in enumerate(clases_a_programar):
            curso = clase['curso']
            opciones_validas = [] 

            if curso.modalidad == 'REGULAR':
                slots_target = SLOTS_LJ_MAT if curso.turno == 'Matutino' else SLOTS_LJ_VESP
                for s in slots_target: opciones_validas.append((s, 0)) # 0 = L-J
            
            elif curso.modalidad == 'ONLINE_LJ':
                for s in ALL_SLOTS_LJ: opciones_validas.append((s, 0))

            elif curso.modalidad == 'ONLINE_FDS':
                for s in SLOT_FDS_INICIO:
                    opciones_validas.append((s, 1)) # Sábado
                    opciones_validas.append((s, 2)) # Domingo

            for p_id in clase['profes_ids']:
                for (slot, tipo_dia) in opciones_validas:
                    shifts[(c_idx, p_id, slot, tipo_dia)] = model.NewBoolVar(f'c{c_idx}_p{p_id}_s{slot}_d{tipo_dia}')

        # --- RESTRICCIONES ---

        # 1. Asignación única
        for c_idx, clase in enumerate(clases_a_programar):
            mod = clase['modalidad']
            
            if mod in ['REGULAR', 'ONLINE_LJ']:
                vars_curso = [var for k, var in shifts.items() if k[0] == c_idx]
                if not vars_curso:
                    # Si no hay variables, significa que no hay huecos/profes compatibles para las restricciones dadas
                    err_msg = f"Imposible asignar curso {clase['materia'].nombre} ({mod}). Verifique disponibilidad horaria de docentes."
                    logger.error(err_msg)
                    return {"status": "error", "message": err_msg}
                model.Add(sum(vars_curso) == 1)
                
            elif mod == 'ONLINE_FDS':
                vars_sab = [var for k, var in shifts.items() if k[0] == c_idx and k[3] == 1]
                vars_dom = [var for k, var in shifts.items() if k[0] == c_idx and k[3] == 2]
                
                if not vars_sab or not vars_dom:
                    err_msg = f"Imposible asignar curso FDS {clase['materia'].nombre}. Verifique docentes con disponibilidad FDS."
                    logger.error(err_msg)
                    return {"status": "error", "message": err_msg}

                model.Add(sum(vars_sab) == 1)
                model.Add(sum(vars_dom) == 1)

                # Espejo
                for p_id in clase['profes_ids']:
                    for s in SLOT_FDS_INICIO:
                        v_s = shifts.get((c_idx, p_id, s, 1))
                        v_d = shifts.get((c_idx, p_id, s, 2))
                        if v_s is not None and v_d is not None:
                            model.Add(v_s == v_d)

        # 2. Conflictos Profesor
        vars_by_p_d_s = {}
        for k, var in shifts.items():
            _, p_id, slot, tipo_dia = k
            key = (p_id, tipo_dia, slot)
            if key not in vars_by_p_d_s: vars_by_p_d_s[key] = []
            vars_by_p_d_s[key].append(var)

        for key, vars_list in vars_by_p_d_s.items():
            model.Add(sum(vars_list) <= 1)

        # 3. Restricciones Avanzadas y Objetivos
        obj_consecutivos = []
        obj_profesores_activos = []
        
        obj_preferencia_online_high = [] 
        obj_preferencia_online_med = []  
        obj_preferencia_online_low = []  

        usage_regular_mat = {7: [], 9: [], 11: []}
        usage_regular_vesp = {13: [], 15: [], 17: []}

        for c_idx, clase in enumerate(clases_a_programar):
            # A) RECOLECCIÓN PARA BALANCEO PRESENCIAL
            if clase['modalidad'] == 'REGULAR':
                turno = clase['curso'].turno
                slots_check = SLOTS_LJ_MAT if turno == 'Matutino' else SLOTS_LJ_VESP
                target_dict = usage_regular_mat if turno == 'Matutino' else usage_regular_vesp
                
                for s in slots_check:
                    for p_id in clase['profes_ids']:
                        var_slot = shifts.get((c_idx, p_id, s, 0)) 
                        if var_slot is not None:
                            target_dict[s].append(var_slot)
            
            # B) PREFERENCIA ONLINE
            if clase['modalidad'] == 'ONLINE_LJ':
                turno = clase['curso'].turno
                for p_id in clase['profes_ids']:
                    if turno == 'Matutino':
                        v7 = shifts.get((c_idx, p_id, 7, 0))
                        v9 = shifts.get((c_idx, p_id, 9, 0))
                        if v7 is not None: obj_preferencia_online_high.append(v7)
                        if v9 is not None: obj_preferencia_online_high.append(v9)
                        
                        v11 = shifts.get((c_idx, p_id, 11, 0))
                        v13 = shifts.get((c_idx, p_id, 13, 0))
                        if v11 is not None: obj_preferencia_online_med.append(v11)
                        if v13 is not None: obj_preferencia_online_med.append(v13)
                        
                        v19 = shifts.get((c_idx, p_id, 19, 0))
                        if v19 is not None: obj_preferencia_online_low.append(v19)
                        
                    else: # Nocturno
                        v19 = shifts.get((c_idx, p_id, 19, 0))
                        if v19 is not None: obj_preferencia_online_high.append(v19)
                        v17 = shifts.get((c_idx, p_id, 17, 0))
                        if v17 is not None: obj_preferencia_online_med.append(v17)

        # --- LÓGICA DE BALANCEO ---
        obj_balance_mat = model.NewIntVar(0, 1000, 'min_load_mat')
        obj_balance_vesp = model.NewIntVar(0, 1000, 'min_load_vesp')

        counts_mat = []
        for s in [7, 9, 11]:
            count_var = model.NewIntVar(0, 1000, f'count_mat_{s}')
            model.Add(sum(usage_regular_mat[s]) == count_var)
            counts_mat.append(count_var)
        if counts_mat:
            model.AddMinEquality(obj_balance_mat, counts_mat)

        counts_vesp = []
        for s in [13, 15, 17]:
            count_var = model.NewIntVar(0, 1000, f'count_vesp_{s}')
            model.Add(sum(usage_regular_vesp[s]) == count_var)
            counts_vesp.append(count_var)
        if counts_vesp:
            model.AddMinEquality(obj_balance_vesp, counts_vesp)

        for p in profesores:
            vars_total_semana = []
            
            for tipo_dia in [0, 1, 2]: 
                if tipo_dia == 0:
                    slots_del_dia = ALL_SLOTS_LJ
                    duracion_bloque = 2
                    dias_reales = 4
                else:
                    slots_del_dia = SLOT_FDS_INICIO
                    duracion_bloque = 4
                    dias_reales = 1

                is_working = {}
                for s in slots_del_dia:
                    vars_en_slot = vars_by_p_d_s.get((p.id, tipo_dia, s), [])
                    trabaja_s = model.NewBoolVar(f'work_p{p.id}_d{tipo_dia}_s{s}')
                    model.Add(sum(vars_en_slot) == trabaja_s)
                    is_working[s] = trabaja_s
                    vars_total_semana.append(trabaja_s * duracion_bloque * dias_reales)

                # GAP Y CONSECUTIVOS
                vars_reg_in_slot = {s: [] for s in slots_del_dia}
                vars_onl_in_slot = {s: [] for s in slots_del_dia}
                
                for k, var in shifts.items():
                    if k[1] == p.id and k[3] == tipo_dia:
                        s = k[2]
                        if s in slots_del_dia:
                            mod = clases_a_programar[k[0]]['modalidad']
                            if mod == 'REGULAR': vars_reg_in_slot[s].append(var)
                            else: vars_onl_in_slot[s].append(var)
                
                is_reg_map = {}
                is_onl_map = {}
                for s in slots_del_dia:
                    b_reg = model.NewBoolVar(f'breg_p{p.id}_d{tipo_dia}_s{s}')
                    b_onl = model.NewBoolVar(f'bonl_p{p.id}_d{tipo_dia}_s{s}')
                    model.Add(sum(vars_reg_in_slot[s]) == b_reg)
                    model.Add(sum(vars_onl_in_slot[s]) == b_onl)
                    is_reg_map[s] = b_reg
                    is_onl_map[s] = b_onl

                if len(slots_del_dia) > 1:
                    for i in range(len(slots_del_dia) - 1):
                        s1 = slots_del_dia[i]
                        s2 = slots_del_dia[i+1]
                        if s2 - s1 == 2:
                            # Gap
                            if tipo_dia == 0:
                                model.Add(is_reg_map[s1] + is_onl_map[s2] <= 1)
                                model.Add(is_onl_map[s1] + is_reg_map[s2] <= 1)
                            # Consecutivos
                            b_consec = model.NewBoolVar(f'cons_p{p.id}_d{tipo_dia}_{s1}_{s2}')
                            model.AddMultiplicationEquality(b_consec, [is_working[s1], is_working[s2]])
                            obj_consecutivos.append(b_consec)

            # Carga Max
            if vars_total_semana:
                model.Add(sum(vars_total_semana) <= p.max_horas_semana)
                is_active = model.NewBoolVar(f'active_p{p.id}')
                model.Add(sum(vars_total_semana) >= is_active)
                obj_profesores_activos.append(is_active)

        # --- OBJETIVO ---
        model.Maximize(
            (obj_balance_mat * 5000) + 
            (obj_balance_vesp * 5000) +
            sum(obj_profesores_activos) * 1000 + 
            sum(obj_preferencia_online_high) * 100 +
            sum(obj_preferencia_online_med) * 50 + 
            sum(obj_preferencia_online_low) * 45 +
            sum(obj_consecutivos) * 10
        )

        # --- SOLVER ---
        print("--- Iniciando CP-SAT Solver ---")
        solver = cp_model.CpSolver()
        # Ajuste de parámetros para que no se quede pegado si es muy complejo
        solver.parameters.max_time_in_seconds = 60.0 
        status = solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            print(f"¡Solución encontrada! Objetivo: {solver.ObjectiveValue()}")
            logger.info(f"Solución encontrada. Estado: {solver.StatusName(status)}")
            
            print("-" * 75)
            print(f"{'DÍA':<15} | {'HORA':<12} | {'ASIGNATURA':<25} | {'PROFESOR':<20}")
            print("-" * 75)

            count = 0
            with db.atomic():
                for key, var in shifts.items():
                    if solver.Value(var) == 1:
                        c_idx, p_id, slot_inicio, tipo_dia = key
                        datos = clases_a_programar[c_idx]
                        
                        dia_str = "Lun-Jue" if tipo_dia == 0 else ("Sábado " if tipo_dia == 1 else "Domingo")
                        tag = "[ON]" if datos['modalidad'] != 'REGULAR' else ""
                        materia_str = f"{tag}{datos['materia'].nombre} - Nivel {datos['materia'].nivel} ({datos['curso'].nombre})"
                        profe_nombre = profesores_map.get(p_id, f"ID {p_id}")
                        
                        print(f"{dia_str:<15} | {slot_inicio:02d}:00-{slot_inicio+2 if tipo_dia==0 else slot_inicio+4:02d}:00 | {materia_str:<35} | {profe_nombre:<20}")

                        dias_a_grabar = []
                        duracion = 2

                        if tipo_dia == 0: # L-J
                            dias_a_grabar = [0, 1, 2, 3]
                            duracion = 2
                        elif tipo_dia == 1: # Sábado
                            dias_a_grabar = [5]
                            duracion = 4 
                        elif tipo_dia == 2: # Domingo
                            dias_a_grabar = [6]
                            duracion = 4 

                        for dia_num in dias_a_grabar:
                            Horario.create(
                                dia=dia_num,
                                hora_inicio=slot_inicio,
                                hora_fin=slot_inicio + duracion,
                                profesor_id=p_id,
                                materia_id=datos['materia'].id,
                                curso_id=datos['curso'].id
                            )
                        count += 1
            print("-" * 75)
            return {"status": "ok", "message": f"Horario generado. {count} bloques asignados."}
        
        elif status == cp_model.INFEASIBLE:
            msg = "El modelo es INVIABLE. Las restricciones son demasiado estrictas o faltan recursos (profesores/horas)."
            logger.error(msg)
            return {"status": "error", "message": msg}
        else:
            msg = f"No se encontró solución. Estado del solver: {solver.StatusName(status)}"
            logger.warning(msg)
            return {"status": "error", "message": msg}

    except Exception as e:
        # CAPTURA DE ERRORES INESPERADOS
        error_detail = traceback.format_exc()
        logger.critical(f"Excepción no controlada en el motor: {str(e)}\n{error_detail}")
        return {"status": "error", "message": f"Error interno del sistema: {str(e)}. Revise los logs."}