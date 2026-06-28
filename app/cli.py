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

    @app.cli.command("update-r32-teams")
    def update_r32_teams() -> None:
        """One-time: set real Round of 32 teams on matches 73–88 (home/away only)."""
        from app import db
        from app.models import Match

        teams: dict[int, tuple[str, str]] = {
            73: ("Sudáfrica", "Canadá"),
            74: ("Países Bajos", "Marruecos"),
            75: ("Alemania", "Paraguay"),
            76: ("Francia", "Suecia"),
            77: ("Bélgica", "Senegal"),
            78: ("Estados Unidos", "Bosnia y Herzegovina"),
            79: ("España", "Austria"),
            80: ("Portugal", "Croacia"),
            81: ("Brasil", "Japón"),
            82: ("Costa de Marfil", "Noruega"),
            83: ("México", "Ecuador"),
            84: ("Inglaterra", "RD Congo"),
            85: ("Suiza", "Argelia"),
            86: ("Colombia", "Ghana"),
            87: ("Australia", "Egipto"),
            88: ("Argentina", "Cabo Verde"),
        }
        updated = 0
        for num, (home, away) in teams.items():
            m = Match.query.filter_by(match_number=num).first()
            if m is None:
                click.echo(f"Partido {num} no encontrado — omitido.")
                continue
            m.home_team = home
            m.away_team = away
            updated += 1
        db.session.commit()
        click.echo(f"Listo. {updated} partidos actualizados (73–88).")

    @app.cli.command("generate-matches")
    def generate_matches() -> None:
        """Generate the full 2026 World Cup structure (104 matches) without external API."""
        from sqlalchemy import func, select

        from app import db
        from app.models import Match
        from app.services.match_generation import generate_world_cup_2026_matches

        _ = generate_world_cup_2026_matches()

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
