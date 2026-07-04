-- Superseded by scripts/update_r16_teams.sql (full Round of 16 fix for matches 89–96).
-- Match 92 only: México vs Inglaterra — kickoff 2026-07-05 18:00 (locks at 17:00).
BEGIN;

UPDATE matches
SET home_team = 'México', away_team = 'Inglaterra', kickoff_at = '2026-07-05 18:00:00'
WHERE match_number = 92;

COMMIT;
