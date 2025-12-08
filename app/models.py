from peewee import Model, CharField, IntegerField, ForeignKeyField, CompositeKey
from app.database import db

class BaseModel(Model):
    class Meta:
        database = db

# --- 1. INFRAESTRUCTURA ---
class Aula(BaseModel):
    nombre = CharField(unique=True) # Ej: "Aula 101", "Laboratorio 1"
    tipo = CharField(default="General") # General, Laboratorio, etc.

# --- 2. ACADÉMICO ---
class Materia(BaseModel):
    nombre = CharField(unique=True) # Ej: "Ingles", "Italiano"
    
class Curso(BaseModel):
    nombre = CharField() # Ej: "A", "B", "C"
    nivel = IntegerField() # Ej: 1, 2, 3
    turno = CharField() # "Matutino" o "Vespertino"
    # Un curso es la combinación de Nivel+Letra (Ej: 1-A Matutino)
    class Meta:
        indexes = ((('nombre', 'nivel', 'turno'), True),)

# --- 3. DOCENTES ---
class Profesor(BaseModel):
    cedula = CharField(unique=True)
    nombre = CharField()
    max_horas_semana = IntegerField(default=20)
    max_horas_dia = IntegerField(default=6)
    # Preferencia de turno (opcional, para el algoritmo después)
    turno_preferido = CharField(default="Indiferente") 

class ProfesorMateria(BaseModel):
    """Define qué materias y en qué niveles puede dar un profesor"""
    profesor = ForeignKeyField(Profesor, backref='competencias')
    materia = ForeignKeyField(Materia, backref='profesores')
    # Si quisieras restringir niveles específicos por materia, podrías añadir campo 'niveles' aquí
    
    class Meta:
        indexes = ((('profesor', 'materia'), True),)

# --- 4. RESULTADO (HORARIO) ---
class Horario(BaseModel):
    dia = IntegerField()      # 0=Lunes, 4=Viernes
    hora_inicio = IntegerField() # 7, 8, 9...
    hora_fin = IntegerField()    # 9, 10...
    
    profesor = ForeignKeyField(Profesor, backref='asignaciones')
    materia = ForeignKeyField(Materia)
    aula = ForeignKeyField(Aula)
    curso = ForeignKeyField(Curso) # A quién le da clase

def inicializar_db():
    db.connect()
    # create_tables verifica si existen, si no, las crea.
    # safe=True evita errores si ya existen.
    db.create_tables([Aula, Materia, Curso, Profesor, ProfesorMateria, Horario], safe=True)
    db.close()