CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    item_name VARCHAR(100) NOT NULL UNIQUE,
    quantity INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

INSERT INTO inventory (item_name, quantity) VALUES
    ('Widget A', 120),
    ('Widget B', 45),
    ('Widget C', 300)
ON CONFLICT (item_name) DO NOTHING;
