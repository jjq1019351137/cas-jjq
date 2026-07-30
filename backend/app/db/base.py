from sqlalchemy import Text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


@compiles(Text, "mysql")
def _text_as_longtext(type_, compiler, **kw):
    return "LONGTEXT"


import app.models
