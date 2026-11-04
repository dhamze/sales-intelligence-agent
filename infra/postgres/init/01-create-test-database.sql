-- Runs once, the first time the database volume is created.
-- The main development database (POSTGRES_DB, default `sia_dev`) is created by the image;
-- this adds a separate database that the automated tests may freely wipe.
CREATE DATABASE sia_test;
