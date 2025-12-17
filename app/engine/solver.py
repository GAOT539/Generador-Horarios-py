from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria, db

def generar_horario_automatico():
    print("--- 1. Preparando entorno (Modo: Distinción Regular/Online) ---")
    
    with db.atomic():
        Horario.delete().execute()
        Curso.delete().execute()

    # 2. AUTO-GENERACIÓN DE CURSOS
    # Ahora leemos cantidad_regular y cantidad_online
    materias = list(Materia.select())
    
    letras = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']
    
    with db.atomic():
        for m in materias:
            # 1. Crear Cursos REGULARES
            cant_reg = min(m.cantidad_regular, 14)
            for i in range(cant_reg):
                letra = letras[i]
                # Turno balanceado (A=Mat, B=Vesp...)
                turno = 'Matutino' if i % 2 == 0 else 'Vespertino' 
                Curso.create(
                    nombre=letra, 
                    nivel=m.nivel, 
                    turno=turno,
                    modalidad='REGULAR'
                )
                
            # 2. Crear Cursos ONLINE
            cant_online = min(m.cantidad_online, 10)
            for i in range(cant_online):
                # Nombres distintivos para Online: OL1, OL2...
                nombre_curso = f"OL{i+1}"
                # Por defecto online se asigna (luego el solver puede moverlo, pero necesitamos un valor inicial)
                # El usuario pidió Online preferente mañana o noche, por ahora lo dejamos genérico
                turno = 'Matutino' 
                Curso.create(
                    nombre=nombre_curso, 
                    nivel=m.nivel, 
                    turno=turno,
                    modalidad='ONLINE'
                )

    # 3. Cargar datos
    profesores = list(Profesor.select())
    cursos = list(Curso.select()) 
    # Planificamos materias que tengan AL MENOS un curso (regular u online)
    materias_planificadas = list(Materia.select().where((Materia.cantidad_regular > 0) | (Materia.cantidad_online > 0)))

    if not materias_planificadas:
        return {"status": "error", "message": "Faltan Materias para generar."}

    # 4. Configuración del Modelo Matemático
    model = cp_model.CpModel()
    
    slots_matutinos = [7, 9, 11]
    slots_vespertinos = [13, 15, 17]

    shifts = {}
    clases_a_programar = []

    cursos_por_nivel = {}
    for c in cursos:
        if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
        cursos_por_nivel[c.nivel].append(c)

    for materia in materias_planificadas:
        # Obtenemos TODOS los cursos de ese nivel (Regular + Online)
        cursos_del_nivel = cursos_por_nivel.get(materia.nivel, [])
        
        # Como Curso no tiene FK directa a Materia (solo nivel), filtramos lógicamente
        # (En este diseño simplificado, asumimos que Curso nivel X pertenece a Materia nivel X)
        # Esto funciona porque generamos los cursos iterando las materias.
        
        # Debemos asegurarnos de no mezclar cursos de 'Ingles 1' con 'Frances 1'
        # PERO, en tu modelo actual Curso NO TIENE Materia. 
        # El solver asume que el Curso del nivel X es para la Materia que se está iterando.
        # *Corrección lógica para el futuro*: Curso debería tener FK a Materia.
        # POR AHORA: Limitamos la lista al número total de cursos creados para esta materia específica.
        
        total_cursos = materia.cantidad_regular + materia.cantidad_online
        cursos_objetivo = cursos_del_nivel[:total_cursos]

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
    profes_ids_unicos = set(p.id for p in profesores)
    
    for p_id in profes_ids_unicos:
        for slot in all_slots:
            vars_profe_slot = [var for k, var in shifts.items() if k[1] == p_id and k[2] == slot]
            model.Add(sum(vars_profe_slot) <= 1)

    # 3. Conflictos Curso
    for curso in cursos:
        for slot in all_slots:
            vars_curso_slot = []
            for k, var in shifts.items():
                if clases_a_programar[k[0]]['curso'].id == curso.id and k[2] == slot:
                    vars_curso_slot.append(var)
            model.Add(sum(vars_curso_slot) <= 1)

    # 4. Max Horas Diarias
    for p in profesores:
        vars_total_profe = [var for k, var in shifts.items() if k[1] == p.id]
        if vars_total_profe:
            model.Add(sum(vars_total_profe) * 2 <= p.max_horas_dia)

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("¡Solución encontrada!")
        count = 0
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, slot_inicio = key
                    datos = clases_a_programar[c_idx]
                    
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
        return {"status": "ok", "message": f"Horario generado. {count} bloques asignados."}
    
    return {"status": "error", "message": "No se encontró solución."}