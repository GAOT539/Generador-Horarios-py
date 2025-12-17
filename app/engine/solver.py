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
            # 1. Crear Cursos REGULARES (Balanceo Turnos)
            cant_reg = min(m.cantidad_regular, 14)
            for i in range(cant_reg):
                letra = letras[i]
                turno = 'Matutino' if i % 2 == 0 else 'Vespertino' 
                Curso.create(nombre=letra, nivel=m.nivel, turno=turno, modalidad='REGULAR')
                
            # 2. Crear Cursos ONLINE
            cant_online = min(m.cantidad_online, 10)
            for i in range(cant_online):
                nombre_curso = f"OL{i+1}"
                Curso.create(nombre=nombre_curso, nivel=m.nivel, turno='Online', modalidad='ONLINE')

    # --- CARGA DE DATOS ---
    profesores = list(Profesor.select())
    cursos = list(Curso.select()) 
    materias_planificadas = list(Materia.select().where((Materia.cantidad_regular > 0) | (Materia.cantidad_online > 0)))

    if not materias_planificadas:
        return {"status": "error", "message": "Faltan Materias para generar."}

    # --- CONFIGURACIÓN DEL MODELO ---
    model = cp_model.CpModel()
    
    # DEFINICIÓN DE BLOQUES HORARIOS
    # Tipo Día 0: Lunes a Jueves (Se replica)
    SLOTS_LJ_MAT = [7, 9, 11]
    SLOTS_LJ_VESP = [13, 15, 17] # 13:00 - 19:00
    SLOTS_LJ_NOCHE = [19]        # 19:00 - 21:00
    
    # Lista ordenada para chequear consecutivos en L-J
    ALL_SLOTS_LJ = sorted(SLOTS_LJ_MAT + SLOTS_LJ_VESP + SLOTS_LJ_NOCHE)

    # Tipo Día 1 (Sáb) y 2 (Dom): Solo mañana
    SLOTS_FDS = [7, 9]

    # Variables principales: shifts[(clase_idx, p_id, slot, tipo_dia)]
    shifts = {}
    clases_a_programar = []

    # Agrupación para optimizar
    cursos_por_nivel = {}
    for c in cursos:
        if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
        cursos_por_nivel[c.nivel].append(c)

    print("--- 2. Creando Variables del Modelo ---")

    for materia in materias_planificadas:
        cursos_del_nivel = cursos_por_nivel.get(materia.nivel, [])
        total_cursos = materia.cantidad_regular + materia.cantidad_online
        cursos_objetivo = cursos_del_nivel[:total_cursos]

        for curso in cursos_objetivo:
            profes_aptos = (Profesor.select().join(ProfesorMateria).where(ProfesorMateria.materia == materia))
            profes_ids = [p.id for p in profes_aptos]
            
            if not profes_ids:
                print(f"⚠️ ALERTA: Sin profesor para {materia.nombre} ({curso.modalidad})")
                continue

            clases_a_programar.append({
                'materia': materia,
                'curso': curso,
                'profes_ids': profes_ids,
                'modalidad': curso.modalidad # Guardamos esto para restricciones
            })

    # Generación de variables de decisión
    for c_idx, clase in enumerate(clases_a_programar):
        curso = clase['curso']
        opciones_validas = [] # (slot, tipo_dia)

        if curso.modalidad == 'REGULAR':
            # Lunes-Jueves
            slots_target = SLOTS_LJ_MAT if curso.turno == 'Matutino' else SLOTS_LJ_VESP
            for s in slots_target: opciones_validas.append((s, 0))
        
        elif curso.modalidad == 'ONLINE':
            # Preferencia Mañana (LJ), Noche (LJ), FDS
            for s in [7, 9]: opciones_validas.append((s, 0)) 
            for s in SLOTS_LJ_NOCHE: opciones_validas.append((s, 0))
            for s in SLOTS_FDS: 
                opciones_validas.append((s, 1)) # Sáb
                opciones_validas.append((s, 2)) # Dom

        for p_id in clase['profes_ids']:
            for (slot, tipo_dia) in opciones_validas:
                shifts[(c_idx, p_id, slot, tipo_dia)] = model.NewBoolVar(f'c{c_idx}_p{p_id}_s{slot}_d{tipo_dia}')

    print(f"Total Clases: {len(clases_a_programar)} | Variables generadas: {len(shifts)}")

    # --- RESTRICCIONES BÁSICAS ---

    # 1. Cada clase asignada exactamente 1 vez
    for c_idx in range(len(clases_a_programar)):
        vars_clase = [var for k, var in shifts.items() if k[0] == c_idx]
        if vars_clase:
            model.Add(sum(vars_clase) == 1)

    # 2. Conflictos de Profesor (No puede estar en 2 lugares)
    profes_ids_unicos = set(p.id for p in profesores)
    
    # Mapeo rápido de vars por profesor/dia/slot
    # vars_by_p_d_s[(p_id, tipo_dia, slot)] = [lista_de_vars_booleanas]
    vars_by_p_d_s = {}

    for k, var in shifts.items():
        _, p_id, slot, tipo_dia = k
        key = (p_id, tipo_dia, slot)
        if key not in vars_by_p_d_s: vars_by_p_d_s[key] = []
        vars_by_p_d_s[key].append(var)

    for key, vars_list in vars_by_p_d_s.items():
        model.Add(sum(vars_list) <= 1)

    # --- RESTRICCIONES AVANZADAS Y OBJETIVOS ---
    
    obj_consecutivos = []
    obj_profesores_activos = []

    for p in profesores:
        # Variables para contar carga total del profesor
        vars_total_semana = []
        
        # --- Lógica por Día (para Gap y Consecutivos) ---
        for tipo_dia in [0, 1, 2]:
            slots_del_dia = ALL_SLOTS_LJ if tipo_dia == 0 else SLOTS_FDS
            
            # Variables auxiliares para este profesor/dia
            # is_working[slot] -> Bool (¿Trabaja en este slot?)
            is_working = {}
            
            for s in slots_del_dia:
                # Recuperar todas las asignaciones potenciales en este slot
                vars_en_slot = vars_by_p_d_s.get((p.id, tipo_dia, s), [])
                
                # Crear variable auxiliar: trabaja_s
                trabaja_s = model.NewBoolVar(f'work_p{p.id}_d{tipo_dia}_s{s}')
                model.Add(sum(vars_en_slot) == trabaja_s) # Si asignado a algo -> 1
                is_working[s] = trabaja_s

                # Sumar a carga semanal
                factor_horas = 8 if tipo_dia == 0 else 2
                vars_total_semana.append(trabaja_s * factor_horas)

                # --- VALIDACIÓN DE GAP DE MODALIDAD (REGLA CRÍTICA) ---
                # Separamos vars por modalidad para chequear el choque
                vars_reg = []
                vars_onl = []
                
                # Iteramos las vars originales para ver de qué modalidad son
                for k, var in shifts.items():
                    if k[1] == p.id and k[2] == s and k[3] == tipo_dia:
                        mod = clases_a_programar[k[0]]['modalidad']
                        if mod == 'REGULAR': vars_reg.append(var)
                        else: vars_onl.append(var)
                
                # Guardamos sumas parciales para comparar con el vecino
                # Nota: como max asignación es 1, sum(vars_reg) es 0 o 1 Bool
                is_reg_s = model.NewBoolVar(f'reg_p{p.id}_d{tipo_dia}_s{s}')
                is_onl_s = model.NewBoolVar(f'onl_p{p.id}_d{tipo_dia}_s{s}')
                model.Add(sum(vars_reg) == is_reg_s)
                model.Add(sum(vars_onl) == is_onl_s)
                
                # Chequeo con el slot ANTERIOR (si existe) para ver adyacencia
                idx_s = slots_del_dia.index(s)
                if idx_s > 0:
                    s_prev = slots_del_dia[idx_s - 1]
                    # Adyacencia: Si la diferencia horaria es exactamente 2 horas
                    # (7->9, 9->11...). Si hay hueco natural > 2h, no aplica restricción.
                    if s - s_prev == 2:
                        # Recuperar vars del previo
                        # Necesitamos referencia a las vars del loop anterior, 
                        # pero es mas fácil recalcular o almacenar.
                        # Accedemos a is_reg_s_prev (que acabamos de crear en it anterior? No, scope)
                        # Mejor: almacenar is_reg / is_onl en diccionario
                        pass

            # Guardamos diccionarios completos para procesar pares
            # is_reg_map[slot] -> BoolVar
            is_reg_map = {}
            is_onl_map = {}
            
            for s in slots_del_dia:
                vars_en_slot = [v for k, v in shifts.items() if k[1] == p.id and k[2] == s and k[3] == tipo_dia]
                
                # Construir vars bool por modalidad
                v_reg = [v for k, v in shifts.items() if k[1]==p.id and k[2]==s and k[3]==tipo_dia and clases_a_programar[k[0]]['modalidad']=='REGULAR']
                v_onl = [v for k, v in shifts.items() if k[1]==p.id and k[2]==s and k[3]==tipo_dia and clases_a_programar[k[0]]['modalidad']=='ONLINE']
                
                b_reg = model.NewBoolVar(f'breg_p{p.id}_d{tipo_dia}_s{s}')
                b_onl = model.NewBoolVar(f'bonl_p{p.id}_d{tipo_dia}_s{s}')
                
                model.Add(sum(v_reg) == b_reg)
                model.Add(sum(v_onl) == b_onl)
                
                is_reg_map[s] = b_reg
                is_onl_map[s] = b_onl

            # APLICAR RESTRICCIONES DE PARES (GAP) Y OBJETIVO (CONSECUTIVOS)
            for i in range(len(slots_del_dia) - 1):
                s1 = slots_del_dia[i]
                s2 = slots_del_dia[i+1]
                
                # Solo si son adyacentes temporalmente (gap 0)
                if s2 - s1 == 2:
                    # 1. GAP DE MODALIDAD
                    # Prohibido: (Reg en s1 Y Onl en s2) O (Onl en s1 Y Reg en s2)
                    # b_reg[s1] + b_onl[s2] <= 1
                    model.Add(is_reg_map[s1] + is_onl_map[s2] <= 1)
                    model.Add(is_onl_map[s1] + is_reg_map[s2] <= 1)
                    
                    # 2. OBJETIVO: CONSECUTIVOS
                    # Premiar si trabaja en s1 Y trabaja en s2 (sin importar modalidad, si cumplen gap)
                    # is_working[s1] AND is_working[s2]
                    b_consec = model.NewBoolVar(f'cons_p{p.id}_d{tipo_dia}_{s1}_{s2}')
                    model.AddMultiplicationEquality(b_consec, [is_working[s1], is_working[s2]])
                    obj_consecutivos.append(b_consec)

        # --- LÍMITES DE CARGA ---
        # A) Carga Semanal
        if vars_total_semana:
            model.Add(sum(vars_total_semana) <= p.max_horas_semana)
            
            # OBJETIVO: PROFESOR ACTIVO
            # Queremos maximizar el uso de distintos profesores (no dejar a nadie en 0 si es posible)
            # is_active es 1 si sum(horas) >= 1.
            is_active = model.NewBoolVar(f'active_p{p.id}')
            # Si suma > 0, is_active puede ser 1. Si suma 0, is_active debe ser 0.
            # Implementación lógica: suma >= is_active. (Si active=1, suma debe ser >=1)
            # Dado que suma es int (horas), y active es bool (0/1).
            # Maximizaremos is_active.
            model.Add(sum(vars_total_semana) >= is_active) 
            obj_profesores_activos.append(is_active)

        # B) Carga Diaria (Solo L-J importa la restricción de 8h o custom)
        # Recalculamos carga L-J
        vars_lj = [v * 2 for k, v in shifts.items() if k[1] == p.id and k[3] == 0]
        if vars_lj:
            model.Add(sum(vars_lj) <= p.max_horas_dia)
        
        # C) Carga Fin de Semana (Max 4 horas dia)
        for d_fds in [1, 2]:
            vars_fds = [v * 2 for k, v in shifts.items() if k[1] == p.id and k[3] == d_fds]
            if vars_fds:
                model.Add(sum(vars_fds) <= 4)

    # --- FUNCIÓN OBJETIVO FINAL ---
    # Maximize (Peso1 * Consecutivos + Peso2 * Activos)
    # Peso Activos > Peso Consecutivos para garantizar distribución primero
    model.Maximize(sum(obj_consecutivos) * 10 + sum(obj_profesores_activos) * 1000)

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    # solver.parameters.log_search_progress = True # Descomentar para debug
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"¡Solución encontrada! ({solver.ObjectiveValue()})")
        count = 0
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, slot_inicio, tipo_dia = key
                    datos = clases_a_programar[c_idx]
                    
                    dias_a_grabar = []
                    if tipo_dia == 0: dias_a_grabar = [0, 1, 2, 3] # L-J
                    elif tipo_dia == 1: dias_a_grabar = [5]        # Sáb
                    elif tipo_dia == 2: dias_a_grabar = [6]        # Dom

                    for dia_num in dias_a_grabar:
                        Horario.create(
                            dia=dia_num,
                            hora_inicio=slot_inicio,
                            hora_fin=slot_inicio + 2,
                            profesor_id=p_id,
                            materia_id=datos['materia'].id,
                            curso_id=datos['curso'].id
                        )
                    count += 1
        return {"status": "ok", "message": f"Horario optimizado. {count} bloques asignados."}
    
    return {"status": "error", "message": "No se encontró solución válida."}
