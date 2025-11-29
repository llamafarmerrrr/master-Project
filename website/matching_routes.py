"""
Flask routes for matching system
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime
from .models import db, User, UserOpinion, OpinionDimension, Match
from .matching_service import MatchingService

matching_bp = Blueprint('matching', __name__, url_prefix='/api/matching')


@matching_bp.route('/opinions', methods=['GET'])
@login_required
def get_user_opinions():
    """Get current user's opinions"""
    opinions = UserOpinion.query.filter_by(user_id=current_user.id).all()
    
    return jsonify({
        'opinions': [{
            'dimension': op.dimension.name,
            'display_name': op.dimension.display_name,
            'score': op.score,
            'weight': op.effective_weight,
            'question_type': op.dimension.question_type
        } for op in opinions]
    })


@matching_bp.route('/opinions', methods=['POST'])
@login_required
def update_opinions():
    """Update user's opinions"""
    data = request.get_json()
    
    if not data or 'opinions' not in data:
        return jsonify({'error': 'Invalid data'}), 400
    
    try:
        for opinion_data in data['opinions']:
            dimension_name = opinion_data.get('dimension')
            score = opinion_data.get('score')
            
            if score is None or not -2 <= score <= 2:
                continue
            
            dimension = OpinionDimension.query.filter_by(name=dimension_name).first()
            if not dimension:
                continue
            
            user_opinion = UserOpinion.query.filter_by(
                user_id=current_user.id,
                dimension_id=dimension.id
            ).first()
            
            if user_opinion:
                user_opinion.score = score
                user_opinion.updated_at = datetime.utcnow()
            else:
                user_opinion = UserOpinion(
                    user_id=current_user.id,
                    dimension_id=dimension.id,
                    score=score
                )
                db.session.add(user_opinion)
        
        db.session.commit()
        return jsonify({'success': True})
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@matching_bp.route('/matches', methods=['GET'])
@login_required
def get_matches():
    """Get current user's matches"""
    status = request.args.get('status', None)
    matches = MatchingService.get_user_matches(current_user.id, status)
    
    result = []
    for match in matches:
        matched_user_id = match.user_b_id if match.user_a_id == current_user.id else match.user_a_id
        matched_user = User.query.get(matched_user_id)
        
        # Skip if matched user not found
        if not matched_user:
            continue
            
        result.append({
            'id': match.id,
            'matched_user': {
                'id': matched_user.id,
                'user_name': matched_user.user_name
            },
            'opposition_score': round(match.opposition_score, 2),
            'status': match.status,
            'is_active': match.is_active
        })
    
    return jsonify({'matches': result})


@matching_bp.route('/matches/<int:match_id>/accept', methods=['POST'])
@login_required
def accept_match(match_id):
    """Accept a match"""
    success = MatchingService.accept_match(match_id, current_user.id)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Could not accept match'}), 400


@matching_bp.route('/matches/<int:match_id>/reject', methods=['POST'])
@login_required
def reject_match(match_id):
    """Reject a match"""
    success = MatchingService.reject_match(match_id, current_user.id)
    
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Could not reject match'}), 400


@matching_bp.route('/dimensions', methods=['GET'])
def get_opinion_dimensions():
    """Get all opinion dimensions"""
    dimensions = OpinionDimension.query.filter_by(is_active=True).all()
    
    return jsonify({
        'dimensions': [{
            'name': dim.name,
            'display_name': dim.display_name,
            'question_type': dim.question_type,
            'question_number': dim.question_number,
            'description': dim.description,
            'weight': dim.default_weight
        } for dim in dimensions]
    })


@matching_bp.route('/admin/run-matching', methods=['POST'])
@login_required
def run_manual_matching():
    """Manually trigger batch matching"""
    # TODO: Add admin permission check in production
    stats = MatchingService.run_batch_matching(max_matches_per_user=3)
    
    return jsonify({
        'success': True,
        'statistics': stats
    })