from __future__ import annotations

import enum
from datetime import datetime, timezone

from app import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(40), nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    entries = db.relationship("Entry", back_populates="user", lazy="dynamic")
    payments = db.relationship("Payment", back_populates="user", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<User {self.email}>"

    @property
    def public_name(self) -> str:
        name = (self.display_name or "").strip()
        return name or ""


class Entry(db.Model):
    __tablename__ = "entries"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, default="Mi quiniela")
    total_points = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", back_populates="entries")
    payment = db.relationship("Payment", back_populates="entry", uselist=False)
    predictions = db.relationship("Prediction", back_populates="entry", lazy="dynamic")

    __table_args__ = (db.Index("ix_entries_user_id_name", "user_id", "name"),)

    def __repr__(self) -> str:
        return f"<Entry {self.name} user={self.user_id}>"


class Match(db.Model):
    __tablename__ = "matches"

    id = db.Column(db.Integer, primary_key=True)
    match_number = db.Column(db.Integer, unique=True, nullable=False)  # 1–104
    stage = db.Column(db.String(64), nullable=False)  # e.g. group, R16, QF
    home_team = db.Column(db.String(100), nullable=False)
    away_team = db.Column(db.String(100), nullable=False)
    kickoff_at = db.Column(db.DateTime, nullable=True)
    external_match_id = db.Column(db.String(64), nullable=True, index=True)  # API integration (Phase 7)

    result = db.relationship("Result", back_populates="match", uselist=False)
    predictions = db.relationship("Prediction", back_populates="match", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Match {self.match_number} {self.home_team} vs {self.away_team}>"


class Result(db.Model):
    __tablename__ = "results"

    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), unique=True, nullable=False)
    home_score = db.Column(db.Integer, nullable=False)
    away_score = db.Column(db.Integer, nullable=False)
    recorded_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    match = db.relationship("Match", back_populates="result")

    def __repr__(self) -> str:
        return f"<Result m={self.match_id} {self.home_score}-{self.away_score}>"


class Prediction(db.Model):
    __tablename__ = "predictions"

    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("entries.id"), nullable=False, index=True)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False, index=True)
    home_goals = db.Column(db.Integer, nullable=False)
    away_goals = db.Column(db.Integer, nullable=False)
    points_earned = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    entry = db.relationship("Entry", back_populates="predictions")
    match = db.relationship("Match", back_populates="predictions")

    __table_args__ = (db.UniqueConstraint("entry_id", "match_id", name="uq_prediction_entry_match"),)

    def __repr__(self) -> str:
        return f"<Prediction e={self.entry_id} m={self.match_id} {self.home_goals}-{self.away_goals}>"


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("entries.id"), nullable=False, unique=True, index=True)
    amount_mxn = db.Column(db.Integer, nullable=False, default=1000)
    proof_stored_path = db.Column(db.String(512), nullable=True)
    status = db.Column(
        db.Enum(PaymentStatus, name="payment_status", native_enum=False),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    admin_note = db.Column(db.String(500), nullable=True)

    user = db.relationship("User", back_populates="payments")
    entry = db.relationship("Entry", back_populates="payment")

    def __repr__(self) -> str:
        return f"<Payment {self.id} entry={self.entry_id} {self.status}>"


class TournamentState(db.Model):
    __tablename__ = "tournament_state"

    id = db.Column(db.Integer, primary_key=True)
    predictions_locked = db.Column(db.Boolean, default=False, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    @staticmethod
    def get_singleton() -> "TournamentState":
        row = db.session.get(TournamentState, 1)
        if row is None:
            row = TournamentState(id=1, predictions_locked=False)
            db.session.add(row)
            db.session.commit()
        return row
