-- Deploy superfolio:create_portfolio_layer to pg

BEGIN;

CREATE TABLE public.portfolios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    reporting_currency CHAR(3) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT portfolios_name_not_blank_check CHECK (btrim(name) <> ''),
    CONSTRAINT portfolios_reporting_currency_uppercase_check CHECK (reporting_currency ~ '^[A-Z]{3}$')
);

CREATE TABLE public.portfolio_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    account_id UUID NOT NULL REFERENCES public.accounts(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT portfolio_accounts_unique_membership UNIQUE (portfolio_id, account_id)
);

CREATE TABLE public.portfolio_transfer_bridges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
    source_account_id UUID NOT NULL REFERENCES public.accounts(id),
    destination_account_id UUID NOT NULL REFERENCES public.accounts(id),
    departure_date DATE NOT NULL,
    arrival_date DATE NOT NULL,
    value NUMERIC(20, 8) NOT NULL,
    currency CHAR(3) NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT portfolio_transfer_bridges_distinct_accounts_check CHECK (source_account_id <> destination_account_id),
    CONSTRAINT portfolio_transfer_bridges_ordered_dates_check CHECK (departure_date <= arrival_date),
    CONSTRAINT portfolio_transfer_bridges_positive_value_check CHECK (value > 0),
    CONSTRAINT portfolio_transfer_bridges_currency_uppercase_check CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE INDEX portfolio_accounts_account_id_idx ON public.portfolio_accounts (account_id);
CREATE INDEX portfolio_transfer_bridges_portfolio_dates_idx
    ON public.portfolio_transfer_bridges (portfolio_id, departure_date, arrival_date);

CREATE FUNCTION public.create_portfolio(
    p_name TEXT,
    p_reporting_currency TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id UUID;
    v_name TEXT;
    v_reporting_currency TEXT;
    v_existing_reporting_currency TEXT;
BEGIN
    IF p_name IS NULL OR btrim(p_name) = '' THEN
        RAISE EXCEPTION 'portfolio name must not be NULL or blank';
    END IF;
    IF p_reporting_currency IS NULL OR btrim(p_reporting_currency) = '' THEN
        RAISE EXCEPTION 'reporting_currency must not be NULL or blank';
    END IF;

    v_name := btrim(p_name);
    v_reporting_currency := upper(btrim(p_reporting_currency));

    INSERT INTO public.portfolios (name, reporting_currency)
    VALUES (v_name, v_reporting_currency)
    ON CONFLICT (name) DO NOTHING
    RETURNING id INTO v_portfolio_id;

    IF v_portfolio_id IS NOT NULL THEN
        RETURN v_portfolio_id;
    END IF;

    SELECT id, reporting_currency
    INTO v_portfolio_id, v_existing_reporting_currency
    FROM public.portfolios
    WHERE name = v_name;

    IF v_existing_reporting_currency <> v_reporting_currency THEN
        RAISE EXCEPTION 'Portfolio % already exists with reporting_currency %',
            v_name,
            v_existing_reporting_currency;
    END IF;

    RETURN v_portfolio_id;
END;
$$;

CREATE FUNCTION public.attach_portfolio_account(
    p_portfolio_name TEXT,
    p_brokerage_code TEXT,
    p_account_external_id TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id UUID;
    v_account_id UUID;
    v_membership_id UUID;
BEGIN
    SELECT id INTO v_portfolio_id
    FROM public.portfolios
    WHERE name = btrim(p_portfolio_name);

    IF v_portfolio_id IS NULL THEN
        RAISE EXCEPTION 'Unknown portfolio: %', p_portfolio_name;
    END IF;

    SELECT a.id INTO v_account_id
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_brokerage_code))
      AND a.external_id = btrim(p_account_external_id);

    IF v_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown account: % %', p_brokerage_code, p_account_external_id;
    END IF;

    INSERT INTO public.portfolio_accounts (portfolio_id, account_id)
    VALUES (v_portfolio_id, v_account_id)
    ON CONFLICT (portfolio_id, account_id) DO UPDATE
      SET portfolio_id = EXCLUDED.portfolio_id
    RETURNING id INTO v_membership_id;

    RETURN v_membership_id;
END;
$$;

CREATE FUNCTION public.create_portfolio_transfer_bridge(
    p_portfolio_name TEXT,
    p_source_brokerage_code TEXT,
    p_source_account_external_id TEXT,
    p_destination_brokerage_code TEXT,
    p_destination_account_external_id TEXT,
    p_departure_date DATE,
    p_arrival_date DATE,
    p_value NUMERIC,
    p_currency TEXT,
    p_note TEXT DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_portfolio_id UUID;
    v_reporting_currency CHAR(3);
    v_source_account_id UUID;
    v_destination_account_id UUID;
    v_bridge_id UUID;
BEGIN
    SELECT id, reporting_currency INTO v_portfolio_id, v_reporting_currency
    FROM public.portfolios
    WHERE name = btrim(p_portfolio_name);

    IF v_portfolio_id IS NULL THEN
        RAISE EXCEPTION 'Unknown portfolio: %', p_portfolio_name;
    END IF;
    IF p_departure_date IS NULL OR p_arrival_date IS NULL OR p_departure_date > p_arrival_date THEN
        RAISE EXCEPTION 'Invalid bridge date range';
    END IF;
    IF p_value IS NULL OR p_value <= 0 THEN
        RAISE EXCEPTION 'Bridge value must be positive';
    END IF;
    IF upper(btrim(p_currency)) <> v_reporting_currency THEN
        RAISE EXCEPTION 'Bridge currency % does not match portfolio reporting currency %',
            p_currency,
            v_reporting_currency;
    END IF;

    SELECT a.id INTO v_source_account_id
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_source_brokerage_code))
      AND a.external_id = btrim(p_source_account_external_id);

    SELECT a.id INTO v_destination_account_id
    FROM public.accounts a
    JOIN public.brokerages b ON b.id = a.brokerage_id
    WHERE b.code = upper(btrim(p_destination_brokerage_code))
      AND a.external_id = btrim(p_destination_account_external_id);

    IF v_source_account_id IS NULL OR v_destination_account_id IS NULL THEN
        RAISE EXCEPTION 'Unknown bridge source or destination account';
    END IF;
    IF v_source_account_id = v_destination_account_id THEN
        RAISE EXCEPTION 'Bridge source and destination accounts must differ';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.portfolio_accounts
        WHERE portfolio_id = v_portfolio_id AND account_id = v_source_account_id
    ) OR NOT EXISTS (
        SELECT 1 FROM public.portfolio_accounts
        WHERE portfolio_id = v_portfolio_id AND account_id = v_destination_account_id
    ) THEN
        RAISE EXCEPTION 'Bridge source and destination accounts must both belong to the portfolio';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.portfolio_transfer_bridges
        WHERE portfolio_id = v_portfolio_id
          AND source_account_id = v_source_account_id
          AND destination_account_id = v_destination_account_id
          AND (
              (departure_date = p_departure_date AND arrival_date = p_arrival_date)
              OR (
                  CASE WHEN departure_date < arrival_date
                       THEN daterange(departure_date + 1, arrival_date, '[)')
                       ELSE 'empty'::daterange
                  END
                  &&
                  CASE WHEN p_departure_date < p_arrival_date
                       THEN daterange(p_departure_date + 1, p_arrival_date, '[)')
                       ELSE 'empty'::daterange
                  END
              )
          )
    ) THEN
        RAISE EXCEPTION 'Bridge overlaps an existing bridge for this source and destination account';
    END IF;

    INSERT INTO public.portfolio_transfer_bridges (
        portfolio_id,
        source_account_id,
        destination_account_id,
        departure_date,
        arrival_date,
        value,
        currency,
        note
    )
    VALUES (
        v_portfolio_id,
        v_source_account_id,
        v_destination_account_id,
        p_departure_date,
        p_arrival_date,
        p_value,
        upper(btrim(p_currency)),
        NULLIF(btrim(p_note), '')
    )
    RETURNING id INTO v_bridge_id;

    RETURN v_bridge_id;
END;
$$;

COMMIT;
