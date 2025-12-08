from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Aula, Curso, Horario, ProfesorMateria, db

def generar_horario_automatico():
    print("--- 1. Preparando entorno ---")
    
    # Limpiamos horarios y cursos antiguos (se regenerarán según la demanda actual)
    with db.atomic():
        Horario.delete().execute()
        Curso.delete().execute()

    # 2. AUTO-GENERACIÓN DE CURSOS (La magia que pediste)
    # Analizamos cuál es la demanda máxima de grupos por cada nivel
    materias = list(Materia.select())
    max_grupos_por_nivel = {} # Ej: {1: 3, 2: 2} (Nivel 1 necesita 3 grupos, Nivel 2 necesita 2)

    for m in materias:
        if m.nivel not in max_grupos_por_nivel:
            max_grupos_por_nivel[m.nivel] = 0
        
        # Si Inglés pide 3 grupos, el nivel necesita al menos 3 cursos (A, B, C)
        if m.cantidad_grupos > max_grupos_por_nivel[m.nivel]:
            max_grupos_por_nivel[m.nivel] = m.cantidad_grupos

    print(f"Demanda detectada: {max_grupos_por_nivel}")

    # Creamos los cursos en la BD automáticamente
    letras = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
    cursos_generados = []

    with db.atomic():
        for nivel, cantidad in max_grupos_por_nivel.items():
            for i in range(cantidad):
                letra = letras[i] if i < len(letras) else f"G{i}"
                
                # LOGICA DE TURNOS AUTOMÁTICA
                # Grupos A y B -> Matutino
                # Grupos C, D... -> Vespertino
                # (Puedes cambiar este '2' si quieres más matutinos)
                turno = 'Matutino' if i < 2 else 'Vespertino' 
                
                nuevo_curso = Curso.create(
                    nombre=letra,
                    nivel=nivel,
                    turno=turno
                )
                cursos_generados.append(nuevo_curso)
                print(f"   -> Auto-creado: Curso {nivel}-{letra} ({turno})")

    # 3. Cargar datos para el algoritmo
    profesores = list(Profesor.select())
    aulas = list(Aula.select())
    cursos = list(Curso.select()) 
    materias_planificadas = list(Materia.select().where(Materia.cantidad_grupos > 0))

    if not aulas or not materias_planificadas:
        return {"status": "error", "message": "Faltan Aulas o Materias para generar."}

    # 4. Configuración del Modelo Matemático
    model = cp_model.CpModel()
    dias = [0, 1, 2, 3, 4] # Lunes a Viernes
    
    # Bloques horarios
    horas_matutinas = [7, 8, 9, 10, 11, 12]
    horas_vespertinas = [14, 15, 16, 17, 18, 19]

    # Variables: x[materia, curso, profe, aula, dia, hora]
    shifts = {}
    clases_a_programar = []

    # Mapeo de cursos por nivel para acceso rápido
    cursos_por_nivel = {}
    for c in cursos:
        if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
        cursos_por_nivel[c.nivel].append(c) # Estarán ordenados A, B, C...

    for materia in materias_planificadas:
        # Recuperamos los cursos disponibles para este nivel
        cursos_del_nivel = cursos_por_nivel.get(materia.nivel, [])
        
        # Asignamos la materia a los primeros N cursos
        # Ej: Si Inglés pide 2 grupos, se asigna al Curso A y al Curso B
        cursos_objetivo = cursos_del_nivel[:materia.cantidad_grupos]

        for curso in cursos_objetivo:
            # Buscar profes competentes
            profes_aptos = (Profesor
                            .select()
                            .join(ProfesorMateria)
                            .where(ProfesorMateria.materia == materia))
            profes_ids = [p.id for p in profes_aptos]
            
            if not profes_ids:
                print(f"⚠️ ALERTA: Nadie sabe dar {materia.nombre} (Nivel {materia.nivel})")
                continue

            clases_a_programar.append({
                'materia': materia,
                'curso': curso,
                'profes_ids': profes_ids
            })

    print(f"Intentando programar {len(clases_a_programar)} bloques académicos.")

    # CREACIÓN DE VARIABLES
    for clase_idx, clase in enumerate(clases_a_programar):
        curso = clase['curso']
        horas_posibles = horas_matutinas if curso.turno == 'Matutino' else horas_vespertinas

        for p_id in clase['profes_ids']:
            for aula in aulas:
                for dia in dias:
                    for hora in horas_posibles:
                        shifts[(clase_idx, p_id, aula.id, dia, hora)] = model.NewBoolVar(
                            f'c{clase_idx}_p{p_id}_a{aula.id}_d{dia}_h{hora}'
                        )

    # --- RESTRICCIONES ---

    # 1. Duración de clases (2 horas por materia)
    duracion = 2
    for c_idx, clase in enumerate(clases_a_programar):
        vars_clase = []
        # Recolectar todas las variables asociadas a esta clase específica
        for key, var in shifts.items():
            if key[0] == c_idx: # key[0] es el indice de la clase
                vars_clase.append(var)
        
        if vars_clase:
            model.Add(sum(vars_clase) == duracion)

    # 2. Restricciones de NO CLONACIÓN (Overlap)
    all_horas = horas_matutinas + horas_vespertinas
    for dia in dias:
        for hora in all_horas:
            # A. Un aula, una clase
            for aula in aulas:
                model.Add(sum(shifts[k] for k in shifts if k[2] == aula.id and k[3] == dia and k[4] == hora) <= 1)

            # B. Un profe, una clase
            profes_ids_unicos = set(p.id for p in profesores)
            for p_id in profes_ids_unicos:
                 model.Add(sum(shifts[k] for k in shifts if k[1] == p_id and k[3] == dia and k[4] == hora) <= 1)

            # C. Un curso, una clase
            for c in cursos:
                # Buscamos variables que pertenezcan a este curso
                vars_curso = []
                for k, var in shifts.items():
                    # k[0] es el indice en clases_a_programar
                    if clases_a_programar[k[0]]['curso'].id == c.id and k[3] == dia and k[4] == hora:
                        vars_curso.append(var)
                model.Add(sum(vars_curso) <= 1)

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10 # Limite de tiempo para no congelar
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("¡Solución encontrada!")
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, a_id, d, h = key
                    datos = clases_a_programar[c_idx]
                    
                    Horario.create(
                        dia=d, hora_inicio=h, hora_fin=h+1,
                        profesor_id=p_id, materia_id=datos['materia'].id,
                        aula_id=a_id, curso_id=datos['curso'].id
                    )
        return {"status": "ok", "message": f"Horario generado. Se crearon {len(cursos)} cursos automáticamente."}
    
    return {"status": "error", "message": "No se encontró solución. Revisa aulas o disponibilidad."}