-- One-time fix: Round of 32 teams (matches 73–88). Only home_team / away_team change.
BEGIN;

UPDATE matches SET home_team = 'Sudáfrica', away_team = 'Canadá' WHERE match_number = 73;
UPDATE matches SET home_team = 'Países Bajos', away_team = 'Marruecos' WHERE match_number = 74;
UPDATE matches SET home_team = 'Alemania', away_team = 'Paraguay' WHERE match_number = 75;
UPDATE matches SET home_team = 'Francia', away_team = 'Suecia' WHERE match_number = 76;
UPDATE matches SET home_team = 'Bélgica', away_team = 'Senegal' WHERE match_number = 77;
UPDATE matches SET home_team = 'Estados Unidos', away_team = 'Bosnia y Herzegovina' WHERE match_number = 78;
UPDATE matches SET home_team = 'España', away_team = 'Austria' WHERE match_number = 79;
UPDATE matches SET home_team = 'Portugal', away_team = 'Croacia' WHERE match_number = 80;
UPDATE matches SET home_team = 'Brasil', away_team = 'Japón' WHERE match_number = 81;
UPDATE matches SET home_team = 'Costa de Marfil', away_team = 'Noruega' WHERE match_number = 82;
UPDATE matches SET home_team = 'México', away_team = 'Ecuador' WHERE match_number = 83;
UPDATE matches SET home_team = 'Inglaterra', away_team = 'RD Congo' WHERE match_number = 84;
UPDATE matches SET home_team = 'Suiza', away_team = 'Argelia' WHERE match_number = 85;
UPDATE matches SET home_team = 'Colombia', away_team = 'Ghana' WHERE match_number = 86;
UPDATE matches SET home_team = 'Australia', away_team = 'Egipto' WHERE match_number = 87;
UPDATE matches SET home_team = 'Argentina', away_team = 'Cabo Verde' WHERE match_number = 88;

COMMIT;

-- Verify:
-- SELECT match_number, home_team, away_team FROM matches WHERE match_number BETWEEN 73 AND 88 ORDER BY match_number;
