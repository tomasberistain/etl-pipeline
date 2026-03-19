# fuente/utils/db_config.py
import os
from typing import Optional, Tuple
import psycopg2
from psycopg2 import DatabaseError, OperationalError

# ────────────────────────────────────────────────

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "charges_db")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASS = os.getenv("DB_PASSWORD", "admin1234")


# ────────────────────────────────────────────────

class DatabaseConnection:
    """
    Clase para manejar conexión a PostgreSQL de forma similar al estilo anterior.
    Uso recomendado:

        db = DatabaseConnection()
        conn, cur = db.connect()
        if conn is None:
            # manejar error
        try:
            # trabajar con cur
            cur.execute(...)
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            db.close()
    """

    def __init__(self):
        self.conn: Optional[psycopg2.extensions.connection] = None
        self.cursor: Optional[psycopg2.extensions.cursor] = None

    def connect(self) -> Tuple[Optional[psycopg2.extensions.connection],
                              Optional[psycopg2.extensions.cursor]]:
        """Establece la conexión a PostgreSQL."""
        if self.conn is not None and not self.conn.closed:
            print("Conexión ya está abierta.")
            return self.conn, self.cursor

        try:
            self.conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS,
            )
            self.cursor = self.conn.cursor()
            print("Conexión establecida con éxito.")
            return self.conn, self.cursor

        except OperationalError as e:
            print(f"Error de conexión (¿está corriendo Postgres?): {e}")
            return None, None
        except DatabaseError as e:
            print(f"Error al conectar a la base de datos: {e}")
            return None, None

    def close(self) -> None:
        """Cierra cursor y conexión de forma segura."""
        if self.cursor:
            try:
                self.cursor.close()
            except Exception:
                pass
            self.cursor = None

        if self.conn and not self.conn.closed:
            try:
                self.conn.close()
                print("Conexión cerrada.")
            except Exception:
                pass
            self.conn = None

    def execute_query(
        self,
        query: str,
        params: tuple = None,
        fetch: bool = False,
        commit: bool = True
    ) -> Optional[Tuple[list, int]]:
        """
        Ejecuta una consulta SQL.
        Retorna:
        - (filas, rowcount) si fetch=True
        - rowcount si es INSERT/UPDATE/DELETE y commit=True
        - None en caso de error
        """
        if not self.conn or self.conn.closed:
            print("No hay conexión activa. Llama a .connect() primero.")
            return None

        try:
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)

            if fetch:
                rows = self.cursor.fetchall()
                return rows, self.cursor.rowcount

            if commit and not query.strip().upper().startswith(("SELECT", "WITH")):
                self.conn.commit()

            return None, self.cursor.rowcount

        except DatabaseError as e:
            print(f"Error al ejecutar consulta:\n{query}\n{e}")
            if self.conn:
                self.conn.rollback()
            return None

    # Método de conveniencia para selects
    def fetch_all(self, query: str, params: tuple = None) -> Optional[list]:
        result = self.execute_query(query, params, fetch=True, commit=False)
        if result:
            return result[0]
        return None

    # Método de conveniencia para inserts/updates con retorno de filas afectadas
    def execute_and_commit(self, query: str, params: tuple = None) -> Optional[int]:
        result = self.execute_query(query, params, fetch=False, commit=True)
        if result:
            return result[1]
        return None