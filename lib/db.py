import psycopg2
import psycopg2.extras


def get_connection(database_url: str):
    conn = psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn
