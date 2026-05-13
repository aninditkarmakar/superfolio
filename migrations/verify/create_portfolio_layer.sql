-- Verify superfolio:create_portfolio_layer on pg

BEGIN;

SELECT id, name, reporting_currency, is_active, created_at, updated_at
FROM public.portfolios
WHERE false;

SELECT id, portfolio_id, account_id, created_at
FROM public.portfolio_accounts
WHERE false;

SELECT id, portfolio_id, source_account_id, destination_account_id,
       departure_date, arrival_date, value, currency, note, created_at
FROM public.portfolio_transfer_bridges
WHERE false;

SELECT has_function_privilege('public.create_portfolio(text, text)', 'execute');
SELECT has_function_privilege('public.attach_portfolio_account(text, text, text)', 'execute');
SELECT has_function_privilege(
    'public.create_portfolio_transfer_bridge(text, text, text, text, text, date, date, numeric, text, text)',
    'execute'
);

ROLLBACK;
