from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria, db

def generar_horario_automatico():
    print("--- 1. Preparando entorno (Modo: Lunes a Jueves | Cursos A-N) ---")
    
    with db.atomic():
        Horario.delete().execute()
        Curso.delete().execute()

    # 2. AUTO-GENERACIÓN DE CURSOS
    materias = list(Materia.select())
    max_grupos_por_nivel = {} 

    for m in materias:
        if m.nivel not in max_grupos_por_nivel:
            max_grupos_por_nivel[m.nivel] = 0
        if m.cantidad_grupos > max_grupos_por_nivel[m.nivel]:
            max_grupos_por_nivel[m.nivel] = m.cantidad_grupos

    # CAMBIO: Lista extendida hasta la 'N' (14 letras)
    letras = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']
    
    with db.atomic():
        for nivel, cantidad in max_grupos_por_nivel.items():
            # CAMBIO: Límite estricto de 14 cursos máximo
            cantidad_real = min(cantidad, 14)
            
            for i in range(cantidad_real):
                letra = letras[i]
                
                # LOGICA DE TURNOS:
                # A, B (índices 0, 1) -> Matutino
                # C en adelante -> Vespertino
                turno = 'Matutino' if i < 2 else 'Vespertino' 
                
                Curso.create(nombre=letra, nivel=nivel, turno=turno)
                print(f"   -> Curso creado: {nivel}-{letra} ({turno})")

    # 3. Cargar datos
    profesores = list(Profesor.select())
    cursos = list(Curso.select()) 
    materias_planificadas = list(Materia.select().where(Materia.cantidad_grupos > 0))

    if not materias_planificadas:
        return {"status": "error", "message": "Faltan Materias para generar."}

    # 4. Configuración del Modelo Matemático
    model = cp_model.CpModel()
    
    # Slots de 2 horas (Inicio del bloque)
    slots_matutinos = [7, 9, 11]
    slots_vespertinos = [14, 16, 18]

    shifts = {}
    clases_a_programar = []

    cursos_por_nivel = {}
    for c in cursos:
        if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
        cursos_por_nivel[c.nivel].append(c)

    for materia in materias_planificadas:
        cursos_del_nivel = cursos_por_nivel.get(materia.nivel, [])
        # También limitamos aquí por si acaso, aunque ya filtramos al crear cursos
        cursos_objetivo = cursos_del_nivel[:min(materia.cantidad_grupos, 14)]

        for curso in cursos_objetivo:
            profes_aptos = (Profesor.select().join(ProfesorMateria).where(ProfesorMateria.materia == materia))
            profes_ids = [p.id for p in profes_aptos]
            
            if not profes_ids:
                print(f"⚠️ ALERTA: Nadie sabe dar {materia.nombre} (Nivel {materia.nivel})")
                continue

            clases_a_programar.append({
                'materia': materia,
                'curso': curso,
                'profes_ids': profes_ids
            })

    print(f"Programando {len(clases_a_programar)} bloques de 2 horas...")

    # CREACIÓN DE VARIABLES
    for clase_idx, clase in enumerate(clases_a_programar):
        curso = clase['curso']
        slots_posibles = slots_matutinos if curso.turno == 'Matutino' else slots_vespertinos

        for p_id in clase['profes_ids']:
            for slot in slots_posibles:
                shifts[(clase_idx, p_id, slot)] = model.NewBoolVar(f'c{clase_idx}_p{p_id}_s{slot}')

    # --- RESTRICCIONES ---
    # 1. Cada clase 1 vez
    for c_idx in range(len(clases_a_programar)):
        vars_clase = [var for k, var in shifts.items() if k[0] == c_idx]
        model.Add(sum(vars_clase) == 1)

    # 2. Conflictos Profe
    all_slots = slots_matutinos + slots_vespertinos
    profes_ids = set(p.id for p in profesores)
    for p_id in profes_ids:
        for slot in all_slots:
            vars_profe = [var for k, var in shifts.items() if k[1] == p_id and k[2] == slot]
            model.Add(sum(vars_profe) <= 1)

    # 3. Conflictos Curso
    for curso in cursos:
        for slot in all_slots:
            vars_curso = []
            for k, var in shifts.items():
                if clases_a_programar[k[0]]['curso'].id == curso.id and k[2] == slot:
                    vars_curso.append(var)
            model.Add(sum(vars_curso) <= 1)

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("¡Solución encontrada! Guardando Lunes-Jueves...")
        count = 0
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, slot_inicio = key
                    datos = clases_a_programar[c_idx]
                    
                    # REPLICACIÓN: 0=Lunes, 1=Martes, 2=Miércoles, 3=Jueves (Sin Viernes)
                    for dia_semana in [0, 1, 2, 3]:
                        Horario.create(
                            dia=dia_semana,
                            hora_inicio=slot_inicio,
                            hora_fin=slot_inicio + 2,
                            profesor_id=p_id,
                            materia_id=datos['materia'].id,
                            curso_id=datos['curso'].id
                        )
                    count += 1
        return {"status": "ok", "message": f"Horario generado (L-J). {count} bloques asignados."}
    
    return {"status": "error", "message": "No se encontró solución."}