from peewee import Model, CharField, IntegerField, ForeignKeyField
from app.database import db

class BaseModel(Model):
    class Meta:
        database = db

# --- 1. ACADÉMICO ---
class Materia(BaseModel):
    nombre = CharField() 
    nivel = IntegerField() 
    # CAMBIO: Desglose detallado de demanda
    cantidad_regular = IntegerField(default=0)      # Lunes a Jueves (Presencial)
    cantidad_online_lj = IntegerField(default=0)    # Lunes a Jueves (Online)
    cantidad_online_fds = IntegerField(default=0)   # Sábado y Domingo (Online)
    
    class Meta:
        indexes = ((('nombre', 'nivel'), True),)

class Curso(BaseModel):
    nombre = CharField() 
    nivel = IntegerField() 
    turno = CharField()     # Matutino, Vespertino, Nocturno, FDS
    modalidad = CharField() # 'REGULAR' o 'ONLINE'

# --- 2. DOCENTES ---
class Profesor(BaseModel):
    nombre = CharField(unique=True)
    max_horas_semana = IntegerField(default=32)
    max_horas_dia = IntegerField(default=8)

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