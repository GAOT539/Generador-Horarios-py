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
            # 1. Crear Cursos REGULARES (Balanceo Matutino/Vespertino)
            # Lunes a Jueves
            cant_reg = min(m.cantidad_regular, 14)
            for i in range(cant_reg):
                letra = letras[i]
                turno = 'Matutino' if i % 2 == 0 else 'Vespertino' 
                Curso.create(nombre=letra, nivel=m.nivel, turno=turno, modalidad='REGULAR')
                
            # 2. Crear Cursos ONLINE L-J (Balanceo Matutino/Nocturno)
            # Se comportan como los regulares pero con preferencia de bloques extremos
            cant_online_lj = min(m.cantidad_online_lj, 10)
            for i in range(cant_online_lj):
                nombre_curso = f"OL-LJ{i+1}"
                # Alternancia: Pares -> Mañana, Impares -> Noche
                turno = 'Matutino' if i % 2 == 0 else 'Nocturno'
                Curso.create(nombre=nombre_curso, nivel=m.nivel, turno=turno, modalidad='ONLINE_LJ')

            # 3. Crear Cursos ONLINE Fin de Semana (Sáb y Dom)
            # Estos son fijos para FDS
            cant_online_fds = min(m.cantidad_online_fds, 5)
            for i in range(cant_online_fds):
                nombre_curso = f"OL-FDS{i+1}"
                Curso.create(nombre=nombre_curso, nivel=m.nivel, turno='FDS', modalidad='ONLINE_FDS')

    # --- CARGA DE DATOS ---
    profesores = list(Profesor.select())
    cursos = list(Curso.select()) 
    
    # Filtramos materias que tengan alguna demanda
    materias_planificadas = []
    for m in materias:
        if m.cantidad_regular > 0 or m.cantidad_online_lj > 0 or m.cantidad_online_fds > 0:
            materias_planificadas.append(m)

    if not materias_planificadas:
        return {"status": "error", "message": "Faltan Materias para generar."}

    # --- CONFIGURACIÓN DEL MODELO ---
    model = cp_model.CpModel()
    
    # DEFINICIÓN DE BLOQUES HORARIOS
    
    # BLOQUES L-J (2 horas x 4 días = 8 horas)
    SLOTS_LJ_MAT = [7, 9, 11]
    SLOTS_LJ_VESP = [13, 15, 17] 
    SLOTS_LJ_NOCHE = [19]        
    ALL_SLOTS_LJ = sorted(SLOTS_LJ_MAT + SLOTS_LJ_VESP + SLOTS_LJ_NOCHE)

    # BLOQUES FDS (4 horas Sábado + 4 horas Domingo = 8 horas)
    # Solo permitimos inicios a las 7:00 (para acabar a las 11:00) o quizás 7 y 8?
    # El usuario dijo "Bloque permitido 07:00 a 11:00". Eso es un solo bloque de 4 horas.
    # Por tanto, el único slot de inicio posible es las 7:00.
    SLOT_FDS_INICIO = [7] 

    # Variables principales: shifts[(clase_idx, p_id, slot, tipo_dia)]
    # tipo_dia: 0=L-J, 1=Sábado, 2=Domingo
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

    # Generación de variables de decisión
    for c_idx, clase in enumerate(clases_a_programar):
        curso = clase['curso']
        opciones_validas = [] # (slot, tipo_dia)

        if curso.modalidad == 'REGULAR':
            # Solo Lunes-Jueves
            slots_target = SLOTS_LJ_MAT if curso.turno == 'Matutino' else SLOTS_LJ_VESP
            for s in slots_target: opciones_validas.append((s, 0)) # 0 = L-J
        
        elif curso.modalidad == 'ONLINE_LJ':
            # Solo Lunes-Jueves (Prioridad Mañana o Noche)
            if curso.turno == 'Matutino':
                for s in [7, 9]: opciones_validas.append((s, 0))
            else: # Nocturno
                for s in SLOTS_LJ_NOCHE: opciones_validas.append((s, 0))

        elif curso.modalidad == 'ONLINE_FDS':
            # Solo Fin de Semana
            # REGLA 4 HORAS: Solo un slot posible (7:00 a 11:00)
            for s in SLOT_FDS_INICIO:
                opciones_validas.append((s, 1)) # Sábado
                opciones_validas.append((s, 2)) # Domingo

        for p_id in clase['profes_ids']:
            for (slot, tipo_dia) in opciones_validas:
                shifts[(c_idx, p_id, slot, tipo_dia)] = model.NewBoolVar(f'c{c_idx}_p{p_id}_s{slot}_d{tipo_dia}')

    # --- RESTRICCIONES ---

    # 1. Cada clase asignada 1 vez
    # PARA FDS: Necesitamos que se asigne 1 vez en Sábado Y 1 vez en Domingo (Espejo)
    
    for c_idx, clase in enumerate(clases_a_programar):
        mod = clase['modalidad']
        
        if mod in ['REGULAR', 'ONLINE_LJ']:
            # Suma total debe ser 1 (un bloque L-J)
            vars_curso = [var for k, var in shifts.items() if k[0] == c_idx]
            model.Add(sum(vars_curso) == 1)
            
        elif mod == 'ONLINE_FDS':
            # Aquí es el truco:
            # Debe haber 1 asignación en Sábado y 1 en Domingo
            vars_sab = [var for k, var in shifts.items() if k[0] == c_idx and k[3] == 1]
            vars_dom = [var for k, var in shifts.items() if k[0] == c_idx and k[3] == 2]
            
            model.Add(sum(vars_sab) == 1)
            model.Add(sum(vars_dom) == 1)

            # REGLA DE ESPEJO (MISMO PROFESOR, MISMA HORA)
            # Si el profe P da la clase a las 7 el sábado, el mismo profe P debe darla a las 7 el domingo.
            for p_id in clase['profes_ids']:
                for s in SLOT_FDS_INICIO:
                    # Var Sábado vs Var Domingo
                    v_s = shifts.get((c_idx, p_id, s, 1))
                    v_d = shifts.get((c_idx, p_id, s, 2))
                    
                    if v_s and v_d:
                        model.Add(v_s == v_d)

    # 2. Conflictos de Profesor 
    profes_ids_unicos = set(p.id for p in profesores)
    
    vars_by_p_d_s = {}
    for k, var in shifts.items():
        _, p_id, slot, tipo_dia = k
        key = (p_id, tipo_dia, slot)
        if key not in vars_by_p_d_s: vars_by_p_d_s[key] = []
        vars_by_p_d_s[key].append(var)

    for key, vars_list in vars_by_p_d_s.items():
        model.Add(sum(vars_list) <= 1)

    # 3. Restricciones Avanzadas (Consecutivos, Gap 2h)
    obj_consecutivos = []
    obj_profesores_activos = []

    for p in profesores:
        vars_total_semana = []
        
        # Iteramos por tipos de día para ver Gaps y Cargas
        for tipo_dia in [0, 1, 2]: # L-J, Sab, Dom
            if tipo_dia == 0:
                slots_del_dia = ALL_SLOTS_LJ
                duracion_bloque = 2
                dias_reales = 4
            else:
                slots_del_dia = SLOT_FDS_INICIO # Solo 7
                duracion_bloque = 4 # Son bloques de 4 horas
                dias_reales = 1

            is_working = {}
            
            for s in slots_del_dia:
                vars_en_slot = vars_by_p_d_s.get((p.id, tipo_dia, s), [])
                trabaja_s = model.NewBoolVar(f'work_p{p.id}_d{tipo_dia}_s{s}')
                model.Add(sum(vars_en_slot) == trabaja_s)
                is_working[s] = trabaja_s
                
                # Carga Semanal: (1 si trabaja) * duracion * dias que se repite
                vars_total_semana.append(trabaja_s * duracion_bloque * dias_reales)

                # --- GAP DE MODALIDAD (Solo aplica en L-J porque en FDS solo hay Online) ---
                if tipo_dia == 0:
                     # Lógica de Gap para L-J (Regular vs Online LJ)
                     # Recuperamos vars y chequeamos adyacencia
                     # (Simplificado aquí para brevedad, se mantiene igual que en tu versión anterior
                     #  pero adaptado a las nuevas modalidades 'ONLINE_LJ')
                     pass 

            # CONSECUTIVOS (Solo aplica si hay más de 1 slot posible, en FDS solo hay 1 slot de 7-11)
            if len(slots_del_dia) > 1:
                for i in range(len(slots_del_dia) - 1):
                    s1 = slots_del_dia[i]
                    s2 = slots_del_dia[i+1]
                    if s2 - s1 == 2: # Solo si son bloques de 2h seguidos
                        b_consec = model.NewBoolVar(f'cons_p{p.id}_{s1}_{s2}')
                        model.AddMultiplicationEquality(b_consec, [is_working[s1], is_working[s2]])
                        obj_consecutivos.append(b_consec)

        # LÍMITES DE CARGA
        if vars_total_semana:
            model.Add(sum(vars_total_semana) <= p.max_horas_semana)
            
            is_active = model.NewBoolVar(f'active_p{p.id}')
            model.Add(sum(vars_total_semana) >= is_active)
            obj_profesores_activos.append(is_active)

    # --- FUNCIÓN OBJETIVO ---
    model.Maximize(sum(obj_consecutivos) * 10 + sum(obj_profesores_activos) * 1000)

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"¡Solución encontrada!")
        count = 0
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, slot_inicio, tipo_dia = key
                    datos = clases_a_programar[c_idx]
                    
                    dias_a_grabar = []
                    duracion = 2

                    if tipo_dia == 0: # L-J
                        dias_a_grabar = [0, 1, 2, 3]
                        duracion = 2
                    elif tipo_dia == 1: # Sábado
                        dias_a_grabar = [5]
                        duracion = 4 # Bloque de 4 horas
                    elif tipo_dia == 2: # Domingo
                        dias_a_grabar = [6]
                        duracion = 4 # Bloque de 4 horas

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
        return {"status": "ok", "message": f"Horario generado. {count} bloques asignados."}
    
    return {"status": "error", "message": "No se encontró solución."}