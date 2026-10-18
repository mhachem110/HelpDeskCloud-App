-- The owner creates the LOGIN role first. This Job owns schema only, not passwords.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'helpdesk') THEN
        RAISE EXCEPTION 'Create the restricted helpdesk login before migration';
    END IF;
END
$$;

REVOKE ALL ON TABLE public.tickets FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO helpdesk;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tickets TO helpdesk;
