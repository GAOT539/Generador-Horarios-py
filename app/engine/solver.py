from ortools.sat.python import cp_model
from app.models import Profesor, Materia, Curso, Horario, ProfesorMateria, db

def generar_horario_automatico():
    print("--- 1. Preparando entorno ---")
    
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

    letras = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
    
    with db.atomic():
        for nivel, cantidad in max_grupos_por_nivel.items():
            for i in range(cantidad):
                letra = letras[i] if i < len(letras) else f"G{i}"
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
    dias = [0, 1, 2, 3, 4] # Lunes a Viernes
    
    horas_matutinas = [7, 8, 9, 10, 11, 12]
    horas_vespertinas = [14, 15, 16, 17, 18, 19]

    # Variables: x[clase_idx, profesor_id, dia, hora]
    # YA NO USAMOS AULA
    shifts = {}
    clases_a_programar = []

    cursos_por_nivel = {}
    for c in cursos:
        if c.nivel not in cursos_por_nivel: cursos_por_nivel[c.nivel] = []
        cursos_por_nivel[c.nivel].append(c)

    for materia in materias_planificadas:
        cursos_del_nivel = cursos_por_nivel.get(materia.nivel, [])
        cursos_objetivo = cursos_del_nivel[:materia.cantidad_grupos]

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

    print(f"Intentando programar {len(clases_a_programar)} bloques académicos.")

    # CREACIÓN DE VARIABLES
    for clase_idx, clase in enumerate(clases_a_programar):
        curso = clase['curso']
        horas_posibles = horas_matutinas if curso.turno == 'Matutino' else horas_vespertinas

        for p_id in clase['profes_ids']:
            for dia in dias:
                for hora in horas_posibles:
                    # Variable Booleana: ¿Esta clase se da con este profe en este dia y hora?
                    shifts[(clase_idx, p_id, dia, hora)] = model.NewBoolVar(
                        f'c{clase_idx}_p{p_id}_d{dia}_h{hora}'
                    )

    # --- RESTRICCIONES ---

    # 1. Duración de clases (2 horas por materia)
    duracion = 2
    for c_idx, clase in enumerate(clases_a_programar):
        vars_clase = []
        for key, var in shifts.items():
            if key[0] == c_idx: 
                vars_clase.append(var)
        if vars_clase:
            model.Add(sum(vars_clase) == duracion)

    # 2. Restricciones de NO CLONACIÓN
    all_horas = horas_matutinas + horas_vespertinas
    for dia in dias:
        for hora in all_horas:
            
            # A. Un profe, una sola clase al mismo tiempo
            profes_ids_unicos = set(p.id for p in profesores)
            for p_id in profes_ids_unicos:
                 # Suma de todas las clases donde aparece este profe en este slot <= 1
                 model.Add(sum(shifts[k] for k in shifts if k[1] == p_id and k[2] == dia and k[3] == hora) <= 1)

            # B. Un curso, una sola clase al mismo tiempo
            for c in cursos:
                vars_curso = []
                for k, var in shifts.items():
                    # k[0] -> indice en clases_a_programar
                    if clases_a_programar[k[0]]['curso'].id == c.id and k[2] == dia and k[3] == hora:
                        vars_curso.append(var)
                model.Add(sum(vars_curso) <= 1)

    # --- SOLVER ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    status = solver.Solve(model)

    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("¡Solución encontrada!")
        with db.atomic():
            for key, var in shifts.items():
                if solver.Value(var) == 1:
                    c_idx, p_id, d, h = key
                    datos = clases_a_programar[c_idx]
                    
                    Horario.create(
                        dia=d, hora_inicio=h, hora_fin=h+1,
                        profesor_id=p_id, materia_id=datos['materia'].id,
                        curso_id=datos['curso'].id,
                        aula_id=None # Ya no hay aulas
                    )
        return {"status": "ok", "message": f"Horario generado. Se crearon {len(cursos)} cursos automáticamente."}
    
    return {"status": "error", "message": "No se encontró solución. Revisa disponibilidad de profesores."}