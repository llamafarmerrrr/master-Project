# questionnaire_helpers.py
from datetime import datetime

def save_questionnaire_responses(user_id, form_data):
    """
    Save responses from the 15-question questionnaire
    Using -2 to +2 scale (no conversion needed)
    """
    from .models import User, UserOpinion, OpinionDimension
    from . import db  # FIXED: Changed from .static to .
    
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