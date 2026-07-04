-- Round of 16 (Octavos): matches 89–96 — teams and kickoff times only.
BEGIN;

UPDATE matches SET home_team = 'Canadá', away_team = 'Marruecos', kickoff_at = '2026-07-04 11:00:00' WHERE match_number = 89;
UPDATE matches SET home_team = 'Paraguay', away_team = 'Francia', kickoff_at = '2026-07-04 15:00:00' WHERE match_number = 90;
UPDATE matches SET home_team = 'Brasil', away_team = 'Noruega', kickoff_at = '2026-07-05 14:00:00' WHERE match_number = 91;
UPDATE matches SET home_team = 'México', away_team = 'Inglaterra', kickoff_at = '2026-07-05 18:00:00' WHERE match_number = 92;
UPDATE matches SET home_team = 'Portugal', away_team = 'España', kickoff_at = '2026-07-06 13:00:00' WHERE match_number = 93;
UPDATE matches SET home_team = 'Estados Unidos', away_team = 'Bélgica', kickoff_at = '2026-07-06 18:00:00' WHERE match_number = 94;
UPDATE matches SET home_team = 'Argentina', away_team = 'Egipto', kickoff_at = '2026-07-07 10:00:00' WHERE match_number = 95;
UPDATE matches SET home_team = 'Suiza', away_team = 'Colombia', kickoff_at = '2026-07-07 14:00:00' WHERE match_number = 96;

COMMIT;

-- Verify:
-- SELECT match_number, home_team, away_team, kickoff_at FROM matches WHERE match_number BETWEEN 89 AND 96 ORDER BY kickoff_at;
