from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc, text
from flask_login import LoginManager
from flask_migrate import Migrate
from dotenv import load_dotenv
import os
import time
from threading import Thread
from datetime import datetime

# ---------------------------------
# Global DB object + environment
# ---------------------------------
db = SQLAlchemy()
load_dotenv()

# Dummy email helper so old imports keep working, but nothing is sent.
def send_email_safe(*args, **kwargs):
    print("[MAIL DISABLED] send_email_safe() was called but email sending is turned off.")
    return True


# ========================================================
# CREATE APP
# ========================================================
def create_app():
    # instance_relative_config=True so app.instance_path points to /instance
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = 'hjshjhdjah kjshkjdhjs'

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # ---------- Database config ----------
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set in .env")

    # Ensure psycopg2 driver
    if db_url.startswith("postgresql://") and "+psycopg2" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    print("📌 USING DATABASE:", app.config['SQLALCHEMY_DATABASE_URI'])

    db.init_app(app)
    Migrate(app, db)

    # ---------- Blueprints ----------
    from .views import views
    from .auth import auth
    from .matching_routes import matching_bp

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')
    app.register_blueprint(matching_bp, url_prefix='/')

    # ---------- Models + DB init ----------
    from .models import User
    with app.app_context():
        db.create_all()
        db.session.commit()
        initialize_opinion_dimensions()

    # ---------- Login manager ----------
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    # ---------- DB connection health ----------
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

    # ---------- Start matching scheduler (no emails) ----------
    init_scheduler(app)

    return app


def create_database(app):
    with app.app_context():
        db.create_all()
        print('Created Database!')


# ========================================================
# OPINION DIMENSIONS INITIALIZATION
# ========================================================
def initialize_opinion_dimensions():
    """
    Initialize the 15 opinion dimensions if they are not already present.
    """
    from .models import OpinionDimension

    existing = OpinionDimension.query.count()
    if existing >= 15:
        # already initialized (or more)
        return

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
         "I believe it is possible to find common ground between opposing views.", 1.0),

        # B. TOPIC-SPECIFIC (10)
        ("match_support_main_idea", "Support Main Idea", "matching", 1,
         "I support the main idea behind this topic.", 2.0),
        ("match_benefits_outweigh_risks", "Benefits Outweigh Risks", "matching", 2,
         "I believe the benefits of this topic outweigh its risks.", 1.8),
        ("match_take_action", "Would Take Action", "matching", 3,
         "I would personally take action to support this issue.", 1.5),
        ("match_positive_impact", "Positive Impact", "matching", 4,
         "This issue has an overall positive impact on society.", 1.9),
        ("match_deserves_attention", "Deserves Attention", "matching", 5,
         "This issue deserves more public attention.", 1.3),
        ("match_trust_experts", "Trust Experts", "matching", 6,
         "I trust the experts or authorities on this topic.", 1.4),
        ("match_emotional_connection", "Emotional Connection", "matching", 7,
         "I feel emotionally connected to this issue.", 1.2),
        ("match_opposing_misunderstanding", "Opposition = Misunderstanding", "matching", 8,
         "I think opposing views are often based on misunderstanding.", 1.1),
        ("match_should_be_priority", "Should Be Priority", "matching", 9,
         "Addressing this issue should be a priority.", 1.7),
        ("match_aligns_values", "Aligns with Values", "matching", 10,
         "This topic aligns with my personal values.", 1.6),
    ]

    for name, display_name, qtype, qnum, desc, weight in dimensions:
        existing_dim = OpinionDimension.query.filter_by(name=name).first()
        if existing_dim:
            continue

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
# QUESTIONNAIRE LOGIC (STAYS HERE, USED BY views.py)
# ========================================================
def save_questionnaire_responses(user_id, form_data):
    """
    Save responses from the 15-question questionnaire using -2 to +2 scale.
    """
    from .models import User, UserOpinion, OpinionDimension

    user = User.query.get(user_id)
    if not user:
        return None

    attitude_scores = []

    # Process attitude questions (1-5)
    for i in range(1, 6):
        field_name = f'attitude{i}'
        if field_name in form_data:
            score = float(form_data[field_name])

            dimension = OpinionDimension.query.filter_by(
                question_type='attitude',
                question_number=i
            ).first()

            if dimension:
                opinion = UserOpinion.query.filter_by(
                    user_id=user_id,
                    dimension_id=dimension.id
                ).first()

                if opinion:
                    opinion.score = score
                    opinion.updated_at = datetime.utcnow()
                else:
                    opinion = UserOpinion(
                        user_id=user_id,
                        dimension_id=dimension.id,
                        score=score
                    )
                    db.session.add(opinion)

                attitude_scores.append(score)

    # Process matching questions (1-10)
    for i in range(1, 11):
        field_name = f'match{i}'
        if field_name in form_data:
            score = float(form_data[field_name])

            dimension = OpinionDimension.query.filter_by(
                question_type='matching',
                question_number=i
            ).first()

            if dimension:
                opinion = UserOpinion.query.filter_by(
                    user_id=user_id,
                    dimension_id=dimension.id
                ).first()

                if opinion:
                    opinion.score = score
                    opinion.updated_at = datetime.utcnow()
                else:
                    opinion = UserOpinion(
                        user_id=user_id,
                        dimension_id=dimension.id,
                        score=score
                    )
                    db.session.add(opinion)

    # Calculate openness score (average of 5 attitude questions)
    if attitude_scores:
        openness_score = sum(attitude_scores) / len(attitude_scores)
        user.openness_score = openness_score
        user.is_extremist = openness_score < 0.0  # Threshold: below neutral

    db.session.commit()

    return {
        'openness_score': user.openness_score,
        'is_extremist': user.is_extremist,
        'attitude_scores': attitude_scores
    }


def get_openness_category(openness_score):
    """Categorize user's openness level (-2 to +2 scale)."""
    if openness_score is None:
        return None
    if openness_score >= 1.5:
        return "Very Open-Minded"
    elif openness_score >= 0.5:
        return "Open-Minded"
    elif openness_score >= 0.0:
        return "Moderately Open"
    elif openness_score >= -0.5:
        return "Somewhat Closed"
    else:
        return "Very Closed / Extremist"


# ========================================================
# MATCHING SCHEDULER (NO EMAILS)
# ========================================================
class MatchingScheduler:
    def __init__(self, app):
        self.app = app
        self.running = False
        self.thread = None

    def start(self):
        if not self.running:
            self.running = True
            self.thread = Thread(target=self._run_scheduler, daemon=True)
            self.thread.start()
            print("✓ Matching scheduler started (no emails).")

    def _run_scheduler(self):
        from .matching_service import MatchingService

        while self.running:
            try:
                with self.app.app_context():
                    # Run batch matching
                    stats = MatchingService.run_batch_matching()
                    expired = MatchingService.expire_old_matches()
                    if expired > 0:
                        print(f"✓ Expired {expired} old matches")
            except Exception as e:
                print(f"✗ Scheduler error: {e}")

            # Run every hour
            time.sleep(3600)


# Global scheduler instance
scheduler = None


def init_scheduler(app):
    """Initialize and start the matching scheduler."""
    global scheduler
    if scheduler is None:
        scheduler = MatchingScheduler(app)
        scheduler.start()
    return scheduler

