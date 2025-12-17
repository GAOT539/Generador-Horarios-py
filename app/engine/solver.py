from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria, db

def generar_horario_automatico():
    print("--- 1. Preparando entorno y Generando Cursos ---")
    
    with db.atomic():
        Horario.delete().execute()
        Curso.delete().execute()

    materias = list(Materia.select())
    letras = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']
    
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
                # CAMBIO: Usar letras A, B, C... (revisar que no choquen si se desea unicidad global o por modalidad)
                # El requerimiento es que se muestren como A B C. 
                # Usaremos la misma lista de letras. Visualmente se distinguen por el tag [ON].
                letra = letras[i] 
                turno = 'Matutino' if i % 2 == 0 else 'Nocturno'
                Curso.create(nombre=letra, nivel=m.nivel, turno=turno, modalidad='ONLINE_LJ')

            # 3. Crear Cursos ONLINE Fin de Semana
            cant_online_fds = min(m.cantidad_online_fds, 5)
            for i in range(cant_online_fds):
                letra = letras[i]
                Curso.create(nombre=letra, nivel=m.nivel, turno='FDS', modalidad='ONLINE_FDS')

    # --- CARGA DE DATOS ---
    profesores = list(Profesor.select())
    profesores_map = {p.id: p.nombre for p in profesores}
    cursos = list(Curso.select()) 
    
    materias_planificadas = []
    for m in materias:
        if m.cantidad_regular > 0 or m.cantidad_online_lj > 0 or m.cantidad_online_fds > 0:
            materias_planificadas.append(m)

    if not materias_planificadas:
        return {"status": "error", "message": "Faltan Materias para generar."}

    # --- CONFIGURACIÓN DEL MODELO ---
    model = cp_model.CpModel()
    
    # DEFINICIÓN DE BLOQUES HORARIOS
    SLOTS_LJ_MAT = [7, 9, 11]
    SLOTS_LJ_VESP = [13, 15, 17] 
    SLOTS_LJ_NOCHE = [19]        
    ALL_SLOTS_LJ = sorted(SLOTS_LJ_MAT + SLOTS_LJ_VESP + SLOTS_LJ_NOCHE)

    # BLOQUES FDS
    SLOT_FDS_INICIO = [7] 

    shifts = {}
    clases_a_programar = []

    cursos_por_nivel = {}
    for c in cursos:
        if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
        cursos_por_nivel[c.nivel].append(c)

    print("--- 2. Creando Variables del Modelo ---")

    for materia in materias_planificadas:
        cursos_del_nivel = cursos_por_nivel.get(materia.nivel, [])
        total_cursos_mat = materia.cantidad_regular + materia.cantidad_online_lj + materia.cantidad_online_fds
        cursos_objetivo = cursos_del_nivel[:total_cursos_mat]

        for curso in cursos_objetivo:
            profes_aptos = (Profesor.select().join(ProfesorMateria).where(ProfesorMateria.materia == materia))
            profes_ids = [p.id for p in profes_aptos]
            
            if not profes_ids: continue

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
            # Flexibilidad total
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
            model.Add(sum(vars_curso) == 1)
            
        elif mod == 'ONLINE_FDS':
            vars_sab = [var for k, var in shifts.items() if k[0] == c_idx and k[3] == 1]
            vars_dom = [var for k, var in shifts.items() if k[0] == c_idx and k[3] == 2]
            
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
    obj_prioridad_presencial = []
    
    # Listas de preferencia Online
    obj_preferencia_online_high = [] # Peso 100
    obj_preferencia_online_med = []  # Peso 50
    obj_preferencia_online_low = []  # Peso 45

    for c_idx, clase in enumerate(clases_a_programar):
        # A) PRIORIDAD PRESENCIAL
        if clase['modalidad'] == 'REGULAR':
            turno = clase['curso'].turno
            target_slot = 7 if turno == 'Matutino' else 13 
            for p_id in clase['profes_ids']:
                var_target = shifts.get((c_idx, p_id, target_slot, 0))
                if var_target is not None:
                    obj_prioridad_presencial.append(var_target)
        
        # B) PREFERENCIA ONLINE
        if clase['modalidad'] == 'ONLINE_LJ':
            turno = clase['curso'].turno
            for p_id in clase['profes_ids']:
                if turno == 'Matutino':
                    # Tier 1: 7 y 9 (Ideal) -> 100 pts
                    v7 = shifts.get((c_idx, p_id, 7, 0))
                    v9 = shifts.get((c_idx, p_id, 9, 0))
                    if v7 is not None: obj_preferencia_online_high.append(v7)
                    if v9 is not None: obj_preferencia_online_high.append(v9)
                    
                    # Tier 2: 11 y 13 -> 50 pts
                    v11 = shifts.get((c_idx, p_id, 11, 0))
                    v13 = shifts.get((c_idx, p_id, 13, 0))
                    if v11 is not None: obj_preferencia_online_med.append(v11)
                    if v13 is not None: obj_preferencia_online_med.append(v13)
                    
                    # Tier 3: 19 -> 45 pts
                    v19 = shifts.get((c_idx, p_id, 19, 0))
                    if v19 is not None: obj_preferencia_online_low.append(v19)
                    
                else: # Nocturno
                    # Tier 1: 19 -> 100 pts
                    v19 = shifts.get((c_idx, p_id, 19, 0))
                    if v19 is not None: obj_preferencia_online_high.append(v19)
                    
                    # Tier 2: 17 -> 50 pts
                    v17 = shifts.get((c_idx, p_id, 17, 0))
                    if v17 is not None: obj_preferencia_online_med.append(v17)

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
    # PESOS SOLICITADOS:
    # 1. Prioridad Presencial (10,000)
    # 2. Profesores Activos (1,000)
    # 3. Preferencia Online ALTA (100) -> 7am o 9am
    # 4. Preferencia Online MEDIA (50) -> 11am o 1pm
    # 5. Preferencia Online BAJA (45) -> 19pm
    # 6. Consecutivos (10)
    model.Maximize(
        sum(obj_profesores_activos) * 1000 + 
        sum(obj_prioridad_presencial) * 10000 + 
        sum(obj_preferencia_online_high) * 100 +
        sum(obj_preferencia_online_med) * 50 + 
        sum(obj_preferencia_online_low) * 45 +
        sum(obj_consecutivos) * 10
    )

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"¡Solución encontrada! Objetivo: {solver.ObjectiveValue()}")
        
        # --- TABLA EN CONSOLA ---
        print("-" * 75)
        print(f"{'DÍA':<15} | {'HORA':<12} | {'ASIGNATURA':<25} | {'PROFESOR':<20}")
        print("-" * 75)

        count = 0
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, slot_inicio, tipo_dia = key
                    datos = clases_a_programar[c_idx]
                    
                    # Log en consola
                    dia_str = "Lun-Jue" if tipo_dia == 0 else ("Sábado " if tipo_dia == 1 else "Domingo")
                    
                    # Formato Log: [ON]Materia si es online
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
    
    return {"status": "error", "message": "No se encontró solución viable."}