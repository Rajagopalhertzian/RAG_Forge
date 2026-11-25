-- ContextForge PostgreSQL Initialization
-- Run on database startup to enable extensions

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable uuid-ossp for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pg_trgm for text similarity
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Enable btree_gin for GIN indexes on arrays
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- Create custom types if needed
-- (Tables are created via Alembic migrations)

-- Set default timezone
SET timezone = 'UTC';

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'ContextForge database initialized with extensions: vector, uuid-ossp, pg_trgm, btree_gin';
END $$;