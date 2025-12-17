from peewee import Model, CharField, IntegerField, ForeignKeyField
from app.database import db

class BaseModel(Model):
    class Meta:
        database = db

# --- 1. ACADÉMICO ---
class Materia(BaseModel):
    nombre = CharField() 
    nivel = IntegerField() 
    # CAMBIO: Separación de demanda por modalidad
    cantidad_regular = IntegerField(default=0) # Presencial
    cantidad_online = IntegerField(default=0)  # En Línea
    
    class Meta:
        indexes = ((('nombre', 'nivel'), True),)

class Curso(BaseModel):
    nombre = CharField() # Ej: "A", "B" o "OL1"
    nivel = IntegerField() 
    turno = CharField() 
    # CAMBIO: Campo para distinguir modalidad
    modalidad = CharField() # 'REGULAR' o 'ONLINE'

# --- 2. DOCENTES ---
class Profesor(BaseModel):
    nombre = CharField(unique=True)
    max_horas_semana = IntegerField(default=20)
    max_horas_dia = IntegerField(default=6)

class ProfesorMateria(BaseModel):
    profesor = ForeignKeyField(Profesor, backref='competencias')
    materia = ForeignKeyField(Materia, backref='profesores')
    class Meta:
        indexes = ((('profesor', 'materia'), True),)

# --- 3. RESULTADO (HORARIO) ---
class Horario(BaseModel):
    dia = IntegerField()      
    hora_inicio = IntegerField()
    hora_fin = IntegerField()    
    profesor = ForeignKeyField(Profesor)
    materia = ForeignKeyField(Materia)
    curso = ForeignKeyField(Curso)

def inicializar_db():
    db.connect()
    db.create_tables([Materia, Curso, Profesor, ProfesorMateria, Horario], safe=True)
    db.close()