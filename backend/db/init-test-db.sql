-- Runs once when the postgres container's data volume is first created.
-- Creates a separate physical database for the test suite so tests never touch
-- development data, while still running against a real PostgreSQL instance (never SQLite).
SELECT 'CREATE DATABASE stock_intel_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'stock_intel_test')
\gexec
