-- Executed once when the local PostgreSQL Docker volume is first initialized.
-- For Cloud SQL, apply this versioned schema through a controlled database migration step.
CREATE TABLE IF NOT EXISTS tickets (
    id UUID PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    description VARCHAR(2000) NOT NULL DEFAULT '',
    category VARCHAR(30) NOT NULL CHECK (category IN ('Access', 'Hardware', 'Software', 'Network', 'Other')),
    priority VARCHAR(20) NOT NULL CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    status VARCHAR(20) NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'In Progress', 'Resolved')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets (status);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets (priority);
