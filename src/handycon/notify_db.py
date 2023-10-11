import pathlib

import peewee


db_path = pathlib.Path('/home/gamer/.notifies')
db_path.mkdir(exist_ok=True, parents=True)

db = peewee.SqliteDatabase(db_path / 'data.db', pragmas={
    'journal_mode': 'wal',
    'cache_size': -1024 * 64})


class BaseModel(peewee.Model):

    class Meta:
        database = db


class Toast(BaseModel):

    title = peewee.TextField()
    body = peewee.TextField()
    duration = peewee.IntegerField()
    critical = peewee.BooleanField(default=True)
    to_notify = peewee.BooleanField(default=True)


def add_toast(
        title: str,
        body: str,
        duration: int = 1500
):
    Toast.create(
        title=title,
        body=body,
        duration=duration
    )


Toast.create_table()