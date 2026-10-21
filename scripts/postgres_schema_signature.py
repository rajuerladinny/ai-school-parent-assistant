"""Compare structural catalog definitions without reading application records."""


def signature(connection, schema):
    # Fully qualify deparsed definitions so search_path cannot hide differences.
    connection.execute("SET LOCAL search_path TO pg_catalog")
    queries = {
        "relations": """SELECT c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s ORDER BY c.relname""",
        "columns": """SELECT c.relname,a.attnum,a.attname,format_type(a.atttypid,a.atttypmod),
            a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid),co.collname
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            LEFT JOIN pg_collation co ON co.oid=a.attcollation
            WHERE n.nspname=%s AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY c.relname,a.attnum""",
        "constraints": """SELECT c.relname,k.conname,k.contype,k.convalidated,
            k.condeferrable,k.condeferred,pg_get_constraintdef(k.oid)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s
            ORDER BY c.relname,k.conname""",
        "indexes": """SELECT c.relname,i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid)
            FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s ORDER BY c.relname""",
        "triggers": """SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid)
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND NOT t.tgisinternal ORDER BY c.relname,t.tgname""",
        "functions": """SELECT p.proname,pg_get_functiondef(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=%s ORDER BY p.proname,p.oid::regprocedure::text""",
        "sequences": """SELECT c.relname,format_type(s.seqtypid,NULL),s.seqstart,s.seqincrement,
            s.seqmax,s.seqmin,s.seqcache,s.seqcycle,t.relname,a.attname
            FROM pg_sequence s JOIN pg_class c ON c.oid=s.seqrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_depend d ON d.objid=c.oid AND d.deptype IN ('a','i')
            LEFT JOIN pg_class t ON t.oid=d.refobjid
            LEFT JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid
            WHERE n.nspname=%s ORDER BY c.relname""",
        "policies": """SELECT tablename,policyname,permissive,roles,cmd,qual,with_check
            FROM pg_policies WHERE schemaname=%s ORDER BY tablename,policyname""",
        "extra_types": """SELECT t.typname,t.typtype FROM pg_type t
            JOIN pg_namespace n ON n.oid=t.typnamespace
            WHERE n.nspname=%s AND t.typrelid=0 AND t.typelem=0 ORDER BY t.typname""",
        "rules": """SELECT c.relname,r.rulename,pg_get_ruledef(r.oid)
            FROM pg_rewrite r JOIN pg_class c ON c.oid=r.ev_class
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s ORDER BY c.relname,r.rulename""",
    }
    def normalize(value):
        if isinstance(value, str):
            return value.replace(schema + ".", "public.")
        return value
    return {key: [tuple(normalize(value) for value in row)
                  for row in connection.execute(query, (schema,)).fetchall()]
            for key, query in queries.items()}
