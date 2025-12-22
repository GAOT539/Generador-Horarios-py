from peewee import Model, CharField, IntegerField, ForeignKeyField, TextField
from app.database import db

class BaseModel(Model):
    class Meta:
        database = db

class Materia(BaseModel):
    nombre = CharField()
    nivel = IntegerField()
    desglose_horarios = TextField(default='{}') 

class Profesor(BaseModel):
    nombre = CharField()
    max_horas_semana = IntegerField()
    max_horas_dia = IntegerField()

class ProfesorMateria(BaseModel):
    profesor = ForeignKeyField(Profesor, backref='competencias')
    materia = ForeignKeyField(Materia, backref='profesores')

class Curso(BaseModel):
    nombre = CharField()
    nivel = IntegerField()
    turno = CharField()
    modalidad = CharField()
    
    bloque_horario = IntegerField(null=True)
    dias_clase = CharField(null=True)

class Horario(BaseModel):
    dia = IntegerField()
    hora_inicio = IntegerField()
    hora_fin = IntegerField()
    profesor = ForeignKeyField(Profesor, backref='asignaciones')
    materia = ForeignKeyField(Materia, backref='horarios')
    curso = ForeignKeyField(Curso, backref='horarios')