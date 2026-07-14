DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'liyans_migrator') THEN
        CREATE ROLE liyans_migrator
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            PASSWORD 'liyans-migrator-local-only';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'liyans_app') THEN
        CREATE ROLE liyans_app
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            PASSWORD 'liyans-app-local-only';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'liyans_dispatcher') THEN
        CREATE ROLE liyans_dispatcher
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            NOBYPASSRLS
            PASSWORD 'liyans-dispatcher-local-only';
    END IF;
END
$$;

ALTER DATABASE liyans OWNER TO liyans_migrator;
ALTER SCHEMA public OWNER TO liyans_migrator;

REVOKE CONNECT, TEMPORARY ON DATABASE liyans FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

GRANT CONNECT ON DATABASE liyans TO liyans_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO liyans_migrator;
GRANT CONNECT ON DATABASE liyans TO liyans_app;
GRANT USAGE ON SCHEMA public TO liyans_app;
GRANT CONNECT ON DATABASE liyans TO liyans_dispatcher;
GRANT USAGE ON SCHEMA public TO liyans_dispatcher;
