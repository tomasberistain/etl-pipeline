ETL Prueba Técnica — PostgreSQL + Python + Docker

Este proyecto implementa un pipeline de procesamiento de información de transacciones de compañías, a partir de un archivo csv.
El árbol de directorios del proyecto es:

	prueba_docker/
	├─ docker_compose.yml
	├─ requirements.txt
	├─ README.md
	├─ init/
	│  ├─ 01_init.sql
	├─ fuente/
	│  ├─ etl.py
	│  ├─ carga_data.py
	│  └─ utils/
	│      └─ db_config.py
	├─ data/
	│  └─ raw/
	│      └─ data_prueba_tecnica.csv

El flujo general es:

	Raw CSV → Tabla cruda en DB (data_raw) → Transformación → Validación → Tablas finales en DB(companies, charges) → Vistas en SQL

Es decir, se implementó una separación por capas:

	data_raw  →  transformación (Python)  →  dbo  →  vistas

Este sistema garantiza la integridad de los datos, realiza las validaciones necesarias, corrige algunas inconsistencias automáticamente y genera un log de errores que deben ser revisados manualmente.

°°° Sobre Docker °°°

Para correr el proyecto se requiere Docker y docker-compose. El contenedor de PostgreSQL se inicializa automáticamente con los scripts de init/01_init.sql, y las librerías necesarias se instalan desde requirements.txt.
Archivos principales del ETL:

	* fuente/carga_data.py → carga el CSV original (data/raw/data_prueba_tecnica.csv) a la tabla cruda data_raw.data_prueba_tecnica_raw.
	* fuente/etl.py → realiza las transformaciones, validaciones y carga final en dbo.companies y dbo.charges.

Comandos para ejecutar

Levantar los contenedores de Docker:

	* docker-compose up -d --build

Ejecutar el ETL manualmente (si no se configura para correr automáticamente):

	* docker-compose exec app python fuente/carga_data.py
	* docker-compose exec app python fuente/etl.py
	


°°° Sobre la base de datos °°°

Se optó por usar PostgreSQL, pues los datos indicaban que se trataba de un modelo de datos relacional, con Empresas y Transacciones, Relación 1:N (una empresa → muchas transacciones),
un modelo claramente relacional perfectamente manejable por PostgreSQL. Además, de observar los datos se tomaron las siguientes decisiones:
 
 * No debe existir un charge sin company.
 * No debe duplicarse un company_id.

Esto para garantizar consistencia en las transacciones, que sean siempre de una compañía y que esta pueda rastrearse de entre las compañías que se poseen.
Se sugería la siguiente estructura de los datos:

	id varchar(24 NOT NULL
	company_name varchar(130) NULL
	company_id varchar(24) NOT NULL
	amount decimal(16,2) NOT NULL
	status marchar(30) NOT NULL
	created_at timestamp NOT NULL
	updated_at timestamp NULL

Sin embargo, se utilizó varchar(40) tanto para id como para company_id, pues la exploración de los datos reveló que los id en realidad tenían una longitud de 40.
Recortarlos a 24 no fue opción, pues no es posible saber si los primeros 24 caracteres no se repetirán entre id's que pretenden ser únicos. Implicaba riesgo de colisión.

°°° data_raw.data_prueba_tecnica_raw °°°

Replica el CSV original. No aplica validaciones de negocio, sólo se sube la tabla directamente. Sirve como fuente auditable y se carga mediante COPY.
Esto se hace en el script carga_data.py. En este hay un diccionario llamado CONF_TABLA que tiene la configuración de la tabla que se creará con este script. 
Esta tabla se agrega a un schema llamado data_raw, previamente creado en la base de datos.

°°° extracción °°°


Se extrajo la información del CSV original mediante **Python + pandas** (lectura directa en `carga_data.py` y posterior carga con `COPY` de PostgreSQL).  
Se usaron Python y pandas pues pandas permite validaciones rápidas antes de la carga.  
No se generó archivo intermedio (Parquet/Avro) porque el enunciado permite cualquier formato y la carga directa con `COPY` es la forma más eficiente y auditable.  


°°° transformación °°°

Se obtienen los datos de la tabla cruda en base. La transformación se implementó en Python utilizando pandas, permitiendo validación estructurada, limpieza y separación de entidades antes de la carga en las tablas finales dbo.companies y dbo.charges.
Validaciones de existencia de company_id:

	* Cada transacción (charge) debe estar asociada a una compañía existente.
	* Se verifica que company_id no sea nulo.
	* Antes de insertar en dbo.charges, se asegura que la compañía exista en dbo.companies.
	* Si el company_id no existe, la transacción se registra en el log de revisión manual y no se inserta, evitando inconsistencias referenciales.
	

Si se detecta un company_id sin sentido, de una longitud distinta de 40, nulo, etc, se compara el nombre de la compañía con los que ya se encuentran en df_companies. Si este nombre, normalizado, existe, se asigna el company_id de companies.

Los campos created_at y updated_at se transforman a tipo datetime en la etapa de transformación. Debido a que el dataset contiene múltiples formatos de fecha, se implementó una limpieza robusta que:

	* Elimina espacios en blanco.
	* Corrige valores que llegan como flotantes (ej. 20190121.0).
	* Soporta distintos formatos:
		**ISO 8601 (2019-02-27T00:00:00)
		**Formato estándar (2019-02-27)
		**Formato compacto (YYYYMMDD, ej. 20190121)

Para los casos en formato YYYYMMDD, se realiza una conversión explícita usando el patrón %Y%m%d, evitando que pandas los interprete como valores inválidos (NaT).

Validación de duplicados:

	*company_id en dbo.companies se mantiene único usando ON CONFLICT DO UPDATE.

id en dbo.charges también es único; si se intenta insertar un duplicado, se actualizan los campos modificables, garantizando que no haya registros duplicados pero sí se mantenga la información actualizada.

Otros ajustes realizados de validación de campos nulos y tipos:

	* Conversión de amount a tipo numérico (decimal(16,2)).
	* Conversión de created_at y updated_at a tipo datetime.
	* Conversión explícita a string de id y company_id. 

Se eliminan y agregan a un log de revisión manual los siguientes:

	* id nulo (ID de transacción nulo)
	* amount fuera del rango(amount excede DECIMAL(16,2))
	* status incorrecto (status inválido o desconocido: '######')

Se encontraron tres registros en los que el id de transacción no existía. En estos casos se decidió generar un registro para ellos en el log de revisión y no subirlos, esto debido a que no tienen la PK que es absolutamente necesaria en el modelo que contruimos, y a que no hay manera de asegurar su unicidad o no.

Se encontraron tres casos con amounts fuera del rango. Se revisaron manualmente y parecian ser errores de carga o del archivo anterior, por lo que se envían también al log de revisión manual.

Desde una observación de los datos se consideró tomar como estatus válidos los siguientes, y hacer un diccionario con ellos para validar el estatus:

	STATUS_VALIDOS = {
			'expired', 'paid', 'voided', 'pending_payment',
			'partially_refunded', 'pre_authorized', 'charged_back', 'refunded'
		}
	
Se encontraron los siguientes que se consideraron errores, pues no tienen la estructura del resto ni tienen sentido respecto de los datos. Se consideró tratarse de un error de captura manual, por lo que se dejan para revisión manual.

	status inválido o desconocido: 'p&0x3fid'
	status inválido o desconocido: '0xFFFF'

°°° Sobre la vista °°°°

Se generó una vista en PostgreSQL, en el esquema `vistas` (para mantener separación clara de los esquemas de datos crudos y productivos).
Permite consultar fácilmente el monto total transaccionado por día para cada compañía.

	```
	-- =========================
	-- VISTAS EN SCHEMA vistas
	-- =========================
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
Esta vista permite responder directamente preguntas como
	
	* ¿Cuánto facturó cada compañía por día?
	* ¿Qué día tuvo mayor volumen por compañía?

Puede consultarse como:
	
	* SELECT * FROM vistas.daily_company_totals LIMIT 10;
	
°°° Sobre el esquema de la base de datos °°°

Este se encuentra en el archivo esquema.png. Consta de dos tablas, companies y charges, que tienen PK en company_id y id respectivamente. company_id se hereda mediante una FK a charges desde companies.