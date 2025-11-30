from flask import render_template

from datetime import datetime, timedelta, time, date

from .models import UserOpinion, OpinionDimension, User, Match, db
from . import send_email_safe

def time_overlap(u1, u2):
    """
    Return a common time slot string if any overlap, else None.
    Cleans None and stray whitespace/newlines.
    """
    slots1 = {u1.time_slot_1, u1.time_slot_2, u1.time_slot_3}
    slots2 = {u2.time_slot_1, u2.time_slot_2, u2.time_slot_3}

    slots1 = {s.strip() for s in slots1 if s}
    slots2 = {s.strip() for s in slots2 if s}

    common = list(slots1 & slots2)
    return common[0] if common else None


class MatchingService:
    # ------------------------------------------------------------------
    # 1) OPTIONAL: Opposition score based on UserOpinion (kept for later)
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_opposition_score(user_a, user_b):
        """
        Calculate an opposition score (0–4) using only the 10 matching dimensions.
        This is kept for future use, but NOT used in the current openness-based matching.
        """
        # Build dict: dimension_id -> opinion
        a_ops = {
            op.dimension.id: op
            for op in user_a.opinions
            if op.dimension and op.dimension.question_type == "matching"
        }
        b_ops = {
            op.dimension.id: op
            for op in user_b.opinions
            if op.dimension and op.dimension.question_type == "matching"
        }

        common_dims = set(a_ops.keys()) & set(b_ops.keys())
        if not common_dims:
            return 0.0, "too_similar"

        total_weighted_diff = 0.0
        total_weight = 0.0

        for dim_id in common_dims:
            op_a = a_ops[dim_id]
            op_b = b_ops[dim_id]

            diff = abs(op_a.score - op_b.score)  # 0–4
            weight = min(op_a.effective_weight, op_b.effective_weight)
            total_weighted_diff += diff * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0, "too_similar"

        # Normalize to 0–4
        opposition_score = (total_weighted_diff / total_weight)

        # Interpret (same thresholds as before)
        if opposition_score < 1.0:
            decision = "too_similar"
        elif opposition_score <= 2.5:
            decision = "ideal_match"
        else:
            decision = "too_extreme"

        return opposition_score, decision

    # ------------------------------------------------------------------
    # 2) Core: openness-based matching for ONE user
    # ------------------------------------------------------------------
    @staticmethod
    def find_best_match_for_user(user):
        """
        Find the best partner for a single user based ONLY on:
          - same topic
          - demo == True (completed screening)
          - is_extremist == False
          - haspartner is False/NULL
          - both have openness_score (from attitude1–5)
          - at least one overlapping time slot

        The compatibility score is based on:
          - closeness of openness_score (smaller difference is better)
          - higher average openness is slightly preferred.
        """
        if not user.topic:
            print(f"[MATCH] User {user.id} has no topic, skipping.")
            return None

        if not user.demo:
            print(f"[MATCH] User {user.id} has not completed screening (demo=False), skipping.")
            return None

        if user.is_extremist:
            print(f"[MATCH] User {user.id} is extremist, skipping.")
            return None

        if user.haspartner:
            print(f"[MATCH] User {user.id} already has a partner, skipping.")
            return None

        if user.openness_score is None:
            print(f"[MATCH] User {user.id} has no openness_score, skipping.")
            return None

        # Base candidate filter: same topic, eligible, no partner yet
        candidates = User.query.filter(
            User.id != user.id,
            User.topic == user.topic,
            User.demo.is_(True),
            User.is_extremist.is_(False),
            (User.haspartner.is_(False) | User.haspartner.is_(None)),
            User.openness_score.isnot(None),
        ).all()

        if not candidates:
            print(f"[MATCH] No candidates for user {user.id} on topic {user.topic}")
            return None

        best_candidate = None
        best_score = None
        best_slot = None

        u_open = float(user.openness_score)

        for candidate in candidates:
            common_slot = time_overlap(user, candidate)
            if not common_slot:
                # No overlapping availability
                continue

            c_open = float(candidate.openness_score)

            # Smaller difference is better, higher avg is better
            diff = abs(u_open - c_open)
            avg = (u_open + c_open) / 2.0

            # Compatibility score: penalize big difference, reward openness
            # (values are arbitrary but consistent)
            compatibility = (4.0 - diff) + avg  # higher = better

            if (best_candidate is None) or (compatibility > best_score):
                best_candidate = candidate
                best_score = compatibility
                best_slot = common_slot

        if not best_candidate:
            print(f"[MATCH] No candidate with overlapping slot for user {user.id}")
            return None

        # We label all openness-based matches as "ideal_match"
        decision = "openness_match"
        print(
            f"[MATCH] Found openness-based match: {user.id} <-> {best_candidate.id}, "
            f"score={best_score:.2f}, slot={best_slot}"
        )
        return best_candidate, best_score, decision, best_slot

    # ------------------------------------------------------------------
    # 3) Create a Match row
    # ------------------------------------------------------------------
    @staticmethod
    def create_match(user_a, user_b, opposition_score, decision, common_slot=None):
        """
        Create and store a Match row between two users.
        For openness-based matching, `opposition_score` is just the compatibility score.
        """
        if not user_a or not user_b:
            return None

        # Avoid self-match
        if user_a.id == user_b.id:
            return None

        # Basic match object
        match = Match(
            user_a_id=user_a.id,
            user_b_id=user_b.id,
            topic=user_a.topic or user_b.topic,
            opposition_score=opposition_score,
            match_decision=decision,
            scheduled_time_slot=common_slot,
            both_open_minded=(not user_a.is_extremist and not user_b.is_extremist),
            status="accepted",  # directly accepted in this design
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=14),
        )

        db.session.add(match)
        db.session.commit()
        print(
            f"[MATCH] Match row created: {match.id} "
            f"({user_a.id} <-> {user_b.id}) topic={match.topic}"
        )
        return match

    # ------------------------------------------------------------------
    # 4) Batch matching for scheduler (simple wrapper around per-user)
    # ------------------------------------------------------------------
    @staticmethod
    def run_batch_matching(**kwargs):
        """
        Run a batch matching pass over all eligible users.
        Uses the same openness-based logic as find_best_match_for_user.
        Returns a small stats dict.
        """
        stats = {
            "users_processed": 0,
            "matches_created": 0,
            "topics_processed": 0,
        }

        # All eligible users without partner
        eligible_users = User.query.filter(
            User.demo.is_(True),
            User.is_extremist.is_(False),
            (User.haspartner.is_(False) | User.haspartner.is_(None)),
            User.openness_score.isnot(None),
            User.topic.isnot(None),
        ).all()

        stats["users_processed"] = len(eligible_users)

        topics = set()
        for user in eligible_users:
            topics.add(user.topic)

            # Skip if they were matched earlier in this batch
            if user.haspartner:
                continue

            result = MatchingService.find_best_match_for_user(user)
            if not result:
                continue

            partner, score, decision, slot = result

            # Partner might have been matched in a previous iteration
            if partner.haspartner:
                continue

            # Create the match row
            match = MatchingService.create_match(user, partner, score, decision, slot)

            # Update convenience flags on User
            user.haspartner = True
            partner.haspartner = True
            user.partner_id = partner.id
            partner.partner_id = user.id
            user.meeting_id = user.id
            partner.meeting_id = user.id

            # ---------- Format the time slot for email ----------
            slot_label = None
            if slot:
                try:
                    dt = datetime.fromisoformat(slot)
                    slot_label = dt.strftime('%A, %d %B %Y, %H:%M')
                except Exception as e:
                    print(f"[BATCH MATCH] Could not parse slot '{slot}': {e}")
                    slot_label = slot  # fallback

            # ---------- Send zusage email to both users ----------
                        # ---------- Send zusage email to both users ----------
            try:
                html_a = render_template(
                    'Email/zusage.html',
                    user=user,
                    partner=partner,
                    topic=user.topic,
                    slot_label=slot_label
                )
                html_b = render_template(
                    'Email/zusage.html',
                    user=partner,
                    partner=user,
                    topic=partner.topic,
                    slot_label=slot_label
                )

                ok_a = send_email_safe(
                    subject='You have been matched for a dialogue session',
                    recipients=[user.email],
                    html=html_a
                )
                ok_b = send_email_safe(
                    subject='You have been matched for a dialogue session',
                    recipients=[partner.email],
                    html=html_b
                )

                print(f"[BATCH MATCH] Email status A={ok_a}, B={ok_b} for {user.email} & {partner.email}")

            except Exception as mail_exc:
                # This should almost never trigger now, but keep it as extra safety
                print(f"[BATCH MATCH] Unexpected error while preparing match emails: {mail_exc}")

            db.session.commit()
            stats["matches_created"] += 1

        stats["topics_processed"] = len(topics)
        print(
            f"[BATCH MATCH] users={stats['users_processed']}, "
            f"topics={stats['topics_processed']}, "
            f"matches_created={stats['matches_created']}"
        )
        return stats

    # ------------------------------------------------------------------
    # 5) Read matches for a user
    # ------------------------------------------------------------------
    @staticmethod
    def get_user_matches(user_id, status=None):
        """
        Get matches where the given user participates.
        Optionally filter by status ('pending', 'accepted', 'rejected', 'expired').
        """
        query = Match.query.filter(
            (Match.user_a_id == user_id) | (Match.user_b_id == user_id)
        )
        if status:
            query = query.filter(Match.status == status)
        return query.order_by(Match.created_at.desc()).all()

    # ------------------------------------------------------------------
    # 6) Accept / reject (kept for completeness)
    # ------------------------------------------------------------------
    @staticmethod
    def accept_match(match_id, user_id):
        """
        Mark a match as accepted. In this design, we create matches as 'accepted'
        already, so this is mostly for completeness.
        """
        match = Match.query.get(match_id)
        if not match or user_id not in [match.user_a_id, match.user_b_id]:
            return False

        match.status = "accepted"

        # Ensure user flags are set
        user_a = User.query.get(match.user_a_id)
        user_b = User.query.get(match.user_b_id)

        if user_a and user_b:
            user_a.haspartner = True
            user_b.haspartner = True
            user_a.partner_id = user_b.id
            user_b.partner_id = user_a.id
            user_a.meeting_id = user_a.id
            user_b.meeting_id = user_a.id

        db.session.commit()
        return True

    @staticmethod
    def reject_match(match_id, user_id):
        """
        Reject a match. Does NOT automatically free haspartner flags here,
        but you can extend it if needed.
        """
        match = Match.query.get(match_id)
        if not match or user_id not in [match.user_a_id, match.user_b_id]:
            return False

        match.status = "rejected"
        db.session.commit()
        return True

    # ------------------------------------------------------------------
    # 7) Expire old matches (called by scheduler)
    # ------------------------------------------------------------------
    @staticmethod
    def expire_old_matches():
        """
        Expire matches whose expires_at is in the past and status is still pending.
        Returns the number of expired matches.
        """
        now = datetime.utcnow()
        old_matches = Match.query.filter(
            Match.status == "pending",
            Match.expires_at.isnot(None),
            Match.expires_at < now,
        ).all()

        count = 0
        for match in old_matches:
            match.status = "expired"
            count += 1

        if count > 0:
            db.session.commit()

        return count
