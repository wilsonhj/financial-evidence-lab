-- Shared harness helpers. Included from each *.test.sql via \ir (psql resolves
-- the path relative to the including file). This file deliberately does NOT
-- match *.test.sql, so CI's `for f in tests/*.test.sql` loop never executes it
-- directly.
--
-- expect_rejection runs a statement and requires it to fail with one of the
-- expected SQLSTATEs. The default union covers the guard families used across
-- the harnesses (FK 23503, CHECK 23514, RAISE P0001, unique 23505); call sites
-- SHOULD pass an explicit array whenever a specific state is the contract
-- under test — the default is a fallback, not a precision target.
CREATE FUNCTION pg_temp.expect_rejection(
    test_name text,
    statement text,
    expected_states text[] DEFAULT ARRAY['23503', '23514', 'P0001', '23505']
) RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    actual_state text;
BEGIN
    BEGIN
        EXECUTE statement;
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS actual_state = RETURNED_SQLSTATE;
        IF actual_state = ANY(expected_states) THEN
            RAISE NOTICE 'ok - % rejected with %', test_name, actual_state;
            RETURN;
        END IF;
        RAISE;
    END;
    RAISE EXCEPTION 'not ok - % was accepted', test_name;
END
$$;
