"""The one way the agent code opens the database.

Every connection in one process has to be opened the same way: DuckDB keeps
one database instance per file and process, and refuses a second connection
with a different configuration - "Can't open a connection to same database
file with a different configuration than existing connections". On the
command line one question opens one connection at a time and never met that.
wiki_service.py answers two at once, and resolve_names, which opened the file
without the setting below, failed every query running beside it.

Its own module so that resolve_names can use it as well as sentence_to_sql,
which imports resolve_names and so cannot be imported by it.
"""


def connect_db(db_path: str):
    """Open the database for SQL the model may have written.

    Read-only because this only ever SELECTs, and a read-write handle takes an
    exclusive lock on the file - one pipeline run would otherwise fail the
    moment a DuckDB CLI, compare_models.py or eval_stage1.py had the same
    database open, and block them in turn. No file access, because read_only
    does not stop read_csv('/etc/passwd') or COPY ... TO a file.

    Lambdas are DuckDB's default `lambda w: ...` form only. The stage 2 model
    served since 2026-11-13 was trained on it; the arrow form (w -> ...) the
    one before wrote is off by default in 2.0 and gone in 2.1, and is no
    longer switched back on here.
    """
    import duckdb
    return duckdb.connect(db_path, read_only=True,
                          config={"enable_external_access": False})
