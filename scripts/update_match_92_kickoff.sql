-- Match 92 (Octavos): México vs Inglaterra — kickoff 2026-07-05 12:00 (locks at 11:00).
BEGIN;

UPDATE matches
SET kickoff_at = '2026-07-05 12:00:00'
WHERE match_number = 92;

COMMIT;

-- Verify:
-- SELECT match_number, home_team, away_team, kickoff_at FROM matches WHERE match_number = 92;
