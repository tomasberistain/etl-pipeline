# fuente/carga_data.py
import pandas as pd
import os

from utils.db_config import DatabaseConnection

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DATA_PATH = os.path.join(BASE_DIR, "data", "raw", "data_prueba_tecnica.csv")
SCHEMA_NAME = "data_raw"
TABLE_NAME = "data_prueba_tecnica_raw"


# Definimos la tabla raw que se creará, en el diccionario CONF_TABLA
CONF_TABLA = {
    "id": "VARCHAR(250)",
    "name": "VARCHAR(250)",
    "company_id": "VARCHAR(250)",
    "amount": "VARCHAR(250)",
    "status": "VARCHAR(250)",
    "created_at": "VARCHAR(250)",
    "paid_at": "VARCHAR(250)"
}

#FUNCIÓN QUE CREA LA TABLA CRUDA EN LA BASE
def crear_tabla_raw(db: DatabaseConnection):
    conn, cur = db.connect()
    if conn is None:
        raise RuntimeError("No se pudo conectar a la base de datos")

    try:
        column_defs = [
            f'"{col}" {tipo}'
            for col, tipo in CONF_TABLA.items()
        ]

        column_defs_str = ",\n    ".join(column_defs)

        create_sql = f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_NAME}.{TABLE_NAME} (
            {column_defs_str}
        );
        """

        cur.execute(create_sql)
        conn.commit()

        print(f"Tabla {SCHEMA_NAME}.{TABLE_NAME} creada o verificada.")

    except Exception as e:
        conn.rollback()
        print(f"Error al crear tabla: {e}")
        raise
    finally:
        db.close()

#FUNCIÓN QUE SUBE LOS DATOS DEL CSV A LA TABLA, USANDO COPY
def load_csv_with_copy(db: DatabaseConnection, csv_path: str):

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"No se encuentra el archivo: {csv_path}")

    # Crear tabla
    crear_tabla_raw(db)

    df = pd.read_csv(
        csv_path,
        dtype=str,
    )

    temp_csv = "temp_load.csv"
    df.to_csv(temp_csv, index=False, encoding='utf-8', sep=',', na_rep='')

    conn, cur = db.connect()
    try:
        with open(temp_csv, 'r', encoding='utf-8') as f:
            copy_sql = f"""
            COPY {SCHEMA_NAME}.{TABLE_NAME}
            FROM STDIN
            WITH (
                FORMAT CSV,
                HEADER TRUE,
                DELIMITER ',',
                NULL ''
            );
            """
            cur.copy_expert(copy_sql, f)

        conn.commit()
        print(f"Datos cargados exitosamente en {SCHEMA_NAME}.{TABLE_NAME}")
        print(f"Filas insertadas ≈ {len(df):,}")

    except Exception as e:
        conn.rollback()
        print(f"Error durante COPY: {e}")
        raise
    finally:
        db.close()
        if os.path.exists(temp_csv):
            os.remove(temp_csv)


def main():
    db = DatabaseConnection()
    conn, cur = db.connect()


    try:
        load_csv_with_copy(db, RAW_DATA_PATH)
    except Exception as e:
        print(f"Error en el proceso principal: {e}")



main()