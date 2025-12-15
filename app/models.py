from peewee import Model, CharField, IntegerField, ForeignKeyField
from app.database import db

class BaseModel(Model):
    class Meta:
        database = db

# --- 1. ACADÉMICO ---
class Materia(BaseModel):
    nombre = CharField() 
    nivel = IntegerField() 
    cantidad_grupos = IntegerField(default=1) 
    
    class Meta:
        indexes = ((('nombre', 'nivel'), True),)

class Curso(BaseModel):
    nombre = CharField() 
    nivel = IntegerField() 
    turno = CharField() 

# --- 2. DOCENTES ---
class Profesor(BaseModel):
    # ELIMINADO: cedula = CharField(unique=True)
    nombre = CharField()
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