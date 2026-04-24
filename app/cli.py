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

    @app.cli.command("make-admin")
    @click.argument("email", type=str, required=True)
    def make_admin(email: str) -> None:
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
