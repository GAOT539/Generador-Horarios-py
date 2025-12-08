from peewee import Model, CharField, IntegerField, ForeignKeyField
from app.database import db

class BaseModel(Model):
    class Meta:
        database = db

# --- 1. INFRAESTRUCTURA ---
class Aula(BaseModel):
    nombre = CharField(unique=True) 
    tipo = CharField(default="General") 

# --- 2. ACADÉMICO ---
class Materia(BaseModel):
    nombre = CharField() # Ej: "Inglés", "Italiano"
    nivel = IntegerField() # 1, 2, 3, 4
    # Esto responde a tu pedido: "Quiero 3 cursos de Inglés 1"
    cantidad_grupos = IntegerField(default=1) 
    
    # Restricción: No puedes crear dos veces "Inglés Nivel 1"
    class Meta:
        indexes = ((('nombre', 'nivel'), True),)

class Curso(BaseModel):
    nombre = CharField() # "A", "B", "C"
    nivel = IntegerField() 
    turno = CharField() 

# --- 3. DOCENTES ---
class Profesor(BaseModel):
    cedula = CharField(unique=True)
    nombre = CharField()
    max_horas_semana = IntegerField(default=20)
    max_horas_dia = IntegerField(default=6)

class ProfesorMateria(BaseModel):
    profesor = ForeignKeyField(Profesor, backref='competencias')
    materia = ForeignKeyField(Materia, backref='profesores')
    class Meta:
        indexes = ((('profesor', 'materia'), True),)

# --- 4. RESULTADO (HORARIO) ---
class Horario(BaseModel):
    dia = IntegerField()      
    hora_inicio = IntegerField()
    hora_fin = IntegerField()    
    profesor = ForeignKeyField(Profesor)
    materia = ForeignKeyField(Materia)
    aula = ForeignKeyField(Aula)
    curso = ForeignKeyField(Curso)

def inicializar_db():
    db.connect()
    db.create_tables([Aula, Materia, Curso, Profesor, ProfesorMateria, Horario], safe=True)
    db.close()