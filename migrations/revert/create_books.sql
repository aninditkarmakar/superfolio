-- Revert superfolio:create_books from pg

BEGIN;

DROP TABLE IF EXISTS example.books;
DROP SCHEMA IF EXISTS example;

COMMIT;
