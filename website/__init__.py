from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import exc, text
import os
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_mail import Mail, Message
from dotenv import load_dotenv
from datetime import datetime
import time
from threading import Thread  # for scheduler threads

# 🚫 IMPORTANT: do NOT import models here to avoid circular imports
# from .models import ScheduledEmail  # ❌ remove this

# Load environment variables from .env (DATABASE_URL, MAIL_*)
load_dotenv()

db = SQLAlchemy()
mail = Mail()


def send_email_safe(subject, recipients, body=None, html=None, sender=None):
    """
    Central helper to send emails. Uses Flask-Mail and logs any error
    without crashing the whole request.
    """
    try:
        msg = Message(subject=subject, recipients=recipients, sender=sender)
        if body:
            msg.body = body
        if html:
            msg.html = html

        mail.send(msg)
        print(f"[MAIL] Sent email to {recipients} with subject '{subject}'")
        return True
    except Exception as e:
        print(f"[MAIL ERROR] Failed to send email to {recipients}: {e}")
        return False

def create_app():
    # instance_relative_config=True so app.instance_path points to /instance
    app = Flask(__name__, instance_relative_config=True)
    app.config['SECRET_KEY'] = 'hjshjhdjah kjshkjdhjs'

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # 🔴 Database Configuration – use shared PostgreSQL from .env
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set in .env")

    # Make sure driver is correct for SQLAlchemy
    if db_url.startswith("postgresql://") and "+psycopg2" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    print("📌 USING DATABASE:", app.config['SQLALCHEMY_DATABASE_URI'])

       # 📧 Email Configuration (read from environment so it works on hosting)
    # Examples for Gmail (set these in your .env / hosting env):
    #   MAIL_SERVER=smtp.gmail.com
    #   MAIL_PORT=587
    #   MAIL_USE_TLS=true
    #   MAIL_USERNAME=togethertolerant@gmail.com
    #   MAIL_PASSWORD=your_16_char_app_password_without_spaces
    #   MAIL_DEFAULT_SENDER_EMAIL=togethertolerant@gmail.com
    #   MAIL_DEFAULT_SENDER_NAME=Tolerance Together

    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    app.config['MAIL_USE_SSL'] = False  # we use TLS on port 587

    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')

    default_sender_email = os.getenv('MAIL_DEFAULT_SENDER_EMAIL', app.config['MAIL_USERNAME'])
    default_sender_name = os.getenv('MAIL_DEFAULT_SENDER_NAME', 'Tolerance Together')
    app.config['MAIL_DEFAULT_SENDER'] = (default_sender_name, default_sender_email)

    # make sure sending is NOT suppressed
    app.config['MAIL_SUPPRESS_SEND'] = False

    mail.init_app(app)
    db.init_app(app)
    migrate = Migrate(app, db)

    # Blueprints
    from .views import views
    from .auth import auth
    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')

    # Matching blueprint
    from .matching_routes import matching_bp
    app.register_blueprint(matching_bp)

    # Import models only AFTER db is created
    from .models import User

    # Optional: create tables if they don't exist
    with app.app_context():
        db.create_all()
        db.session.commit()
        initialize_opinion_dimensions()

    # Login manager
    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    @app.before_request
    def before_request():
        # Check if the database connection is valid
        try:
            db.session.execute(text("SELECT 1"))
        except exc.SQLAlchemyError:
            db.session.rollback()
            db.session.remove()
            db.engine.dispose()

    @app.teardown_request
    def teardown_request(exception=None):
        # Ensure that the session is properly closed at the end of the request
        db.session.remove()

    @app.errorhandler(500)
    def handle_internal_server_error(e):
        return "Internal Server Error", 500

    # ✅ TEST EMAIL ROUTE — for debugging mail
    @app.route("/test-receive")
    def test_receive():
        try:
            msg = Message(
                subject="Test to Gmail Inbox",
                recipients=["togethertolerant@gmail.com"],
                body="If you see this, receiving works."
            )
            mail.send(msg)
            return "Email sent to Gmail inbox!"
        except Exception as e:
            print("MAIL ERROR:", e)
            return f"Error while sending mail: {e}", 500

    # Start autonomous matching + follow-up scheduler
    init_scheduler(app)

    return app


def create_database(app):
    with app.app_context():
        db.create_all()
        print('Created Database!')


# ========================================
# Opinion dimensions + questionnaire logic
# ========================================

def initialize_opinion_dimensions():
    """
    Initialize the 15 opinion dimensions:
    A. General Attitude (5 questions) - For screening extremists
    B. Topic-Specific (10 questions) - For opposition matching
    """
    from .models import OpinionDimension

    dimensions = [
        # A. GENERAL ATTITUDE (5)
        {
            'name': 'attitude_open_to_differ',
            'display_name': 'Open to Different Opinions',
            'question_type': 'attitude',
            'question_number': 1,
            'description': 'I am open to hearing opinions on this topic that differ from my own.',
            'weight': 1.0
        },
        {
            'name': 'attitude_see_both_sides',
            'display_name': 'See Both Positive and Negative',
            'question_type': 'attitude',
            'question_number': 2,
            'description': 'I can see both positive and negative aspects of this issue.',
            'weight': 1.0
        },
        {
            'name': 'attitude_willing_adjust',
            'display_name': 'Willing to Adjust View',
            'question_type': 'attitude',
            'question_number': 3,
            'description': 'I would be willing to adjust my view if presented with convincing evidence.',
            'weight': 1.0
        },
        {
            'name': 'attitude_valid_concerns',
            'display_name': 'Opponents Have Valid Concerns',
            'question_type': 'attitude',
            'question_number': 4,
            'description': 'People who disagree with me on this topic may still have valid concerns.',
            'weight': 1.0
        },
        {
            'name': 'attitude_common_ground',
            'display_name': 'Possible to Find Common Ground',
            'question_type': 'attitude',
            'question_number': 5,
            'description': 'I believe it\'s possible to find common ground between opposing views on this issue.',
            'weight': 1.0
        },

        # B. TOPIC-SPECIFIC ATTITUDE (10)
        {
            'name': 'match_support_main_idea',
            'display_name': 'Support Main Idea/Goal',
            'question_type': 'matching',
            'question_number': 1,
            'description': 'I generally support the main idea or goal of this topic.',
            'weight': 2.0
        },
        {
            'name': 'match_benefits_outweigh_risks',
            'display_name': 'Benefits Outweigh Risks',
            'question_type': 'matching',
            'question_number': 2,
            'description': 'I believe the benefits of this topic outweigh its risks.',
            'weight': 1.8
        },
        {
            'name': 'match_take_action',
            'display_name': 'Would Take Action',
            'question_type': 'matching',
            'question_number': 3,
            'description': 'I would personally take action in support of this issue.',
            'weight': 1.5
        },
        {
            'name': 'match_positive_impact',
            'display_name': 'Positive Impact on Society',
            'question_type': 'matching',
            'question_number': 4,
            'description': 'I think this issue has an overall positive impact on society.',
            'weight': 1.9
        },
        {
            'name': 'match_deserves_attention',
            'display_name': 'Deserves Public Attention',
            'question_type': 'matching',
            'question_number': 5,
            'description': 'I believe this topic deserves more public attention.',
            'weight': 1.3
        },
        {
            'name': 'match_trust_experts',
            'display_name': 'Trust Experts/Authorities',
            'question_type': 'matching',
            'question_number': 6,
            'description': 'I trust the experts or authorities who promote this topic.',
            'weight': 1.4
        },
        {
            'name': 'match_emotional_connection',
            'display_name': 'Emotionally Connected',
            'question_type': 'matching',
            'question_number': 7,
            'description': 'I feel emotionally connected to this issue.',
            'weight': 1.2
        },
        {
            'name': 'match_opposing_misunderstanding',
            'display_name': 'Opposing Views Based on Misunderstanding',
            'question_type': 'matching',
            'question_number': 8,
            'description': 'I think opposing views on this topic are often based on misunderstanding.',
            'weight': 1.1
        },
        {
            'name': 'match_should_be_priority',
            'display_name': 'Should Be a Priority',
            'question_type': 'matching',
            'question_number': 9,
            'description': 'I believe addressing this issue should be a priority.',
            'weight': 1.7
        },
        {
            'name': 'match_aligns_values',
            'display_name': 'Aligns with Personal Values',
            'question_type': 'matching',
            'question_number': 10,
            'description': 'I think this topic aligns with my personal values.',
            'weight': 1.6
        },
    ]

    for dim_data in dimensions:
        existing = OpinionDimension.query.filter_by(name=dim_data['name']).first()
        if not existing:
            dimension = OpinionDimension(
                name=dim_data['name'],
                display_name=dim_data['display_name'],
                question_type=dim_data['question_type'],
                question_number=dim_data['question_number'],
                description=dim_data['description'],
                default_weight=dim_data['weight'],
                is_active=True
            )
            db.session.add(dimension)

    db.session.commit()
    print("✓ Initialized 15 opinion dimensions")


def save_questionnaire_responses(user_id, form_data):
    """
    Save responses from the 15-question questionnaire
    Using -2 to +2 scale (no conversion needed)
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
    """Categorize user's openness level (-2 to +2 scale)"""
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


# ========================================
# Follow-up Email Sending
# ========================================

def send_due_followup_emails():
    """Send follow-up emails that are scheduled and due."""
    # Import models here to avoid circular import at module load time
    from .models import User, ScheduledEmail

    now = datetime.utcnow()

    pending = ScheduledEmail.query.filter(
        ScheduledEmail.sent.is_(False),
        ScheduledEmail.send_at <= now
    ).all()

    if not pending:
        return

    print(f"⏰ Sending {len(pending)} scheduled follow-up email(s)")

    for email in pending:
        user = User.query.get(email.user_id)
        if not user or not user.email:
            # Nothing to send, mark as done so we don't retry forever
            email.sent = True
            db.session.commit()
            continue

        try:
            msg = Message(
                subject=email.subject,
                recipients=[user.email],
            )
            msg.html = email.body_html
            mail.send(msg)

            email.sent = True
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error sending scheduled email {email.id}: {e}")


# ========================================
# Scheduler Class (matching + follow-up)
# ========================================

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
            print("✓ Autonomous matching + follow-up scheduler started")

    def _run_scheduler(self):
        from .matching_service import MatchingService

        while self.running:
            try:
                with self.app.app_context():
                    # 1) Run matching
                    stats = MatchingService.run_batch_matching()
                    expired = MatchingService.expire_old_matches()
                    if expired > 0:
                        print(f"✓ Expired {expired} old matches")

                    # 2) Send any due follow-up emails
                    send_due_followup_emails()
            except Exception as e:
                print(f"✗ Scheduler error: {e}")

            time.sleep(3600)  # Run every hour


# Global scheduler instance
scheduler = None


def init_scheduler(app):
    """Initialize and start the scheduler"""
    global scheduler
    if scheduler is None:
        scheduler = MatchingScheduler(app)
        scheduler.start()
    return scheduler
