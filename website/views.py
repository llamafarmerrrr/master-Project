# views.py — unified and cleaned

from flask import Blueprint, render_template, request, flash, url_for, redirect, session
from flask_login import login_required, current_user
from datetime import datetime, timedelta, time, date
from threading import Thread

from flask_mail import Message

from . import db, mail
from .models import User, SuggestedTopic, ScheduledEmail
from .matching_service import MatchingService
from . import save_questionnaire_responses, get_openness_category


views = Blueprint('views', __name__)


def is_button_disabled():
    """Placeholder for time-based disabling of the start button. Currently always enabled."""
    return False


def schedule_followup_email(user):
    """Schedule a follow-up email 7 days after the discussion."""
    try:
        print(f"[FOLLOWUP] Scheduling follow-up for user {user.id} ({user.email})")

        # When you are done testing, change minutes=1 to days=7
        send_time = datetime.utcnow() + timedelta(days=7)

        body_html = render_template("Email/followup.html", user=user)

        email = ScheduledEmail(
            user_id=user.id,
            send_at=send_time,
            subject="Your Dialogue Experience – One Week Later",
            body_html=body_html,
            sent=False,  # <-- important, so scheduler knows it's not sent yet
        )

        db.session.add(email)
        db.session.commit()
        print(f"[FOLLOWUP] Created ScheduledEmail id={email.id} for {user.email} at {send_time}")
    except Exception as e:
        db.session.rollback()
        print(f"[FOLLOWUP] ERROR while scheduling follow-up for user {user.id}: {e}")

def send_due_scheduled_emails():
    """Send all scheduled emails that are due and not yet sent."""
    now = datetime.utcnow()
    try:
        due_emails = (
            ScheduledEmail.query
            .filter(ScheduledEmail.sent == False)   # noqa: E712
            .filter(ScheduledEmail.send_at <= now)
            .all()
        )

        print(f"[FOLLOWUP] Found {len(due_emails)} due scheduled email(s)")

        for email in due_emails:
            # we store only user_id in ScheduledEmail, so fetch the user
            user = User.query.get(email.user_id)
            if not user:
                print(f"[FOLLOWUP] No user found for ScheduledEmail id={email.id}, marking as sent to skip")
                email.sent = True
                continue

            try:
                msg = Message(
                    subject=email.subject,
                    sender="TogetherTolerant@gmail.com",
                    recipients=[user.email],
                )
                msg.html = email.body_html
                mail.send(msg)
                email.sent = True
                print(f"[FOLLOWUP] Sent follow-up email id={email.id} to {user.email}")
            except Exception as exc:
                # don't mark as sent so we can retry later
                print(f"[FOLLOWUP] Error sending email id={email.id} to {user.email}: {exc}")

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"[FOLLOWUP] ERROR in send_due_scheduled_emails: {exc}")
@views.route('/admin/run_scheduled_emails')
@login_required
def run_scheduled_emails():
    """Manually trigger sending of all due scheduled emails."""
    send_due_scheduled_emails()
    return "Scheduled emails processed."


@views.route('/index', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        form_type = request.form.get('form_type')

        # 1) User is suggesting a new topic
        if form_type == 'suggest_topic':
            title = (request.form.get('title') or '').strip()
            description = (request.form.get('description') or '').strip()

            if not title or not description:
                flash('Please fill in both a title and a description for your topic suggestion.', 'error')
                return redirect(url_for('views.index'))

            new_topic = SuggestedTopic(
                title=title,
                description=description,
                created_by_id=current_user.id if current_user.is_authenticated else None
            )
            db.session.add(new_topic)
            db.session.commit()

            flash('Thank you! Your topic suggestion has been saved.', 'success')
            return redirect(url_for('views.index'))

        # 2) Any other POST on index (e.g. a "Get started" button) → go to home
        return redirect(url_for('views.home'))

    # GET request → just render landing page
    return render_template('index.html', user=current_user)


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
    if getattr(current_user, 'demo', False) and getattr(current_user, 'haspartner', False):
        partner = User.query.get(current_user.partner_id)

    return render_template(
        'home.html',
        user=current_user,
        partner=partner,
        button_disabled=is_button_disabled()
    )


@views.route('/new_questionnaire/part1', methods=['GET', 'POST'])
@login_required
def new_questionnaire_part1():
    """Part 1 contains attitude1..attitude5 and stores them in session."""
    if request.method == 'POST':
        for i in range(1, 6):
            session[f'attitude{i}'] = request.form.get(f'attitude{i}')
        return redirect(url_for('views.new_questionnaire'))

    return render_template('new_questionnaire_part1.html', user=current_user)


@views.route('/new_questionnaire', methods=['GET', 'POST'])
@login_required
def new_questionnaire():
    """Part 2 of the 15-question openness questionnaire (match1..match10)."""
    if request.method == 'POST':
        try:
            # 1) collect part1 from session
            combined = {}
            for i in range(1, 6):
                key = f'attitude{i}'
                if key in session and session[key] is not None:
                    combined[key] = session[key]

            # 2) add form values (match1..match10 and any other fields)
            combined.update(request.form.to_dict())

            # 3) Save match1..match10 as integers if provided
            for i in range(1, 11):
                key = f'match{i}'
                if key in combined and combined[key] not in (None, ''):
                    try:
                        setattr(current_user, key, int(combined[key]))
                    except ValueError:
                        setattr(current_user, key, combined[key])

            db.session.commit()

            # 4) Use helper to calculate openness and check eligibility
            result = save_questionnaire_responses(user_id=current_user.id, form_data=combined)
            if not result:
                flash('An error occurred while saving your answers. Please try again.', 'error')
                return render_template('new_questionnaire_part2.html', user=current_user)

            if result.get('is_extremist'):
                flash(
                    'Thank you for completing the questionnaire. Unfortunately, you do not meet the eligibility criteria.',
                    'error'
                )
                return redirect(url_for('views.index'))

            current_user.demo = True
            db.session.commit()

            return redirect(url_for('views.demographics'))

        except Exception as exc:
            db.session.rollback()
            print(f"Error in new_questionnaire: {exc}")
            flash('There was an error processing your questionnaire. Please try again.', 'error')

    return render_template('new_questionnaire_part2.html', user=current_user)


def generate_time_slots():
    """
    Generate time slot options for the next 7 days,
    starting from the upcoming Sunday (including today if today is Sunday).
    Times: 11:00, 13:00, 15:00, 18:00
    """
    today = date.today()

    # Find upcoming Sunday (weekday: Mon=0 ... Sun=6 → Sunday=6)
    days_until_sunday = (6 - today.weekday()) % 7
    start_day = today + timedelta(days=days_until_sunday)

    times = [11, 13, 15, 18]  # Hours for the sessions
    slots = []

    for day_offset in range(7):  # Only 7 days for one full week
        this_day = start_day + timedelta(days=day_offset)

        # Example label: "Sun 01.12. 11:00"
        prefix = this_day.strftime('%a %d.%m.')

        for hour in times:
            dt = datetime.combine(this_day, time(hour, 0))
            label = f"{prefix} {dt.strftime('%H:%M')}"
            value = dt.isoformat()  # Stored in DB
            slots.append({'value': value, 'label': label})

    return slots


@views.route('/demographics', methods=['GET', 'POST'])
@login_required
def demographics():
    """Collect demographic info and availability, then trigger background matching."""
    slots = generate_time_slots()

    if request.method == 'POST':
        try:
            gender = request.form.get('gender')
            age = request.form.get('age')
            education = request.form.get('education')
            job = request.form.get('job')

            slot1 = request.form.get('availability1')
            slot2 = request.form.get('availability2') or None
            slot3 = request.form.get('availability3') or None

            if not (gender and age and education and job and slot1):
                flash('Please fill all required demographic fields (and at least one availability).', 'error')
                return render_template('Questionnaire1/demographics.html', user=current_user, slots=slots)

            current_user.gender = gender
            current_user.age = age
            current_user.education = education
            current_user.job = job
            current_user.time_slot_1 = slot1
            current_user.time_slot_2 = slot2
            current_user.time_slot_3 = slot3
            db.session.commit()

            find_matches_for_user(current_user.id)
            flash('Questionnaire and timeslots data saved. We will notify you when a match is found.', 'success')
            return redirect(url_for('views.endofq1'))

        except Exception as exc:
            db.session.rollback()
            print(f"Error saving demographics: {exc}")
            flash('There was an error saving timeslot data. Please try again.', 'error')

    return render_template('Questionnaire1/demographics.html', user=current_user, slots=slots)


def find_matches_for_user(user_id):
    """Find best match for user, create match record, and notify both via email."""
    try:
        user = User.query.get(user_id)
        if not user:
            print(f"[MATCH] User {user_id} not found")
            return

        result = MatchingService.find_best_match_for_user(user)
        if not result:
            print(f"[MATCH] No match found for user {user_id}")
            return

        matched_user, score, decision, common_slot = result
        match = MatchingService.create_match(user, matched_user, score, decision, common_slot)

        # Mark both users as matched
        user.haspartner = True
        matched_user.haspartner = True
        user.partner_id = matched_user.id
        matched_user.partner_id = user.id
        user.meeting_id = user.id
        matched_user.meeting_id = user.id

        db.session.commit()

        # ---------- Format the time slot for email ----------
        slot_label = None
        if common_slot:
            try:
                # common_slot is stored as ISO string, e.g. "2025-11-28T11:00:00"
                dt = datetime.fromisoformat(common_slot)
                # Nice human-readable format, adjust language if needed
                slot_label = dt.strftime('%A, %d %B %Y, %H:%M')
            except Exception as e:
                print(f"[MATCH] Could not parse common_slot '{common_slot}': {e}")
                slot_label = common_slot  # fallback to raw string

        # ---------- Send notification emails to both users ----------
        try:
            # Email to user A
            m1 = Message(
                'You have been matched for a dialogue session',
                sender='TogetherTolerant@gmail.com',
                recipients=[user.email]
            )
            m1.html = render_template(
                'Email/zusage.html',
                user=user,
                partner=matched_user,
                topic=user.topic,
                slot_label=slot_label
            )

            # Email to user B
            m2 = Message(
                'You have been matched for a dialogue session',
                sender='TogetherTolerant@gmail.com',
                recipients=[matched_user.email]
            )
            m2.html = render_template(
                'Email/zusage.html',
                user=matched_user,
                partner=user,
                topic=matched_user.topic,
                slot_label=slot_label
            )

            mail.send(m1)
            mail.send(m2)
            print(f"[MATCH] Match emails sent to {user.email} and {matched_user.email}")

        except Exception as mail_exc:
            print(f"[MATCH] Warning: failed to send match emails: {mail_exc}")

    except Exception as exc:
        print(f"[MATCH] Error during matching: {exc}")


@views.route('/Questionnaire1/end', methods=['GET'])
@login_required
def endofq1():
    return render_template('Questionnaire1/endofq1.html', user=current_user)


# ----------- Interaction flow -----------
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

        is_test_mode = request.args.get('test') == '4'

        if request.method == 'POST':
            if is_test_mode or (partner and getattr(partner, 'hasarrived', False)):
                return 'partner_arrived'
            return 'no_partner_arrived'

        if is_test_mode and partner:
            partner.hasarrived = True
            db.session.commit()

        return render_template('Interaction/waitPage.html', user=current_user, test_mode=is_test_mode)
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


# ---------------- post_match Questionnaire ----------------
@views.route('/Questionnaire2/post_match_questionnaire', methods=['GET', 'POST'])
@login_required
def post_match_questionnaire():
    fields = [
        'post_match1_support', 'post_match2_benefits', 'post_match3_action', 'post_match4_impact',
        'post_match5_attention', 'post_match6_trust', 'post_match7_econnected', 'post_match8_misunderstanding',
        'post_match9_priority', 'post_match10_values', 'post_reflection'
    ]

    if request.method == 'POST':
        try:
            for f in fields:
                val = request.form.get(f)
                if val in (None, ''):
                    val = None
                else:
                    if f.startswith('post_match'):
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            val = None
                setattr(current_user, f, val)
                print(f"[DEBUG] {f} = {getattr(current_user, f)}")  # Debug print

            db.session.commit()
            return redirect(url_for('views.discussion_evaluation'))

        except Exception as exc:
            db.session.rollback()
            print(f"Error saving post match questionnaire: {exc}")
            flash('There was an error saving your answers. Please try again.', 'error')

    return render_template('Questionnaire2/post_match_questionnaire.html', user=current_user)


# ---------------- discussion evaluation ----------------
@views.route('/Questionnaire2/discussion_evaluation', methods=['GET', 'POST'])
@login_required
def discussion_evaluation():
    if request.method == 'POST':
        try:
            for attr in [
                'disc_evaluation1', 'disc_evaluation2', 'disc_evaluation3', 'disc_evaluation4',
                'disc_evaluation5', 'disc_evaluation6', 'disc_evaluation7', 'disc_evaluation8',
                'disc_evaluation9', 'disc_evaluation10'
            ]:
                val = request.form.get(attr)
                setattr(current_user, attr, val if val not in (None, '') else None)
            db.session.commit()
            # go directly to opinion shift analysis
            return redirect(url_for('views.opinion_shift_analysis'))
        except Exception as exc:
            db.session.rollback()
            print(f"Error saving discussion evaluation: {exc}")
            flash('There was an error processing the data.', 'error')

    return render_template('Questionnaire2/discussion_evaluation.html', user=current_user)


# ---------------- Opinion Shift Analysis ----------------
@views.route('/opinion_shift_analysis')
@login_required
def opinion_shift_analysis():
    """Display before/after opinion shift visualization for the same 10 questions"""

    try:
        # Map the 10 identical questions (before vs after)
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

        # Collect BEFORE discussion data (match1-match10)
        before_values = []
        for i in range(1, 11):
            val = getattr(current_user, f'match{i}', None)
            try:
                before_values.append(int(val) if val not in (None, '', 'None') else None)
            except (ValueError, TypeError):
                before_values.append(None)

        # Collect AFTER discussion data (post_match1_support through post_match10_values)
        after_fields = [
            'post_match1_support', 'post_match2_benefits', 'post_match3_action',
            'post_match4_impact', 'post_match5_attention', 'post_match6_trust',
            'post_match7_econnected', 'post_match8_misunderstanding',
            'post_match9_priority', 'post_match10_values'
        ]

        after_values = []
        for field in after_fields:
            val = getattr(current_user, field, None)
            try:
                after_values.append(int(val) if val not in (None, '', 'None') else None)
            except (ValueError, TypeError):
                after_values.append(None)

        # Calculate shifts for each question
        shifts = []
        for before, after in zip(before_values, after_values):
            if before is not None and after is not None:
                shifts.append(after - before)
            else:
                shifts.append(None)

        # Calculate overall average shift
        valid_shifts = [s for s in shifts if s is not None]
        avg_shift = sum(valid_shifts) / len(valid_shifts) if valid_shifts else None

        # Calculate average before/after scores
        valid_before = [v for v in before_values if v is not None]
        valid_after = [v for v in after_values if v is not None]
        avg_before = sum(valid_before) / len(valid_before) if valid_before else None
        avg_after = sum(valid_after) / len(valid_after) if valid_after else None

        # Get openness score and category
        openness_score = getattr(current_user, 'openness_score', None)
        openness_category = get_openness_category(openness_score) if openness_score is not None else None

        return render_template(
            'opinion_shift_analysis.html',
            user=current_user,
            questions=questions,
            before_values=before_values,
            after_values=after_values,
            shifts=shifts,
            avg_shift=avg_shift,
            avg_before=avg_before,
            avg_after=avg_after,
            openness_score=openness_score,
            openness_category=openness_category
        )

    except Exception as e:
        print(f"Error in opinion_shift_analysis: {e}")
        import traceback
        traceback.print_exc()
        flash('An error occurred while loading the opinion shift analysis.', 'error')
        return redirect(url_for('views.reward'))


# ---------------- Reward ----------------
@views.route('/Reward', methods=['GET', 'POST'])
@login_required
def reward():
    partner = User.query.get(current_user.partner_id) if current_user.partner_id else None

    # 🔔 Schedule follow-up email in 7 days (only once)
    schedule_followup_email(current_user)

    try:
        if getattr(current_user, 'behaviour_score', None):
            payout = Message(
                'Payout Information',
                sender='TogetherTolerant@gmail.com',
                recipients=[current_user.email]
            )
            payout.html = render_template('Email/auszahlung.html', user=current_user)
            mail.send(payout)
    except Exception as exc:
        print(f"Error sending payout email: {exc}")
        flash('There was an error sending the payout email. Please contact the study administrator.', 'error')

    return render_template('Questionnaire2/reward.html', user=current_user, partner=partner)


# ---------------- Debug / Check User ----------------
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
    <p>Total Opinion Dimensions in DB: {dims}</p>
    <p>User's Opinion Records: {user_opinions}</p>
    <a href="/">Go Home</a>
    """
