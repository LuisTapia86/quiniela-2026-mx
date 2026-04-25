from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app import db
from app.models import Entry, Match, Payment, Prediction, TournamentState, User
from app.routes.auth import _validate_display_name, get_current_user, login_required
from app.translations import tr

bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    user = get_current_user()
    if user is None:
        return render_template("landing.html")
    assert user is not None
    entries = list(
        db.session.scalars(
            select(Entry)
            .where(Entry.user_id == user.id)
            .order_by(Entry.id.desc())
        )
    )
    payments_by_entry: dict[int, Payment | None] = {}
    prediction_counts: dict[int, int] = {}
    total_matches = db.session.scalar(select(func.count()).select_from(Match)) or 0
    predictions_locked = TournamentState.get_singleton().predictions_locked
    if entries:
        eids = [e.id for e in entries]
        for p in db.session.scalars(select(Payment).where(Payment.entry_id.in_(eids))):
            payments_by_entry[p.entry_id] = p
        pred_rows = db.session.execute(
            select(Prediction.entry_id, func.count(Prediction.id))
            .where(Prediction.entry_id.in_(eids))
            .group_by(Prediction.entry_id),
        ).all()
        for entry_id, count in pred_rows:
            prediction_counts[int(entry_id)] = int(count)
        for e in entries:
            payments_by_entry.setdefault(e.id, None)
            prediction_counts.setdefault(e.id, 0)
    return render_template(
        "dashboard.html",
        entries=entries,
        payments_by_entry=payments_by_entry,
        prediction_counts=prediction_counts,
        total_matches=total_matches,
        predictions_locked=predictions_locked,
        needs_display_name=not bool((user.display_name or "").strip()),
    )


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = get_current_user()
    assert user is not None
    if request.method == "POST":
        ok_alias, alias_or_error = _validate_display_name(request.form.get("display_name"))
        if not ok_alias:
            flash(alias_or_error, "error")
            return render_template("profile.html", display_name=(request.form.get("display_name") or "").strip())
        alias = alias_or_error
        dup_user = db.session.scalar(
            select(User.id).where(func.lower(User.display_name) == alias.lower(), User.id != user.id),
        )
        if dup_user is not None:
            flash(tr("flash.auth.alias_exists"), "error")
            return render_template("profile.html", display_name=alias)
        user.display_name = alias
        db.session.commit()
        flash(tr("flash.profile.updated"), "ok")
        return redirect(url_for("main.profile"))
    return render_template("profile.html", display_name=(user.display_name or ""))


@bp.get("/health")
def health():
    return jsonify(status="ok", phase=1), 200


def _extract_group_letter(group_name: str | None) -> str | None:
    import re

    value = (group_name or "").strip()
    if not value:
        return None
    m = re.search(r"\b(?:grupo|group)\s+([A-L])\b", value, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).upper()


def _group_stage_matches() -> list[Match]:
    return list(
        db.session.scalars(
            select(Match)
            .options(joinedload(Match.result))
            .where(
                func.lower(Match.stage) == "fase de grupos",
                Match.group_name.is_not(None),
                func.trim(Match.group_name) != "",
            )
            .order_by(Match.match_number.asc(), Match.id.asc()),
        ),
    )


@bp.get("/groups")
def groups():
    letters = [chr(code) for code in range(ord("A"), ord("L") + 1)]
    matches = _group_stage_matches()

    group_rows: dict[str, dict[str, dict]] = {g: {} for g in letters}
    for m in matches:
        home = (m.home_team or "").strip()
        away = (m.away_team or "").strip()
        if not home or not away:
            continue
        group_letter = _extract_group_letter(m.group_name)
        if group_letter not in group_rows:
            continue
        group_bucket = group_rows[group_letter]
        if home not in group_bucket:
            group_bucket[home] = {
                "team": home,
                "played": 0,
                "won": 0,
                "drawn": 0,
                "lost": 0,
                "gf": 0,
                "gc": 0,
                "gd": 0,
                "pts": 0,
            }
        if away not in group_bucket:
            group_bucket[away] = {
                "team": away,
                "played": 0,
                "won": 0,
                "drawn": 0,
                "lost": 0,
                "gf": 0,
                "gc": 0,
                "gd": 0,
                "pts": 0,
            }
        if m.result is None:
            continue
        hs = int(m.result.home_score)
        aw = int(m.result.away_score)
        home_row = group_rows[group_letter][home]
        away_row = group_rows[group_letter][away]
        home_row["played"] += 1
        away_row["played"] += 1
        home_row["gf"] += hs
        home_row["gc"] += aw
        away_row["gf"] += aw
        away_row["gc"] += hs
        if hs > aw:
            home_row["won"] += 1
            away_row["lost"] += 1
            home_row["pts"] += 3
        elif hs < aw:
            away_row["won"] += 1
            home_row["lost"] += 1
            away_row["pts"] += 3
        else:
            home_row["drawn"] += 1
            away_row["drawn"] += 1
            home_row["pts"] += 1
            away_row["pts"] += 1

    for group_letter in letters:
        for row in group_rows[group_letter].values():
            row["gd"] = row["gf"] - row["gc"]

    groups_payload = []
    summary_for_logs: list[str] = []
    for group_letter in letters:
        rows = list(group_rows[group_letter].values())
        rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"].lower()))
        groups_payload.append({"group": group_letter, "rows": rows})
        summary_for_logs.append(f"Grupo {group_letter}: {len(rows)} equipos")

    has_group_data = any(g["rows"] for g in groups_payload)
    current_app.logger.info("Groups summary -> %s", ", ".join(summary_for_logs))
    return render_template("groups/index.html", groups=groups_payload, has_group_data=has_group_data)


@bp.get("/set-language/<lang>")
def set_language(lang: str):
    chosen = (lang or "").strip().lower()
    if chosen in {"es", "en"}:
        session["lang"] = chosen
    next_url = (request.args.get("next") or request.referrer or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("main.index"))
