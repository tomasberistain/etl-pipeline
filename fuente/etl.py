# fuente/etl.py
import pandas as pd
import re
import unicodedata

from utils.db_config import DatabaseConnection

#FUNCION AUXILIAR PARA NORMALIZAR NOMBRES
def normalizar_nombre(nombre):
    if pd.isna(nombre) or not isinstance(nombre, str):
        return ""

    nombre = unicodedata.normalize('NFD', nombre)
    nombre = ''.join(c for c in nombre if unicodedata.category(c) != 'Mn')

    nombre = nombre.lower().strip()
    nombre = re.sub(r'[^a-z0-9\s]', '', nombre)
    nombre = re.sub(r'\s+', ' ', nombre)
    return nombre.strip()


#FUNCION PARA TRAER LOS DATOS EN df
def traer_raw_df():
    db = DatabaseConnection()
    conn, cursor = db.connect()

    if not conn:
        print("No se pudo establecer conexión")
        return None

    try:
        query = 'SELECT * FROM "data_raw"."data_prueba_tecnica_raw"'
        df = pd.read_sql(query, conn)

        print(f"Número de filas devueltas: {len(df)}")

        df = df.rename(columns={
            df.columns[1]: "nameCompany",
            df.columns[2]: "idCompany",
            df.columns[3]: "amount",
            df.columns[4]: "status",
            df.columns[5]: "created_at",
            df.columns[6]: "updated_at"
        })

        return df

    finally:
        db.close()

#FUNCIÓN PARA TRANSFORMAR LOS TIPOS DE DATO Y RENOMBRAR
def transformar(df):
    df = df.rename(columns={
        "nameCompany": "company_name",
        "idCompany": "company_id"
    })

    # -------- LIMPIEZA FUERTE DE FECHAS --------
    def limpiar_fecha(valor):
        if pd.isna(valor):
            return None

        valor = str(valor).strip()

        # Quitar .0 si viene como float tipo 20190121.0
        if valor.endswith(".0"):
            valor = valor[:-2]

        # Caso YYYYMMDD (8 dígitos)
        if len(valor) == 8 and valor.isdigit():
            return pd.to_datetime(valor, format="%Y%m%d", errors="coerce")

        # Caso ISO o estándar
        return pd.to_datetime(valor, errors="coerce")

    df["created_at"] = df["created_at"].apply(limpiar_fecha)
    df["updated_at"] = df["updated_at"].apply(limpiar_fecha)

    # Conversión numérica
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    return df


#FUNCION QUE LIMPIA Y ESTANDARIZA LOS NOMBRES DE COMPAÑIAS, DESDE EL DATAFRAME
def limpiar_nombres_empresas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame que debe contener al menos las columnas:
        'company_id' y 'company_name'

    Returns
    -------
    pd.DataFrame
        DataFrame con company_id y company_name limpios y únicos
    """

    if not {'company_id', 'company_name'}.issubset(df.columns):
        raise ValueError("El DataFrame debe contener las columnas 'company_id' y 'company_name'")



    # Filtra los company_id que no tienen 40 caracteres
    # Mantener solo las filas donde company_id tiene 40 caracteres
    df = df[df["company_id"].str.len() == 40]

    #Función auxiliar para obtener el nombre más representativo por grupo
    def get_most_common_name(group):
        if group["company_name"].isna().all():
            return None
        # Modo (el más frecuente)
        moda = group["company_name"].mode()
        if not moda.empty:
            return moda.iloc[0]
        # Si no hay moda (todos valores únicos o nulos), tomamos el primero no nulo
        no_nulos = group["company_name"].dropna()
        return no_nulos.iloc[0] if not no_nulos.empty else None

    #Agrupamos y obtenemos un nombre por company_id
    df_companies_clean = (
        df.groupby("company_id", as_index=False)
        .apply(lambda g: pd.Series({
            "company_name": get_most_common_name(g)
        }))
        .reset_index(drop=True)
    )

    #Rellenar nombres que quedaron nulos
    df_companies_clean["company_name"] = df_companies_clean["company_name"].fillna("Desconocido")

    return df_companies_clean

def limpiar_charges(df, df_companies):
    """
    Limpia el dataframe de charges:
    - Elimina y alerta si id es nulo
    - Corrige company_id usando nombre si es posible, sino alerta y elimina
    - Elimina y alerta si amount es inválido para DECIMAL(16,2)
    - Elimina y alerta si status no está en la lista de valores válidos
    - Genera/actualiza alertas_charges_invalidos.csv
    """
    df = df.copy()
    alertas = []

    # Lista de status válidos (según los valores limpios que mencionaste)
    STATUS_VALIDOS = {
        'expired', 'paid', 'voided', 'pending_payment',
        'partially_refunded', 'pre_authorized', 'charged_back', 'refunded'
    }

    # ------------------------------------------------------
    # A. Sin ID → alerta + drop
    # ------------------------------------------------------
    mask_sin_id = df["id"].isna()
    if mask_sin_id.any():
        sin_id = df[mask_sin_id].copy()
        sin_id["motivo"] = "ID de transacción nulo"
        alertas.append(sin_id)
        df = df[~mask_sin_id].copy()

    # ------------------------------------------------------
    # B. company_id inválido → intentar corregir por nombre
    # ------------------------------------------------------
    mask_company_id_valido = (
            df["company_id"].notna() &
            (df["company_id"].astype(str).str.len() == 40)
    )

    df_validos = df[mask_company_id_valido].copy()
    df_dudosos = df[~mask_company_id_valido].copy()

    if not df_dudosos.empty:
        df_companies = df_companies.copy()
        df_companies["company_name_norm"] = df_companies["company_name"].apply(normalizar_nombre)

        df_dudosos = df_dudosos.copy()
        df_dudosos["company_name_norm"] = df_dudosos["company_name"].apply(normalizar_nombre)

        df_corregidos = df_dudosos.merge(
            df_companies[["company_id", "company_name_norm"]],
            on="company_name_norm",
            how="left",
            suffixes=("", "_from_companies")
        )

        mask_encontrado = df_corregidos["company_id_from_companies"].notna()
        df_corregidos.loc[mask_encontrado, "company_id"] = \
            df_corregidos.loc[mask_encontrado, "company_id_from_companies"]

        df_corregidos_validos = df_corregidos[mask_encontrado].drop(
            columns=["company_name_norm", "company_id_from_companies"]
        )

        df_no_corregidos = df_corregidos[~mask_encontrado].drop(
            columns=["company_id_from_companies"]
        )
        df_no_corregidos["motivo"] = df_no_corregidos.apply(
            lambda r: "company_id inválido y nombre no encontrado en catálogo"
            if pd.isna(r["company_id"])
            else "company_id inválido (longitud ≠ 40)",
            axis=1
        )
        alertas.append(df_no_corregidos)

        df = pd.concat([df_validos, df_corregidos_validos], ignore_index=True)
    else:
        df = df_validos.copy()

    # ------------------------------------------------------
    # C. Validación de amount para DECIMAL(16,2)
    # ------------------------------------------------------
    MAX_DECIMAL_16_2 = 99999999999999.99

    mask_amount_invalido = (
            df["amount"].isna() |
            (df["amount"].abs() > MAX_DECIMAL_16_2)
    )

    if mask_amount_invalido.any():
        invalid_amount = df[mask_amount_invalido].copy()

        def get_motivo_amount(row):
            if pd.isna(row["amount"]):
                return "amount es nulo o NaN"
            elif row["amount"] > MAX_DECIMAL_16_2:
                return f"amount excede DECIMAL(16,2) (positivo: {row['amount']:,.2f})"
            elif row["amount"] < -MAX_DECIMAL_16_2:
                return f"amount excede DECIMAL(16,2) (negativo: {row['amount']:,.2f})"
            return "amount inválido"

        invalid_amount["motivo"] = invalid_amount.apply(get_motivo_amount, axis=1)
        alertas.append(invalid_amount)
        df = df[~mask_amount_invalido].copy()

    # ------------------------------------------------------
    # D. Validación de status
    # ------------------------------------------------------
    mask_status_invalido = ~df["status"].isin(STATUS_VALIDOS)

    if mask_status_invalido.any():
        invalid_status = df[mask_status_invalido].copy()
        invalid_status["motivo"] = invalid_status["status"].apply(
            lambda s: f"status inválido o desconocido: '{s}'"
        )
        alertas.append(invalid_status)
        df = df[~mask_status_invalido].copy()

        # Opcional: imprimir conteo rápido para depuración
        print("→ Filas con status inválido detectadas y movidas a alertas:")
        print(invalid_status["status"].value_counts())

    # ------------------------------------------------------
    # E. Guardar todas las alertas
    # ------------------------------------------------------
    if alertas:
        df_alertas = pd.concat(alertas, ignore_index=True)

        if not df_alertas.empty:
            archivo = "alertas_charges_invalidos.csv"
            header = not pd.io.common.file_exists(archivo)

            df_alertas.to_csv(
                archivo,
                mode='a',
                header=header,
                index=False,
                encoding='utf-8'
            )

            print(f"→ Alertas actualizadas en: {archivo}")
            print(f"   Registros agregados esta vez: {len(df_alertas)}")

    # ------------------------------------------------------
    # F. Limpieza final
    # ------------------------------------------------------

    print("Antes del dropna final:", len(df))

    print("Nulos en id:", df["id"].isna().sum())
    print("Nulos en company_id:", df["company_id"].isna().sum())
    print("Nulos en amount:", df["amount"].isna().sum())
    print("Nulos en status:", df["status"].isna().sum())
    print("Nulos en created_at:", df["created_at"].isna().sum())

    df = df.dropna(subset=["id", "company_id", "amount", "status", "created_at"])
    df["company_id"] = df["company_id"].astype(str)
    df["amount"] = pd.to_numeric(df["amount"], errors='coerce')

    return df


#FUNCIONES DE CARGA
def load_companies(df):

    db = DatabaseConnection()
    conn, cursor = db.connect()
    if not conn or not cursor:
        print("No se pudo establecer la conexión")
        return

    try:
        # Insertar cada fila del DataFrame
        for index, row in df.iterrows():

            query = """
                INSERT INTO dbo.companies (company_id, company_name)
                VALUES (%s, %s)
                ON CONFLICT (company_id) DO UPDATE
                SET company_name = EXCLUDED.company_name
            """
            cursor.execute(query, (row['company_id'], row['company_name']))

        conn.commit()
        print("Datos cargados correctamente en la tabla 'companies'")

    except Exception as e:
        conn.rollback()
        print("Error al cargar los datos:", e)
    finally:
        cursor.close()
        conn.close()

def load_charges(df_charges):
    """
    Carga el DataFrame de charges limpios en la tabla 'charges' de PostgreSQL.
    Usa ON CONFLICT para manejar duplicados (actualiza los campos modificables).

    Parámetros:
        df_charges (pd.DataFrame): DataFrame ya limpio con columnas:
            id, company_id, amount, status, created_at, updated_at
    """
    db = DatabaseConnection()
    conn, cursor = db.connect()

    if not conn or not cursor:
        print("No se pudo establecer la conexión a la base de datos")
        return

    try:

        df = df_charges.copy()

        # Convertir NaT de updated_at a None
        df['updated_at'] = df['updated_at'].replace({pd.NaT: None})

        # Insertar cada fila
        inserted_count = 0
        updated_count = 0




        for index, row in df.iterrows():
            query = """
                INSERT INTO dbo.charges (
                    id, company_id, amount, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    company_id  = EXCLUDED.company_id,
                    amount      = EXCLUDED.amount,
                    status      = EXCLUDED.status,
                    created_at  = EXCLUDED.created_at,
                    updated_at  = EXCLUDED.updated_at
            """
            cursor.execute(query, (
                row['id'],
                row['company_id'],
                row['amount'],
                row['status'],
                row['created_at'],
                row['updated_at']
            ))


            inserted_count += 1

        conn.commit()

        print(f"Datos cargados correctamente en la tabla 'charges'")
        print(f"Filas procesadas: {len(df)}")

    except Exception as e:
        if conn:
            conn.rollback()
        print("Error al cargar los datos en 'charges':")
        print(e)


    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()




def main():

    df = traer_raw_df()
    df = transformar(df)


    df_companies_clean = limpiar_nombres_empresas(df)
    df_charges = limpiar_charges(df,df_companies_clean)

    load_companies(df_companies_clean)
    load_charges(df_charges)

main()