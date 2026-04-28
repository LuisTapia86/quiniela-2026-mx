from app.routes.admin import bp as admin_bp
from app.routes.api import bp as api_bp
from app.routes.auth import bp as auth_bp
from app.routes.entries import bp as entries_bp
from app.routes.leaderboard import bp as leaderboard_bp
from app.routes.main import bp as main_bp
from app.routes.emergency_reset import bp as emergency_reset_bp
from app.routes.rules import bp as rules_bp

__all__ = [
    "admin_bp",
    "api_bp",
    "auth_bp",
    "entries_bp",
    "emergency_reset_bp",
    "leaderboard_bp",
    "main_bp",
    "rules_bp",
]
