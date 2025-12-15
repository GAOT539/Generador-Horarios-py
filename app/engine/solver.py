from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria, db

def generar_horario_automatico():
    print("--- 1. Preparando entorno (Modo: Lunes replicado) ---")
    
    with db.atomic():
        Horario.delete().execute()
        Curso.delete().execute()

    # 2. AUTO-GENERACIÓN DE CURSOS
    # (Misma lógica que antes: crea cursos A, B, C según demanda)
    materias = list(Materia.select())
    max_grupos_por_nivel = {} 

    for m in materias:
        if m.nivel not in max_grupos_por_nivel:
            max_grupos_por_nivel[m.nivel] = 0
        if m.cantidad_grupos > max_grupos_por_nivel[m.nivel]:
            max_grupos_por_nivel[m.nivel] = m.cantidad_grupos

    letras = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
    
    with db.atomic():
        for nivel, cantidad in max_grupos_por_nivel.items():
            for i in range(cantidad):
                letra = letras[i] if i < len(letras) else f"G{i}"
                # Los 2 primeros grupos (A, B) son Matutinos, el resto Vespertinos
                turno = 'Matutino' if i < 2 else 'Vespertino' 
                Curso.create(nombre=letra, nivel=nivel, turno=turno)

    # 3. Cargar datos
    profesores = list(Profesor.select())
    cursos = list(Curso.select()) 
    materias_planificadas = list(Materia.select().where(Materia.cantidad_grupos > 0))

    if not materias_planificadas:
        return {"status": "error", "message": "Faltan Materias para generar."}

    # 4. Configuración del Modelo Matemático
    model = cp_model.CpModel()
    
    # --- DEFINICIÓN DE BLOQUES (SLOTS) DE 2 HORAS ---
    # En lugar de horas sueltas, trabajamos con bloques de inicio.
    # Matutino: 7-9, 9-11, 11-13 (Slots inician a las 7, 9, 11)
    # Vespertino: 14-16, 16-18, 18-20 (Slots inician a las 14, 16, 18)
    slots_matutinos = [7, 9, 11]
    slots_vespertinos = [14, 16, 18]

    # Variables: x[clase_idx, profesor_id, slot_inicio]
    # Ya no usamos 'dia' en la variable porque resolvemos para un día genérico
    shifts = {}
    clases_a_programar = []

    # Organizar cursos para acceso rápido
    cursos_por_nivel = {}
    for c in cursos:
        if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
        cursos_por_nivel[c.nivel].append(c)

    # Preparar qué clases necesitamos crear
    for materia in materias_planificadas:
        cursos_del_nivel = cursos_por_nivel.get(materia.nivel, [])
        cursos_objetivo = cursos_del_nivel[:materia.cantidad_grupos]

        for curso in cursos_objetivo:
            # Profesores que pueden dar esta materia
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
        # Definir qué slots están disponibles para este curso según su turno
        slots_posibles = slots_matutinos if curso.turno == 'Matutino' else slots_vespertinos

        for p_id in clase['profes_ids']:
            for slot in slots_posibles:
                # Variable: ¿La clase X la da el Profe Y en el Slot Z?
                shifts[(clase_idx, p_id, slot)] = model.NewBoolVar(
                    f'c{clase_idx}_p{p_id}_s{slot}'
                )

    # --- RESTRICCIONES ---

    # 1. Cada clase debe ocurrir EXACTAMENTE 1 VEZ (en un bloque de 2 horas)
    # (Como replicaremos el horario L-V, esto significa 2 horas diarias)
    for c_idx in range(len(clases_a_programar)):
        vars_de_esta_clase = []
        for key, var in shifts.items():
            if key[0] == c_idx:
                vars_de_esta_clase.append(var)
        model.Add(sum(vars_de_esta_clase) == 1)

    # 2. Conflictos: Un PROFE no puede estar en dos clases en el mismo slot
    all_slots = slots_matutinos + slots_vespertinos
    profes_ids_unicos = set(p.id for p in profesores)
    
    for p_id in profes_ids_unicos:
        for slot in all_slots:
            clases_del_profe_en_slot = []
            for key, var in shifts.items():
                # key = (clase_idx, p_id_variable, slot_variable)
                if key[1] == p_id and key[2] == slot:
                    clases_del_profe_en_slot.append(var)
            model.Add(sum(clases_del_profe_en_slot) <= 1)

    # 3. Conflictos: Un CURSO no puede recibir dos clases en el mismo slot
    for curso in cursos:
        for slot in all_slots:
            clases_del_curso_en_slot = []
            for key, var in shifts.items():
                c_idx = key[0]
                # Verificamos si la clase pertenece a este curso
                if clases_a_programar[c_idx]['curso'].id == curso.id and key[2] == slot:
                    clases_del_curso_en_slot.append(var)
            model.Add(sum(clases_del_curso_en_slot) <= 1)

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("¡Solución encontrada! Guardando y replicando...")
        count = 0
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, slot_inicio = key
                    datos = clases_a_programar[c_idx]
                    
                    # REPLICACIÓN: Guardamos lo mismo para Lunes(0) a Viernes(4)
                    for dia_semana in [0, 1, 2, 3, 4]:
                        Horario.create(
                            dia=dia_semana,
                            hora_inicio=slot_inicio,
                            hora_fin=slot_inicio + 2, # Siempre son bloques de 2 horas
                            profesor_id=p_id,
                            materia_id=datos['materia'].id,
                            curso_id=datos['curso'].id
                        )
                    count += 1
        return {"status": "ok", "message": f"Horario generado. {count} bloques asignados y replicados L-V."}
    
    return {"status": "error", "message": "No se encontró solución. Verifica disponibilidad de profes."}