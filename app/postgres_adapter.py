"""PostgreSQL DB-API adapter for the existing SQLite-style application queries.

An incremental compatibility layer. Schema initialization, SQLite PRAGMAs and
SQLite-specific INSERT OR IGNORE still require explicit PostgreSQL migrations.
"""
import re

_SQLITE_LAST_ID=re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\b",re.I)


def placeholders(sql):
    """Replace positional ? outside SQL single/double-quoted strings with %s."""
    out=[]
    quote=None
    i=0
    while i<len(sql):
        char=sql[i]
        if quote:
            out.append(char)
            if char==quote:
                if i+1<len(sql) and sql[i+1]==quote:
                    out.append(sql[i+1]);i+=1
                else:quote=None
        elif char in ("'",'"'):
            quote=char;out.append(char)
        elif char=="?":out.append("%s")
        else:out.append(char)
        i+=1
    return "".join(out)


class RowAdapter(dict):
    """Support both SQLite positional row[0] and named row["column"] access."""
    def __getitem__(self,key):
        if isinstance(key,int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CursorAdapter:
    def __init__(self,cursor):self._cursor=cursor
    def fetchone(self):
        row=self._cursor.fetchone()
        return RowAdapter(row) if isinstance(row,dict) else row
    def fetchall(self):return [RowAdapter(row) if isinstance(row,dict) else row for row in self._cursor.fetchall()]
    def __iter__(self):
        return (RowAdapter(row) if isinstance(row,dict) else row for row in self._cursor)
    @property
    def rowcount(self):return self._cursor.rowcount
    @property
    def lastrowid(self):
        raise NotImplementedError("PostgreSQL inserts must use RETURNING id")


class ConnectionAdapter:
    def __init__(self,connection):self._connection=connection
    def execute(self,sql,params=()):
        statement=sql.lstrip().upper()
        if statement.startswith("PRAGMA ") or "INSERT OR IGNORE" in statement:
            raise NotImplementedError("SQLite-only SQL requires PostgreSQL migration")
        cursor=self._connection.execute(placeholders(sql),params)
        return CursorAdapter(cursor)
    def executemany(self,sql,params):
        with self._connection.cursor() as cur:
            cur.executemany(placeholders(sql),params)
            return CursorAdapter(cur)
    def __enter__(self):self._connection.__enter__();return self
    def __exit__(self,*args):return self._connection.__exit__(*args)
    def close(self):self._connection.close()
    def commit(self):self._connection.commit()
    def rollback(self):self._connection.rollback()


def connect(dsn):
    import psycopg
    from psycopg.rows import dict_row
    return ConnectionAdapter(psycopg.connect(dsn,row_factory=dict_row))
