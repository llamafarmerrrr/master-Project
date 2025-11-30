from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc, text
from flask_login import LoginManager
from flask_migrate import Migrate
from dotenv import load_dotenv
import os
import time
from threading import Thread

# -----------------
# Global DB object
# -----------------
db = SQLAlchemy()

# Load environment variables
load_dotenv()


# ========================================================
# CREATE APP
# ========================================================
def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = 'hjshjhdjah kjshkjdhjs'

    # Make sure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except:
        pass

    # ------------- DATABASE -------------
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set in .env!")

    # Ensure SQLAlchemy format is correct
    if db_url.startswith("postgresql://") and "+psycopg2" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Init DB + Migrate
    db.init_app(app)
    Migrate(app, db)

    # ------------- BLUEPRINTS -------------
    from .views import views
    from .auth import auth
    from .matching_routes import matching_bp

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')
    app.register_blueprint(matching_bp, url_prefix='/')

    # ------------- MODELS + DB CREATE -------------
    from .models import User
    with app.app_context():
        db.create_all()
        initialize_opinion_dimensions()

    # ---------------- LOGIN MANAGER ----------------
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    # ---------------- DB STABILITY ----------------
    @app.before_request
    def before_request():
        try:
            db.session.execute(text("SELECT 1"))
        except exc.SQLAlchemyError:
            db.session.rollback()
            db.session.remove()
            db.engine.dispose()

    @app.teardown_request
    def teardown_request(exception=None):
        db.session.remove()

    # ------------- START MATCHING SCHEDULER -------------
    init_scheduler(app)

    return app


# ========================================================
# OPINION DIMENSIONS INITIALIZATION
# ========================================================
def initialize_opinion_dimensions():
    from .models import OpinionDimension

    existing = OpinionDimension.query.count()
    if existing == 15:
        return  # Already initialized

    dimensions = [
        # A. GENERAL ATTITUDE (5)
        ("attitude_open_to_differ", "Open to Different Opinions", "attitude", 1,
         "I am open to hearing opinions on this topic that differ from my own.", 1.0),
        ("attitude_see_both_sides", "See Both Positive and Negative", "attitude", 2,
         "I can see both positive and negative aspects of this issue.", 1.0),
        ("attitude_willing_adjust", "Willing to Adjust View", "attitude", 3,
         "I would be willing to adjust my view if presented with convincing evidence.", 1.0),
        ("attitude_valid_concerns", "Opponents Have Valid Concerns", "attitude", 4,
         "People who disagree with me may still have valid concerns.", 1.0),
        ("attitude_common_ground", "Possible to Find Common Ground", "attitude", 5,
         "It is possible to find common ground between opposing views.", 1.0),

        # TOPIC-SPECIFIC (10)
        ("match_support_main_idea", "Support Main Idea", "matching", 1,
         "I support the main idea behind this topic.", 2.0),
        ("match_benefits_outweigh_risks", "Benefits Outweigh Risks", "matching", 2,
         "I believe benefits outweigh risks.", 1.8),
        ("match_take_action", "Would Take Action", "matching", 3,
         "I would take action to support this issue.", 1.5),
        ("match_positive_impact", "Positive Impact", "matching", 4,
         "This issue has a positive impact on society.", 1.9),
        ("match_deserves_attention", "Deserves Attention", "matching", 5,
         "This issue deserves more attention.", 1.3),
        ("match_trust_experts", "Trust Experts", "matching", 6,
         "I trust experts on this topic.", 1.4),
        ("match_emotional_connection", "Emotional Connection", "matching", 7,
         "I feel emotionally connected to this topic.", 1.2),
        ("match_opposing_misunderstanding", "Opposition = Misunderstanding", "matching", 8,
         "Opposition is based on misunderstanding.", 1.1),
        ("match_should_be_priority", "Should Be Priority", "matching", 9,
         "This should be a priority.", 1.7),
        ("match_aligns_values", "Aligns with Values", "matching", 10,
         "This aligns with my values.", 1.6),
    ]

    for name, display_name, qtype, qnum, desc, weight in dimensions:
        dim = OpinionDimension(
            name=name,
            display_name=display_name,
            question_type=qtype,
            question_number=qnum,
            description=desc,
            default_weight=weight,
            is_active=True
        )
        db.session.add(dim)

    db.session.commit()
    print("✓ Opinion dimensions initialized.")


# ========================================================
# MATCHING SCHEDULER (MATCHES ONLY — NO EMAIL)
# ========================================================
class MatchingScheduler:
    def __init__(self, app):
        self.app = app
        self.running = False
        self.thread = None

    def start(self):
        if not self.running:
            self.running = True
            self.thread = Thread(target=self.loop, daemon=True)
            self.thread.start()
            print("✓ Matching scheduler started (no email system).")

    def loop(self):
        from .matching_service import MatchingService

        while self.running:
            try:
                with self.app.app_context():
                    MatchingService.run_batch_matching()
                    MatchingService.expire_old_matches()
            except Exception as e:
                print("[SCHEDULER ERROR]", e)

            time.sleep(3600)  # run every hour


scheduler = None


def init_scheduler(app):
    global scheduler
    if scheduler is None:
        scheduler = MatchingScheduler(app)
        scheduler.start()
    return scheduler
