-- Deploy superfolio:create_books to pg

BEGIN;

CREATE SCHEMA example;

CREATE TABLE example.books (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    published_year INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT books_published_year_check CHECK (
        published_year IS NULL OR published_year > 0
    )
);

COMMIT;
