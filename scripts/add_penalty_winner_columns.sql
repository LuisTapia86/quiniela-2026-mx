-- Optional manual migration (auto-applied on app startup via _ensure_penalty_winner_columns).
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS penalty_winner VARCHAR(100);
ALTER TABLE results ADD COLUMN IF NOT EXISTS penalty_winner VARCHAR(100);
