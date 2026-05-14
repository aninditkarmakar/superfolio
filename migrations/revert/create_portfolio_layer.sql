-- Revert superfolio:create_portfolio_layer from pg

BEGIN;

DROP FUNCTION IF EXISTS public.create_portfolio_transfer_bridge(
    TEXT, TEXT, TEXT, TEXT, TEXT, DATE, DATE, NUMERIC, TEXT, TEXT
);
DROP FUNCTION IF EXISTS public.attach_portfolio_account(TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.create_portfolio(TEXT, TEXT);
DROP TABLE IF EXISTS public.portfolio_transfer_bridges;
DROP TABLE IF EXISTS public.portfolio_accounts;
DROP TABLE IF EXISTS public.portfolios;

COMMIT;
