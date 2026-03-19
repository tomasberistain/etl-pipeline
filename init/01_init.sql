-- Crear esquemas
CREATE SCHEMA IF NOT EXISTS dbo;
CREATE SCHEMA IF NOT EXISTS vistas;
CREATE SCHEMA IF NOT EXISTS data_raw;

-- =========================
-- TABLAS EN SCHEMA dbo
-- =========================
CREATE TABLE dbo.companies (
    company_id VARCHAR(40) NOT NULL PRIMARY KEY,
    company_name VARCHAR(130) NULL
);

CREATE TABLE dbo.charges (
    id VARCHAR(40) NOT NULL,
    company_id VARCHAR(40) NOT NULL,
    amount NUMERIC(16,2) NOT NULL,
    status VARCHAR(30) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NULL,
    CONSTRAINT charges_pkey PRIMARY KEY (id),
    CONSTRAINT fk_company_id
        FOREIGN KEY (company_id)
        REFERENCES dbo.companies (company_id)
);

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