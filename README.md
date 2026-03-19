# etl-pipeline

ETL PostgreSQL + Python + Docker

Este proyecto implementa un pipeline de procesamiento de información de transacciones de compañías, a partir de un archivo CSV.

El árbol de directorios del proyecto es:
```
etl-pipeline/
├─ docker-compose.yml
├─ requirements.txt
├─ README.md
├─ init/
│  └─ 01_init.sql
├─ fuente/
│  ├─ etl.py
│  ├─ carga_data.py
│  └─ utils/
│      └─ db_config.py
├─ data/
│  └─ raw/
│      └─ transactions.csv
```

El flujo general es:
```
Raw CSV → Tabla cruda en DB (data_raw) → Transformación → Validación → Tablas finales en DB (companies, charges) → Vistas en SQL
```

Es decir, se implementó una separación por capas:
```
data_raw  →  transformación (Python)  →  dbo  →  vistas
```

Este sistema garantiza la integridad de los datos, realiza las validaciones necesarias, corrige algunas inconsistencias automáticamente y genera un log de errores que deben ser revisados manualmente.

## Sobre Docker

Para correr el proyecto se requiere Docker y docker-compose. El contenedor de PostgreSQL se inicializa automáticamente con los scripts de `init/01_init.sql`, y las librerías necesarias se instalan desde `requirements.txt`.

Archivos principales del ETL:

- `fuente/carga_data.py` → carga el CSV original (`data/raw/transactions.csv`) a la tabla cruda `data_raw.transactions_raw`.
- `fuente/etl.py` → realiza las transformaciones, validaciones y carga final en `dbo.companies` y `dbo.charges`.

## Comandos para ejecutar

Levantar el contenedor de PostgreSQL:
```bash
docker-compose up -d
```

Ejecutar el ETL:
```bash
python fuente/carga_data.py
python fuente/etl.py
```

## Sobre la base de datos

Se optó por usar PostgreSQL, pues los datos indicaban que se trataba de un modelo de datos relacional, con Empresas y Transacciones, Relación 1:N (una empresa → muchas transacciones), un modelo claramente relacional perfectamente manejable por PostgreSQL. Además, de observar los datos se tomaron las siguientes decisiones:

- No debe existir un charge sin company.
- No debe duplicarse un company_id.

Esto para garantizar consistencia en las transacciones, que sean siempre de una compañía y que esta pueda rastrearse de entre las compañías que se poseen.

Se utilizó `varchar(40)` tanto para `id` como para `company_id`, pues la exploración de los datos reveló que los id en realidad tenían una longitud de 40. Recortarlos a 24 implicaba riesgo de colisión entre id's que pretenden ser únicos.

## Extracción

Se extrajo la información del CSV original mediante **Python + pandas** (lectura directa en `carga_data.py` y posterior carga con `COPY` de PostgreSQL). No se generó archivo intermedio (Parquet/Avro) porque la carga directa con `COPY` es la forma más eficiente y auditable.

## Transformación

Se obtienen los datos de la tabla cruda en base. La transformación se implementó en Python utilizando pandas, permitiendo validación estructurada, limpieza y separación de entidades antes de la carga en las tablas finales `dbo.companies` y `dbo.charges`.

Validaciones de existencia de `company_id`:

- Cada transacción (charge) debe estar asociada a una compañía existente.
- Se verifica que `company_id` no sea nulo.
- Antes de insertar en `dbo.charges`, se asegura que la compañía exista en `dbo.companies`.
- Si el `company_id` no existe, la transacción se registra en el log de revisión manual y no se inserta, evitando inconsistencias referenciales.

Si se detecta un `company_id` sin sentido, de una longitud distinta de 40, nulo, etc., se compara el nombre de la compañía con los que ya se encuentran en `df_companies`. Si este nombre, normalizado, existe, se asigna el `company_id` de companies.

Los campos `created_at` y `updated_at` se transforman a tipo datetime. Debido a que el dataset contiene múltiples formatos de fecha, se implementó una limpieza robusta que:

- Elimina espacios en blanco.
- Corrige valores que llegan como flotantes (ej. `20190121.0`).
- Soporta distintos formatos: ISO 8601, formato estándar (`2019-02-27`) y formato compacto (`YYYYMMDD`).

Validación de duplicados:

- `company_id` en `dbo.companies` se mantiene único usando `ON CONFLICT DO UPDATE`.
- `id` en `dbo.charges` también es único; si se intenta insertar un duplicado, se actualizan los campos modificables.

Registros enviados al log de revisión manual:

- `id` nulo
- `amount` fuera del rango (`DECIMAL(16,2)`)
- `status` inválido

Los status válidos considerados son:
```python
STATUS_VALIDOS = {
    'expired', 'paid', 'voided', 'pending_payment',
    'partially_refunded', 'pre_authorized', 'charged_back', 'refunded'
}
```

## Sobre la vista

Se generó una vista en PostgreSQL en el esquema `vistas`, para mantener separación clara de los esquemas de datos crudos y productivos. Permite consultar el monto total transaccionado por día para cada compañía.
```sql
CREATE OR REPLACE VIEW vistas.daily_company_totals AS
SELECT
    c.company_name,
    DATE(ch.created_at) AS transaction_date,
    SUM(ch.amount) AS total_amount
FROM dbo.charges ch
JOIN dbo.companies c 
    ON ch.company_id = c.company_id
GROUP BY 
    c.company_name, 
    DATE(ch.created_at);
```

Puede consultarse como:
```sql
SELECT * FROM vistas.daily_company_totals LIMIT 10;
```

## Esquema de la base de datos

El esquema se encuentra en `esquema.png`. Consta de dos tablas, `companies` y `charges`, con PK en `company_id` e `id` respectivamente. `company_id` se hereda mediante FK a `charges` desde `companies`.
