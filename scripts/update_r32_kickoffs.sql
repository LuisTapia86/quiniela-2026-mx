-- Sync Round of 32 kickoff times (matches 73–88). match_number unchanged.
BEGIN;

UPDATE matches SET kickoff_at = '2026-06-28 13:00' WHERE match_number = 73;
UPDATE matches SET kickoff_at = '2026-06-29 11:00' WHERE match_number = 74;
UPDATE matches SET kickoff_at = '2026-06-29 14:30' WHERE match_number = 75;
UPDATE matches SET kickoff_at = '2026-06-29 19:00' WHERE match_number = 76;
UPDATE matches SET kickoff_at = '2026-06-30 11:00' WHERE match_number = 77;
UPDATE matches SET kickoff_at = '2026-06-30 15:00' WHERE match_number = 78;
UPDATE matches SET kickoff_at = '2026-06-30 19:00' WHERE match_number = 79;
UPDATE matches SET kickoff_at = '2026-07-01 10:00' WHERE match_number = 80;
UPDATE matches SET kickoff_at = '2026-07-01 14:00' WHERE match_number = 81;
UPDATE matches SET kickoff_at = '2026-07-01 18:00' WHERE match_number = 82;
UPDATE matches SET kickoff_at = '2026-07-02 13:00' WHERE match_number = 83;
UPDATE matches SET kickoff_at = '2026-07-02 17:00' WHERE match_number = 84;
UPDATE matches SET kickoff_at = '2026-07-02 21:00' WHERE match_number = 85;
UPDATE matches SET kickoff_at = '2026-07-03 12:00' WHERE match_number = 86;
UPDATE matches SET kickoff_at = '2026-07-03 16:00' WHERE match_number = 87;
UPDATE matches SET kickoff_at = '2026-07-03 19:30' WHERE match_number = 88;

COMMIT;

-- Verify:
-- SELECT match_number, home_team, away_team, kickoff_at FROM matches WHERE match_number BETWEEN 73 AND 88 ORDER BY kickoff_at;
