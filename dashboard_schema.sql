CREATE TABLE IF NOT EXISTS memory (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_memory_user_channel_created
    ON memory (user_id, channel_id, created_at DESC);

CREATE TABLE IF NOT EXISTS warns (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_warns_guild_user_created
    ON warns (guild_id, user_id, created_at);

CREATE TABLE IF NOT EXISTS color_roles (
    guild_id BIGINT NOT NULL,
    categoria TEXT NOT NULL,
    clave TEXT NOT NULL,
    role_id BIGINT NOT NULL,
    PRIMARY KEY (guild_id, categoria, clave)
);

CREATE TABLE IF NOT EXISTS purge_exceptions (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    razon TEXT NOT NULL,
    added_by BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS purge_scans (
    guild_id BIGINT PRIMARY KEY,
    candidate_user_ids BIGINT[] NOT NULL DEFAULT ARRAY[]::BIGINT[],
    scanned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT NOT NULL,
    setting_key TEXT NOT NULL,
    setting_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, setting_key)
);

CREATE TABLE IF NOT EXISTS tickets (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL UNIQUE,
    opener_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    details TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    claimed_by BIGINT,
    closed_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    transcript_message_id BIGINT,
    transcript_url TEXT,
    transcript_html BYTEA
);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS transcript_html BYTEA;
CREATE INDEX IF NOT EXISTS idx_tickets_guild_opener_status
    ON tickets (guild_id, opener_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_one_open_per_user
    ON tickets (guild_id, opener_id) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS ticket_panels (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    image_url TEXT NOT NULL DEFAULT '',
    buttons TEXT NOT NULL DEFAULT '[{"emoji":"🎫","label":"Crear ticket"}]',
    channel_id BIGINT,
    message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (guild_id, name)
);
ALTER TABLE ticket_panels ADD COLUMN IF NOT EXISTS image_url TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_ticket_panels_guild ON ticket_panels (guild_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS card_catalog (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rarity TEXT NOT NULL,
    image_file TEXT NOT NULL,
    drop_weight INTEGER NOT NULL DEFAULT 100,
    base_value INTEGER NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS card_wallets (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    coins BIGINT NOT NULL DEFAULT 500 CHECK (coins >= 0),
    daily_claimed_at TIMESTAMPTZ,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS card_inventory (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    card_slug TEXT NOT NULL REFERENCES card_catalog(slug),
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    first_obtained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id, card_slug)
);
CREATE INDEX IF NOT EXISTS idx_card_inventory_user ON card_inventory (guild_id, user_id, quantity DESC);

CREATE TABLE IF NOT EXISTS card_market_listings (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    seller_id BIGINT NOT NULL,
    card_slug TEXT NOT NULL REFERENCES card_catalog(slug),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    remaining INTEGER NOT NULL CHECK (remaining >= 0),
    price_each BIGINT NOT NULL CHECK (price_each > 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','sold','cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_card_market_active ON card_market_listings (guild_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS card_trades (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    sender_id BIGINT NOT NULL,
    receiver_id BIGINT NOT NULL,
    offered_slug TEXT NOT NULL REFERENCES card_catalog(slug),
    offered_quantity INTEGER NOT NULL CHECK (offered_quantity > 0),
    requested_slug TEXT NOT NULL REFERENCES card_catalog(slug),
    requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_key TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
