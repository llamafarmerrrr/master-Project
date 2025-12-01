from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from flask_login import login_required, current_user
from datetime import datetime, timedelta, time, date

from . import db
from .models import User, SuggestedTopic
from .matching_service import MatchingService
from . import save_questionnaire_responses, get_openness_category

views = Blueprint('views', __name__)


def is_button_disabled():
    return False


@views.route('/index', methods=['GET', 'POST'])
def index():

    partner = None
    slot_label = None

    if current_user.is_authenticated and current_user.haspartner:
        partner = User.query.get(current_user.partner_id)

        if partner:
            my_slots = {current_user.time_slot_1, current_user.time_slot_2, current_user.time_slot_3}
            partner_slots = {partner.time_slot_1, partner.time_slot_2, partner.time_slot_3}
            common = [s for s in my_slots.intersection(partner_slots) if s]

            if common:
                try:
                    dt = datetime.fromisoformat(sorted(common)[0])
                    slot_label = dt.strftime('%A, %d %B %Y, %H:%M')
                except:
                    slot_label = sorted(common)[0]

    return render_template('index.html',
                           user=current_user,
                           partner=partner,
                           slot_label=slot_label)


@views.route('/', methods=['GET', 'POST'])
@login_required
def home():
    if request.method == 'POST':
        selected_topic = request.form.get('topic')
        if selected_topic:
            current_user.topic = selected_topic
            db.session.commit()
        return redirect(url_for('views.new_questionnaire_part1'))

    partner = None
    slot_label = None

    if current_user.demo and current_user.haspartner:
        partner = User.query.get(current_user.partner_id)

        if partner:
            my_slots = {current_user.time_slot_1, current_user.time_slot_2, current_user.time_slot_3}
            partner_slots = {partner.time_slot_1, partner.time_slot_2, partner.time_slot_3}
            common = [s for s in my_slots.intersection(partner_slots) if s]

            if common:
                try:
                    dt = datetime.fromisoformat(common[0])
                    slot_label = dt.strftime('%A, %d %B %Y, %H:%M')
                except:
                    slot_label = common[0]

    return render_template(
        'home.html',
        user=current_user,
        partner=partner,
        slot_label=slot_label,
        button_disabled=is_button_disabled()
    )


@views.route('/new_questionnaire/part1', methods=['GET', 'POST'])
@login_required
def new_questionnaire_part1():
    if request.method == 'POST':
        for i in range(1, 6):
            setattr(current_user, f'attitude{i}', request.form.get(f'attitude{i}'))

        db.session.commit()   # commit once
        return redirect(url_for('views.new_questionnaire'))

    return render_template('new_questionnaire_part1.html', user=current_user)


@views.route('/new_questionnaire', methods=['GET', 'POST'])
@login_required
def new_questionnaire():
    if request.method == 'POST':
        try:
            combined = {}

            for i in range(1, 6):
                key = f'attitude{i}'
                if key in session:
                    combined[key] = session[key]

            combined.update(request.form.to_dict())

            for i in range(1, 11):
                key = f'match{i}'
                if key in combined and combined[key] not in ('', None):
                    setattr(current_user, key, int(combined[key]))

            db.session.commit()

            result = save_questionnaire_responses(current_user.id, combined)
            if not result:
                flash("Error saving data.", "error")
                return render_template('new_questionnaire_part2.html', user=current_user)

            if result.get('is_extremist'):
                flash("You do not meet the eligibility criteria.", "error")
                return redirect(url_for('views.index'))

            current_user.demo = True
            db.session.commit()

            return redirect(url_for('views.demographics'))

        except Exception as e:
            db.session.rollback()
            flash("Error processing questionnaire.", "error")

    return render_template('new_questionnaire_part2.html', user=current_user)


from datetime import datetime, timedelta, time, date

def generate_time_slots():
    now = datetime.now()
    today = date.today()
    year = today.year

    # Fixed window: December 1–10 of this year
    start_day = date(year, 12, 1)
    end_day = date(year, 12, 10)

    # If today is after Dec 10, you can optionally early-return:
    if today > end_day:
        return []

    times = [12, 15, 17]  # 12:00, 15:00 (3pm), 17:00 (5pm)
    slots = []

    day = start_day
    while day <= end_day:
        for hour in times:
            dt = datetime.combine(day, time(hour))

            # Only keep future slots (hide past times & past days)
            if dt >= now:
                prefix = day.strftime('%a %d.%m.')
                slots.append({
                    "value": dt.isoformat(),
                    "label": f"{prefix} {dt.strftime('%H:%M')}"
                })

        day += timedelta(days=1)

    return slots


@views.route('/demographics', methods=['GET', 'POST'])
@login_required
def demographics():
    slots = generate_time_slots()

    if request.method == 'POST':
        try:
            gender = request.form.get('gender')
            age = request.form.get('age')
            education = request.form.get('education')
            job = request.form.get('job')
            slot1 = request.form.get('availability1')

            if not all([gender, age, education, job, slot1]):
                flash("Please complete all required fields.", "error")
                return render_template('Questionnaire1/demographics.html', user=current_user, slots=slots)

            current_user.gender = gender
            current_user.age = age
            current_user.education = education
            current_user.job = job
            current_user.time_slot_1 = slot1
            current_user.time_slot_2 = request.form.get('availability2') or None
            current_user.time_slot_3 = request.form.get('availability3') or None

            db.session.commit()

            find_matches_for_user(current_user.id)

            flash("Data saved. Check the platform regularly to see if you have been matched.", "success")
            return redirect(url_for('views.endofq1'))

        except Exception as e:
            db.session.rollback()
            flash("Error saving data.", "error")

    return render_template('Questionnaire1/demographics.html', user=current_user, slots=slots)


def find_matches_for_user(user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return

        result = MatchingService.find_best_match_for_user(user)
        if not result:
            return

        matched_user, score, decision, common_slot = result

        user.haspartner = True
        matched_user.haspartner = True
        user.partner_id = matched_user.id
        matched_user.partner_id = user.id

        user.meeting_id = user.id
        matched_user.meeting_id = user.id

        db.session.commit()

    except Exception as e:
        print(f"[MATCH ERR] {e}")


@views.route('/Questionnaire1/end')
@login_required
def endofq1():
    return render_template('Questionnaire1/endofq1.html', user=current_user)


# -------- Interaction Pages ----------
@views.route('/Interaction/introduction', methods=['GET', 'POST'])
@login_required
def introduction():
    if request.method == 'POST':
        return redirect(url_for('views.waitpage'))
    return render_template('Interaction/introduction.html', user=current_user)


@views.route('/Interaction/WaitingPage', methods=['GET', 'POST'])
@login_required
def waitpage():
    try:
        partner = User.query.get(current_user.partner_id) if current_user.partner_id else None
        current_user.hasarrived = True
        db.session.commit()

        if request.method == "POST":
            if partner and partner.hasarrived:
                return "partner_arrived"
            return "no_partner_arrived"

        return render_template('Interaction/waitPage.html', user=current_user)

    except Exception:
        return render_template('Interaction/waitPage.html', user=current_user)


@views.route('/Interaction/climate')
@login_required
def climate():
    return render_template('Interaction/climate.html', user=current_user)


@views.route('/Interaction/opinion')
@login_required
def opinion():
    return render_template('Interaction/opinion.html', user=current_user)


@views.route('/Interaction/future')
@login_required
def future():
    current_user.hasarrived = False
    db.session.commit()
    return render_template('Interaction/future.html', user=current_user)


# -------- Post-Match Questionnaire ----------
@views.route('/Questionnaire2/post_match_questionnaire', methods=['GET', 'POST'])
@login_required
def post_match_questionnaire():
    fields = [
        'post_match1_support', 'post_match2_benefits', 'post_match3_action', 'post_match4_impact',
        'post_match5_attention', 'post_match6_trust', 'post_match7_econnected',
        'post_match8_misunderstanding', 'post_match9_priority', 'post_match10_values',
        'post_reflection'
    ]

    if request.method == 'POST':
        try:
            for f in fields:
                val = request.form.get(f)
                setattr(current_user, f, val or None)

            db.session.commit()
            return redirect(url_for('views.discussion_evaluation'))

        except Exception as e:
            db.session.rollback()
            flash("Error saving answers.", "error")

    return render_template('Questionnaire2/post_match_questionnaire.html', user=current_user)


# -------- Discussion Evaluation ----------
@views.route('/Questionnaire2/discussion_evaluation', methods=['GET', 'POST'])
@login_required
def discussion_evaluation():
    if request.method == 'POST':
        try:
            for attr in [
                'disc_evaluation1', 'disc_evaluation2', 'disc_evaluation3',
                'disc_evaluation4', 'disc_evaluation5', 'disc_evaluation6',
                'disc_evaluation7', 'disc_evaluation8', 'disc_evaluation9',
                'disc_evaluation10'
            ]:
                setattr(current_user, attr, request.form.get(attr) or None)

            db.session.commit()
            return redirect(url_for('views.opinion_shift_analysis'))

        except Exception:
            db.session.rollback()
            flash("Error processing evaluation.", "error")

    return render_template('Questionnaire2/discussion_evaluation.html', user=current_user)


# -------- Opinion Shift ----------
@views.route('/opinion_shift_analysis')
@login_required
def opinion_shift_analysis():
    try:
        questions = [
            "Support the main idea/goal",
            "Benefits outweigh risks",
            "Would take action",
            "Positive societal impact",
            "Deserves more attention",
            "Trust experts/authorities",
            "Feel emotionally connected",
            "Opposing views = misunderstanding",
            "Should be a priority",
            "Aligns with personal values"
        ]

        before = []
        after = []

        for i in range(1, 11):
            val = getattr(current_user, f'match{i}')
            before.append(int(val) if val not in (None, '') else None)

        post_fields = [
            'post_match1_support', 'post_match2_benefits', 'post_match3_action',
            'post_match4_impact', 'post_match5_attention', 'post_match6_trust',
            'post_match7_econnected', 'post_match8_misunderstanding',
            'post_match9_priority', 'post_match10_values'
        ]

        for f in post_fields:
            val = getattr(current_user, f)
            after.append(int(val) if val not in (None, '') else None)

        shifts = [(a - b) if (a is not None and b is not None) else None for b, a in zip(before, after)]

        return render_template(
            'opinion_shift_analysis.html',
            user=current_user,
            questions=questions,
            before_values=before,
            after_values=after,
            shifts=shifts,
        )

    except Exception as e:
        return redirect(url_for('views.reward'))


# -------- Reward ----------
@views.route('/Reward')
@login_required
def reward():
    partner = User.query.get(current_user.partner_id) if current_user.partner_id else None
    return render_template('Questionnaire2/reward.html', user=current_user, partner=partner)


# -------- Debug Route ----------
@views.route('/check_user')
@login_required
def check_user():
    from .models import OpinionDimension, UserOpinion
    dims = OpinionDimension.query.count()
    user_opinions = UserOpinion.query.filter_by(user_id=current_user.id).count()

    return f"""
    <h2>User Debug Info</h2>
    <p>User ID: {current_user.id}</p>
    <p>Email: {current_user.email}</p>
    <p>Topic: {current_user.topic}</p>
    <p>Demo: {current_user.demo}</p>
    <p>Openness Score: {current_user.openness_score}</p>
    <p>Is Extremist: {current_user.is_extremist}</p>
    <hr>
    <p>Total Opinion Dimensions: {dims}</p>
    <p>User Opinions Recorded: {user_opinions}</p>
    <a href="/">Go Home</a>
    """
