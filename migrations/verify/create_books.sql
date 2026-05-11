-- Verify superfolio:create_books on pg

BEGIN;

SELECT 1 / count(*)
FROM information_schema.schemata
WHERE schema_name = 'example';

SELECT 1 / count(*)
FROM information_schema.tables
WHERE table_schema = 'example'
  AND table_name = 'books';

SELECT 1 / (count(*) = 5)::int
FROM information_schema.columns
WHERE table_schema = 'example'
  AND table_name = 'books'
  AND column_name IN ('id', 'title', 'author', 'published_year', 'created_at');

ROLLBACK;
