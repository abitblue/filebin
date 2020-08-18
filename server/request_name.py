import os
import pathlib
import random
import sqlite3
import string
from datetime import datetime, timezone

from dateutil import relativedelta

parent_path = pathlib.Path(__file__).parent.absolute()


def gen_random():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))


class SQLite:
    def __init__(self, file):
        self.file = file

    def __enter__(self):
        self.conn = sqlite3.connect(self.file)
        self.cur = self.conn.cursor()
        # self.conn.row_factory = sqlite3.Row
        return self

    def __exit__(self, type, value, traceback):
        self.conn.commit()
        self.conn.close()

    def check_name(self, name):
        self.cur.execute(f'SELECT EXISTS(SELECT 1 FROM assets WHERE obfuscated_name="{name}");')
        return bool(self.cur.fetchone()[0])

    def get_random_unused_obfuscated_name(self):
        candidate = gen_random()

        while self.check_name(candidate):  # If name is taken, try again
            candidate = gen_random()

        tmp = datetime.now(timezone.utc) + relativedelta.relativedelta(months=1)
        expire = int(datetime(tmp.year, tmp.month, tmp.day, tzinfo=timezone.utc).timestamp())

        # To ensure no conflicts, names cannot be reused, and a request for obfuscated name will immediately write
        # candidate to DB.
        self.cur.execute('INSERT INTO assets(obfuscated_name, expire_time) VALUES (?, ?);', (candidate, expire,))

        return candidate, expire


def initdb():
    # Create assets folder if does not exist
    if not (parent_path / 'assets').exists():
        os.makedirs(parent_path / 'assets')

    # Setup DB is DB doesn't exist
    with SQLite(parent_path / 'project.sqlite3') as sql:
        sql.cur.execute("CREATE TABLE IF NOT EXISTS assets ("
                        "id INTEGER UNIQUE PRIMARY KEY AUTOINCREMENT,"
                        "obfuscated_name TEXT UNIQUE NOT NULL,"
                        "expire_time INTEGER NOT NULL"  # Unix time in UTC
                        ");")


if __name__ == '__main__':
    initdb()
    with SQLite(parent_path / 'project.sqlite3') as sql:
        data = sql.get_random_unused_obfuscated_name()
        print(data[0])
        print(data[1])
