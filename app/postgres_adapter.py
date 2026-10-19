"""PostgreSQL DB-API adapter for the existing SQLite-style application queries.

An incremental compatibility layer. Schema initialization, SQLite PRAGMAs and
SQLite-specific INSERT OR IGNORE still require explicit PostgreSQL migrations.
"""
import re

_SQLITE_LAST_ID=re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\b",re.I)


def placeholders(sql):
    """Convert SQLite placeholders without altering SQL strings or comments."""
    out=[]
    state="normal"
    i=0
    while i<len(sql):
        char=sql[i]
        next_char=sql[i+1] if i+1<len(sql) else ""
        if state=="normal":
            if char=="-" and next_char=="-":
                state="line_comment";out.extend((char,next_char));i+=2;continue
            if char=="/" and next_char=="*":
                state="block_comment";out.extend((char,next_char));i+=2;continue
            if char in ("'",'"'):
                state=char
            out.append("%s" if char=="?" else char)
        elif state in ("'",'"'):
            out.append(char)
            if char==state:
                if next_char==state:
                    out.append(next_char);i+=2;continue
                state="normal"
        elif state=="line_comment":
            out.append(char)
            if char=="\n":state="normal"
        else:
            out.append(char)
            if char=="*" and next_char=="/":
                out.append(next_char);i+=2;state="normal";continue
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
    def fetchmany(self,size=1):
        return [RowAdapter(row) if isinstance(row,dict) else row for row in self._cursor.fetchmany(size)]
    @property
    def rowcount(self):return self._cursor.rowcount
    @property
    def lastrowid(self):
        raise NotImplementedError("PostgreSQL inserts must use RETURNING id")


def _reject_sqlite_only(sql):
    statement=sql.lstrip().upper()
    if statement.startswith("PRAGMA ") or "INSERT OR IGNORE" in statement:
        raise NotImplementedError("SQLite-only SQL requires PostgreSQL migration")


class ConnectionAdapter:
    def __init__(self,connection):self._connection=connection
    def execute(self,sql,params=()):
        _reject_sqlite_only(sql)
        cursor=self._connection.execute(placeholders(sql),params)
        return CursorAdapter(cursor)
    def executemany(self,sql,params):
        _reject_sqlite_only(sql)
        cur=self._connection.cursor()
        try:
            cur.executemany(placeholders(sql),params)
        except Exception:
            cur.close()
            raise
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
