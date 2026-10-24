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
    emoji_name TEXT NOT NULL DEFAULT '',
    emoji_id TEXT NOT NULL DEFAULT '',
    image_mime TEXT NOT NULL DEFAULT '',
    image_data BYTEA,
    set_slug TEXT NOT NULL DEFAULT 'original',
    description TEXT NOT NULL DEFAULT '',
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    embed_color INTEGER NOT NULL DEFAULT 5793266,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS set_slug TEXT NOT NULL DEFAULT 'original';
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS emoji_name TEXT NOT NULL DEFAULT '';
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS emoji_id TEXT NOT NULL DEFAULT '';
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS image_mime TEXT NOT NULL DEFAULT '';
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS image_data BYTEA;
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS stats JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE card_catalog ADD COLUMN IF NOT EXISTS embed_color INTEGER NOT NULL DEFAULT 5793266;


CREATE TABLE IF NOT EXISTS card_sets (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    reward_coins INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO card_sets (slug,name,description,reward_coins)
VALUES ('original','Colección Original','Las primeras cartas de Abo Cards.',250)
ON CONFLICT (slug) DO NOTHING;

CREATE TABLE IF NOT EXISTS card_wallets (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    coins BIGINT NOT NULL DEFAULT 500 CHECK (coins >= 0),
    daily_claimed_at TIMESTAMPTZ,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    xp BIGINT NOT NULL DEFAULT 0,
    level INTEGER NOT NULL DEFAULT 1,
    pity_rare INTEGER NOT NULL DEFAULT 0,
    pity_epic INTEGER NOT NULL DEFAULT 0,
    packs_opened INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, user_id)
);

ALTER TABLE card_wallets ADD COLUMN IF NOT EXISTS xp BIGINT NOT NULL DEFAULT 0;
ALTER TABLE card_wallets ADD COLUMN IF NOT EXISTS level INTEGER NOT NULL DEFAULT 1;
ALTER TABLE card_wallets ADD COLUMN IF NOT EXISTS pity_rare INTEGER NOT NULL DEFAULT 0;
ALTER TABLE card_wallets ADD COLUMN IF NOT EXISTS pity_epic INTEGER NOT NULL DEFAULT 0;
ALTER TABLE card_wallets ADD COLUMN IF NOT EXISTS packs_opened INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS card_set_claims (
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    set_slug TEXT NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id,user_id,set_slug)
);

CREATE TABLE IF NOT EXISTS card_message_templates (
    guild_id BIGINT NOT NULL,
    message_key TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    color INTEGER NOT NULL DEFAULT 5793266,
    updated_by BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (guild_id, message_key)
);

CREATE TABLE IF NOT EXISTS card_admin_audit (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    actor_id BIGINT NOT NULL,
    action TEXT NOT NULL,
    target_id BIGINT,
    card_slug TEXT,
    quantity INTEGER,
    coins BIGINT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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

CREATE TABLE IF NOT EXISTS card_trade_sessions (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_a BIGINT NOT NULL,
    user_b BIGINT NOT NULL,
    channel_id BIGINT,
    offer_a JSONB NOT NULL DEFAULT '{}'::jsonb,
    offer_b JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('active','completed','cancelled')),
    confirmed_a BOOLEAN NOT NULL DEFAULT FALSE,
    confirmed_b BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
ALTER TABLE card_trade_sessions DROP CONSTRAINT IF EXISTS card_trade_sessions_status_check;
ALTER TABLE card_trade_sessions ADD CONSTRAINT card_trade_sessions_status_check CHECK (status IN ('active','completed','cancelled'));
ALTER TABLE card_trade_sessions ADD COLUMN IF NOT EXISTS channel_id BIGINT;
ALTER TABLE card_trade_sessions ADD COLUMN IF NOT EXISTS confirmed_a BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE card_trade_sessions ADD COLUMN IF NOT EXISTS confirmed_b BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_card_trade_sessions_active ON card_trade_sessions (guild_id, channel_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_card_trade_sessions_guild ON card_trade_sessions (guild_id, created_at DESC);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_key TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Evoluciones de cartas (espejo del bot)
CREATE TABLE IF NOT EXISTS card_evolutions (
    base_slug    TEXT PRIMARY KEY REFERENCES card_catalog(slug),
    evolved_slug TEXT NOT NULL REFERENCES card_catalog(slug),
    cost_coins   INTEGER NOT NULL DEFAULT 0,
    cost_copies  INTEGER NOT NULL DEFAULT 3,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
