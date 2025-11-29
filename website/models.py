from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func
from datetime import datetime  # ADD THIS IMPORT


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(500))
    user_name = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    family_name = db.Column(db.String(150))
    demo = db.Column(db.Boolean, default=False)
    gender = db.Column(db.String(100))
    age = db.Column(db.String(100))
    education = db.Column(db.String(100))
    job = db.Column(db.String(100)) 

    topic = db.Column(db.String(100))  # Already exists ✓

    classification = db.Column(db.Integer)

    haspartner = db.Column(db.Boolean, default=False)  # Already exists ✓
    partner_id = db.Column(db.Integer)
    meeting_id = db.Column(db.Integer)
    hasarrived = db.Column(db.Boolean, default=False)
    perspective_score = db.Column(db.Float)
    behaviour_score = db.Column(db.Float)
    paypal = db.Column(db.Boolean, default=False)

    classification_p = db.Column(db.Integer)
    
    # ========================================
    #  ATTITUDE COLUMNS
    # ========================================
    attitude1 = db.Column(db.Integer)  # - openness to different opinions
    attitude2 = db.Column(db.Integer)  # - see both sides
    attitude3 = db.Column(db.Integer)  # - willing to adjust view
    attitude4 = db.Column(db.Integer)  # - valid concerns from others
    attitude5 = db.Column(db.Integer)  # - find common ground


    # PRE-DISCUSSION opinion responses (from new_questionnaire_part2.html)
    match1 = db.Column(db.Integer)
    match2 = db.Column(db.Integer)
    match3 = db.Column(db.Integer)
    match4 = db.Column(db.Integer)
    match5 = db.Column(db.Integer)
    match6 = db.Column(db.Integer)
    match7 = db.Column(db.Integer)
    match8 = db.Column(db.Integer)
    match9 = db.Column(db.Integer)
    match10 = db.Column(db.Integer)

    # Availability for up to three time slots
    time_slot_1 = db.Column(db.String(50), nullable=True)
    time_slot_2 = db.Column(db.String(50), nullable=True)
    time_slot_3 = db.Column(db.String(50), nullable=True)

        # Post-discussion opinion response (after the discussion)
    post_match1_support = db.Column(db.Integer)              # I generally support the main idea or goal of this topic
    post_match2_benefits = db.Column(db.Integer)             # I believe the benefits of this topic outweigh its risks
    post_match3_action = db.Column(db.Integer)               # I would personally take action in support of this issue
    post_match4_impact = db.Column(db.Integer)               # I think this issue has an overall positive impact on society
    post_match5_attention = db.Column(db.Integer)            # I believe this topic deserves more public attention
    post_match6_trust = db.Column(db.Integer)                # I trust the experts or authorities who promote this topic
    post_match7_econnected = db.Column(db.Integer)           # I feel emotionally connected to this issue
    post_match8_misunderstanding = db.Column(db.Integer)     # I think opposing views on this topic are often based on misunderstanding
    post_match9_priority = db.Column(db.Integer)             # I believe addressing this issue should be a priority
    post_match10_values = db.Column(db.Integer)              # I think this topic aligns with my personal values
    post_reflection = db.Column(db.Text)                     # Additional reflections

    # ========================================
    #  DISCUSSION EVALUATION COLUMNS
    # ========================================
    disc_evaluation1 = db.Column(db.Integer)  # - confident expressing opinion
    disc_evaluation2 = db.Column(db.Integer)  # - open to listening to partner's perspective
    disc_evaluation3 = db.Column(db.Integer)  # - possible to find shared understanding
    disc_evaluation4 = db.Column(db.Integer)  # - discussion was respectful and constructive
    disc_evaluation5 = db.Column(db.Integer)  # - comfortable sharing honest thoughts
    disc_evaluation6 = db.Column(db.Integer)  # - learned something new
    disc_evaluation7 = db.Column(db.Integer)  # - felt listened to and understood
    disc_evaluation8 = db.Column(db.Integer)  # - encouraged to think more deeply
    disc_evaluation9 = db.Column(db.Integer)  # - would participate again
    disc_evaluation10 = db.Column(db.Text)     # - additional reflections (text area)
 

    # ========================================
    # EVALUATION 3: Feedback and Reflections
    # ========================================
    eval3 = db.Column(db.Integer)              # Would recommend to others
    perspective = db.Column(db.String(500))     # New perspective learned
    construct = db.Column(db.String(500))       # Changed perception of social cohesion
    feedback = db.Column(db.String(500))        # Additional feedback/suggestions


    
    # ========================================
    #  MATCHING SYSTEM
    # ========================================
    openness_score = db.Column(db.Float, nullable=True)  # NEW
    is_extremist = db.Column(db.Boolean, default=False)  # NEW
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # NEW
    
    # NEW RELATIONSHIPS - Add these at the end
    opinions = db.relationship('UserOpinion', back_populates='user', cascade='all, delete-orphan')
    matches_initiated = db.relationship('Match', foreign_keys='Match.user_a_id', back_populates='user_a', cascade='all, delete-orphan')
    matches_received = db.relationship('Match', foreign_keys='Match.user_b_id', back_populates='user_b', cascade='all, delete-orphan')

 


# ========================================
# ========================================

class OpinionDimension(db.Model):
    """
    Defines the 15 opinion dimensions:
    - 5 General Attitude questions (for screening)
    - 10 Topic-Specific questions (for matching algorithm)
    """
    __tablename__ = 'opinion_dimensions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    question_type = db.Column(db.String(50))  # 'attitude' or 'matching'
    question_number = db.Column(db.Integer)  # 1-5 for attitude, 1-10 for matching
    description = db.Column(db.Text)
    default_weight = db.Column(db.Float, default=1.0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user_opinions = db.relationship('UserOpinion', back_populates='dimension', cascade='all, delete-orphan')


class UserOpinion(db.Model):
    """
    Stores user's response to each question
    Scale: -2 to +2 (5-point scale, no conversion needed)
    """
    __tablename__ = 'user_opinions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    dimension_id = db.Column(db.Integer, db.ForeignKey('opinion_dimensions.id'), nullable=False)
    
    # Score from questionnaire: -2 to +2 scale (already normalized)
    score = db.Column(db.Float, nullable=False)
    
    # Custom weight for this user (overrides dimension default if set)
    custom_weight = db.Column(db.Float, nullable=True)
    
    # Metadata
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = db.relationship('User', back_populates='opinions')
    dimension = db.relationship('OpinionDimension', back_populates='user_opinions')
    
    # Constraints
    __table_args__ = (
        db.UniqueConstraint('user_id', 'dimension_id', name='unique_user_dimension'),
        db.CheckConstraint('score >= -2 AND score <= 2', name='check_score_range'),
    )
    
    @property
    def effective_weight(self):
        """Get the effective weight (custom or default)"""
        return self.custom_weight if self.custom_weight is not None else self.dimension.default_weight


class Match(db.Model):
    """Stores matching results between users"""
    __tablename__ = 'matches'
    
    id = db.Column(db.Integer, primary_key=True)
    user_a_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_b_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Topic they're matched on
    topic = db.Column(db.String(50), nullable=False)
    
    # Opposition score (calculated from 10 matching questions only)
    opposition_score = db.Column(db.Float, nullable=False)
    match_decision = db.Column(db.String(50), nullable=False)  # 'ideal_match', 'too_similar', 'too_extreme'
    
    scheduled_time_slot = db.Column(db.String(50), nullable=True)

    # Openness compatibility (both users are open-minded)
    both_open_minded = db.Column(db.Boolean, default=True)
    
    # Match status
    status = db.Column(db.String(50), default='pending')  # pending, accepted, rejected, expired
    
    # Interaction tracking
    conversation_started = db.Column(db.Boolean, default=False)
    last_interaction = db.Column(db.DateTime, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    user_a = db.relationship('User', foreign_keys=[user_a_id], back_populates='matches_initiated')
    user_b = db.relationship('User', foreign_keys=[user_b_id], back_populates='matches_received')
    
    # Constraints
    __table_args__ = (
        db.CheckConstraint('user_a_id != user_b_id', name='check_different_users'),
        db.CheckConstraint('opposition_score >= 0 AND opposition_score <= 4', name='check_score_range'),
    )
    
    @property
    def is_ideal_match(self):
        """Check if this is an ideal match"""
        return self.match_decision == 'ideal_match'
    
    @property
    def is_active(self):
        """Check if match is still active"""
        if self.status not in ['pending', 'accepted']:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True


class MatchHistory(db.Model):
    """Tracks historical matching data for analytics"""
    __tablename__ = 'match_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    matched_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    topic = db.Column(db.String(50), nullable=False)
    opposition_score = db.Column(db.Float, nullable=False)
    match_decision = db.Column(db.String(50), nullable=False)
    
    # Outcome tracking
    accepted = db.Column(db.Boolean, nullable=True)
    conversation_count = db.Column(db.Integer, default=0)
    total_interaction_time = db.Column(db.Integer, default=0)  # in minutes
    
    # Feedback
    user_rating = db.Column(db.Integer, nullable=True)  # 1-5 stars
    user_feedback = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


class MatchingSession(db.Model):
    """Tracks batch matching sessions for analytics"""
    __tablename__ = 'matching_sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    session_type = db.Column(db.String(50), default='automated')  # automated, manual
    topic = db.Column(db.String(50))  # Which topic was matched
    
    # Statistics
    total_users_processed = db.Column(db.Integer, default=0)
    total_matches_created = db.Column(db.Integer, default=0)
    ideal_matches_count = db.Column(db.Integer, default=0)
    extremists_excluded = db.Column(db.Integer, default=0)
    
    # Performance
    execution_time = db.Column(db.Float)  # in seconds
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Optional: store configuration
    config_json = db.Column(db.JSON, nullable=True)

class SuggestedTopic(db.Model):
    __tablename__ = 'suggested_topics'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)

    # Optional: who suggested it
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScheduledEmail(db.Model):
    __tablename__ = 'scheduled_emails'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    send_at = db.Column(db.DateTime, nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    body_html = db.Column(db.Text, nullable=False)

    sent = db.Column(db.Boolean, default=False)
