import click
from flask import Flask


def register_cli(app: Flask) -> None:
    @app.cli.command("seed-matches")
    def seed_matches() -> None:
        """Load 5 sample World Cup 2026 matches (skips if already present)."""
        from sqlalchemy import func, select

        from app import db
        from app.models import Match
        from app.seed import seed_sample_matches

        n = seed_sample_matches()
        if n:
            click.echo(f"Partidos añadidos: {n}.")
        else:
            click.echo("Nada que añadir (los 5 de muestra ya existen).")
        total = db.session.scalar(select(func.count()).select_from(Match)) or 0
        click.echo(f"Total de partidos en la base: {total}.")

    @app.cli.command("set-admin")
    @click.argument("email", type=str, required=True)
    def set_admin(email: str) -> None:
        """Set is_admin=True for the user with this email (case-insensitive)."""
        from app import db
        from app.models import User

        e = (email or "").strip().lower()
        if not e or "@" not in e:
            click.echo("Correo inválido (usa user@dominio).")
            return
        u = User.query.filter_by(email=e).first()
        if u is None:
            click.echo(f'No se encontró ningún usuario con el correo "{e}".')
            return
        u.is_admin = True
        db.session.commit()
        click.echo(f"Listo. {e} ahora es administrador.")

    @app.cli.command("import-matches")
    @click.argument("csv_path", type=click.Path(exists=True, dir_okay=False, path_type=str))
    def import_matches(csv_path: str) -> None:
        """Importa/actualiza partidos desde CSV."""
        from app import db
        from app.services.matches_csv import import_matches_from_path

        summary = import_matches_from_path(csv_path)
        db.session.commit()
        click.echo(
            f"Importación completada. creados={summary['created']} actualizados={summary['updated']} "
            f"omitidos={summary['skipped']}",
        )
        if summary["errors"]:
            click.echo("Errores/avisos:")
            for err in summary["errors"]:
                click.echo(f" - {err}")

    @app.cli.command("generate-matches")
    def generate_matches() -> None:
        """Generate the full 2026 World Cup structure (104 matches) without external API."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import func, select

        from app import db
        from app.models import Match

        def _group_round_robin_matches(group_teams: list[str]) -> list[tuple[str, str]]:
            # Standard 4-team group round robin: 6 matches
            t1, t2, t3, t4 = group_teams
            return [
                (t1, t2),
                (t3, t4),
                (t1, t3),
                (t2, t4),
                (t1, t4),
                (t2, t3),
            ]

        def _all_matches() -> list[tuple[int, str, str, str, datetime]]:
            teams = [f"Team {i:02d}" for i in range(1, 49)]
            groups: dict[str, list[str]] = {}
            letters = "ABCDEFGHIJKL"
            idx = 0
            for letter in letters:
                groups[letter] = teams[idx : idx + 4]
                idx += 4

            kickoff = datetime(2026, 6, 11, 16, 0, tzinfo=timezone.utc)
            slot = timedelta(hours=4)
            match_no = 1
            out: list[tuple[int, str, str, str, datetime]] = []

            # Group stage: 12 groups x 6 matches = 72
            for letter in letters:
                for home, away in _group_round_robin_matches(groups[letter]):
                    out.append((match_no, "Group", home, away, kickoff))
                    match_no += 1
                    kickoff += slot

            # Round of 32: 16 matches
            r32_pairs = [
                ("A1", "B3"), ("C1", "D3"), ("E1", "F3"), ("G1", "H3"),
                ("I1", "J3"), ("K1", "L3"), ("B1", "A3"), ("D1", "C3"),
                ("F1", "E3"), ("H1", "G3"), ("J1", "I3"), ("L1", "K3"),
                ("A2", "B2"), ("C2", "D2"), ("E2", "F2"), ("G2", "H2"),
            ]
            for home, away in r32_pairs:
                out.append((match_no, "Round of 32", home, away, kickoff))
                match_no += 1
                kickoff += slot

            # Round of 16: 8 matches
            for i in range(1, 9):
                out.append((match_no, "Round of 16", f"W{72 + ((i - 1) * 2) + 1}", f"W{72 + ((i - 1) * 2) + 2}", kickoff))
                match_no += 1
                kickoff += slot

            # Quarterfinals: 4
            for i in range(1, 5):
                out.append((match_no, "Quarterfinals", f"W{88 + ((i - 1) * 2) + 1}", f"W{88 + ((i - 1) * 2) + 2}", kickoff))
                match_no += 1
                kickoff += slot

            # Semifinals: 2
            out.append((match_no, "Semifinals", "W97", "W98", kickoff))
            match_no += 1
            kickoff += slot
            out.append((match_no, "Semifinals", "W99", "W100", kickoff))
            match_no += 1
            kickoff += slot

            # Final phase: 2 matches to complete 104 (final + third-place in same stage label)
            out.append((match_no, "Final", "L101", "L102", kickoff))
            match_no += 1
            kickoff += slot
            out.append((match_no, "Final", "W101", "W102", kickoff))
            match_no += 1

            return out

        created = 0
        for match_number, stage, home, away, kickoff_at in _all_matches():
            exists = db.session.scalar(select(Match.id).where(Match.match_number == match_number))
            if exists is not None:
                continue
            db.session.add(
                Match(
                    match_number=match_number,
                    stage=stage,
                    home_team=home,
                    away_team=away,
                    kickoff_at=kickoff_at,
                ),
            )
            created += 1
        if created:
            db.session.commit()

        in_scope_total = (
            db.session.scalar(
                select(func.count())
                .select_from(Match)
                .where(Match.match_number >= 1, Match.match_number <= 104),
            )
            or 0
        )
        if in_scope_total == 104:
            click.echo("104 matches created successfully")
        else:
            click.echo(f"Generated/available matches in range 1-104: {in_scope_total}")
