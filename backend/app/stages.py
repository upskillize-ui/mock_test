"""InterviewIQ session-stage machine, readiness bands, and calibration math.

Pure logic only (no DB, no I/O) so it is trivially testable. Consumed by main.py.

Stages (INT-04):
  SETUP -> WARMUP -> DOMAIN -> BEHAVIOURAL -> CASE -> REVERSE -> FEEDBACK -> READOUT -> DONE

The learner answers questions in WARMUP/DOMAIN/BEHAVIOURAL/CASE (these are the
"scored" stages). Confidence ratings (INT-01) are collected from DOMAIN onward;
WARMUP is intentionally exempt — warm-up answers advance straight to the next
question. REVERSE flips the flow: the learner asks the interviewer questions
(not rated). FEEDBACK is the closing ritual's last beat — we ask THEM how the session
was, and the answer is stored for product review, never scored and never shown to the
model that writes the readout. READOUT is terminal input-wise; the debrief is at
/session/end.
"""

import re

from .config import settings

# Ordered, answerable stages (excludes SETUP/READOUT/DONE which take no /turn answer).
STAGE_ORDER = ["WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE", "REVERSE", "FEEDBACK"]
SCORED_STAGES = {"WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE"}
# Stages whose answers are followed by a confidence rating. WARMUP is excluded
# by product decision — warm-up is a rapport ice-breaker, not rating-gated.
RATING_STAGES = {"DOMAIN", "BEHAVIOURAL", "CASE"}
TERMINAL_STAGES = {"READOUT", "DONE"}
# FEEDBACK is answerable but NOT scored and NOT rated — it is the one turn in the session
# where the candidate is not being assessed at all. Deliberately absent from SCORED_STAGES
# and RATING_STAGES above: what they think of US must never touch what we think of THEM,
# in either direction. A student who says the session was too hard has not scored badly,
# and a student who flatters us has not scored well.

STAGE_LABELS = {
    "WARMUP": "Warm-up",
    "DOMAIN": "Domain",
    "BEHAVIOURAL": "Behavioural",
    "CASE": "Case",
    "REVERSE": "Your Questions",
    "FEEDBACK": "Your Feedback",
    "READOUT": "Readout",
    "DONE": "Complete",
}


def _seniority_bucket(level: str) -> str:
    """Map the frontend's experience-level strings to a question-count bucket.

    Buckets: 'fresher' | 'junior' (0-2) | 'mid' (2-5) | 'senior' (5+).
    """
    lv = (level or "").strip().lower()
    if lv in ("fresher", "0-2", "student", "intern"):
        return "fresher"
    if lv in ("career switcher", "1-3 years", "0-1 year", "< 1 year"):
        return "junior"
    if lv in ("3-10 years", "2-5", "mid"):
        return "mid"
    if lv in ("10-20 years", "20+ years", "5+", "senior"):
        return "senior"
    # Unknown -> treat as mid (safe middle ground).
    return "mid"


def stage_plan(level: str) -> dict:
    """Return the per-stage question targets + flags for this experience level."""
    bucket = _seniority_bucket(level)
    if bucket == "fresher":
        domain, behavioural, case_variant, notice = 4, 3, "short", False
    elif bucket == "junior":
        domain, behavioural, case_variant, notice = 4, 3, "short", False
    elif bucket == "senior":
        domain, behavioural, case_variant, notice = 6, 4, "long", True
    else:  # mid
        domain, behavioural, case_variant, notice = 5, 3, "long", False
    return {
        "bucket": bucket,
        "totals": {
            "WARMUP": 2,
            "DOMAIN": domain,
            "BEHAVIOURAL": behavioural,
            "CASE": 1,
            "REVERSE": 2,
            # One question, every session, every level. "How was that for you?" asked once
            # is a question; asked twice it is a survey, and a survey at the end of an
            # interview is the moment the room stops being a room.
            "FEEDBACK": 1,
        },
        "case_variant": case_variant,
        "notice_period": notice,
    }


def stage_total(level: str, stage: str) -> int:
    return stage_plan(level)["totals"].get(stage, 0)


def next_stage(stage: str) -> str:
    """The stage that follows `stage`. After REVERSE comes FEEDBACK, then READOUT, then DONE."""
    if stage in TERMINAL_STAGES:
        return "DONE" if stage == "READOUT" else "DONE"
    try:
        idx = STAGE_ORDER.index(stage)
    except ValueError:
        return "READOUT"
    return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else "READOUT"


def is_scored(stage: str) -> bool:
    return stage in SCORED_STAGES


def is_rating_gated(stage: str) -> bool:
    """True if a learner answer in this stage must be followed by a confidence
    rating before the interview can proceed. WARMUP is not gated (INT-01 exemption)."""
    return stage in RATING_STAGES


# ── Substantive-answer gate (generalises the WARMUP rating exemption) ─────────
# We only ask a learner to rate their confidence, and only "spend" a question
# slot, on a *substantive* answer. A non-answer ("I don't know" / "skip" / a bare
# clarification request / a couple of characters) is not something worth rating,
# and it must not consume one of the round's planned questions.

MIN_SUBSTANTIVE_CHARS = 15

# E7.7 — the per-question clock. When it expires with NOTHING captured (no partial
# transcript, no typed draft), the turn is recorded as a SKIP: this exact text is stored
# as the answer so the transcript stays honest about what happened, and every downstream
# reader (the substantive gate, the debrief) recognises it. The learner never types it
# and the client never sends it — the SERVER writes it, so it cannot be forged or varied.
TIMEOUT_SKIP_TEXT = "(No answer — the time on this question ran out.)"
# The two ways a question can hit its deadline.
#   "partial" — something WAS captured (a partial transcript or a typed draft): it is
#               submitted as the answer and scored like any other short answer.
#   "skip"    — nothing was captured: no slot spent, no rating, the interviewer
#               acknowledges it neutrally and moves on.
TIMEOUT_KINDS = ("partial", "skip")

# Obvious non-answers. Anchored so we only fire on a message that is *entirely* a
# non-answer, not one that merely contains the phrase ("I don't know why, but the
# reason we chose Kafka was ..." is a real answer and must still be rated).
_NONANSWER_RX = re.compile(
    r"^\s*(i\s*(really\s*|honestly\s*)?(don'?t|do\s*not|dont)\s*know"
    r"|no\s*idea|not\s*sure|no\s*clue|dunno|idk"
    r"|skip(\s*this)?|pass|next(\s*question)?|move\s*on"
    r"|can'?t\s*answer|cannot\s*answer|i\s*give\s*up|no\s*comment)"
    r"[\s.!?]*$",
    re.IGNORECASE,
)
# Pure clarification requests — the learner asked us something instead of answering.
_CLARIFY_RX = re.compile(
    r"^\s*(what\s*do\s*you\s*mean"
    r"|(can|could)\s*you\s*(please\s*)?(repeat|rephrase|clarify|explain)"
    r"|come\s*again|sorry\s*,?\s*what|pardon|i\s*didn'?t\s*(get|understand))"
    # allow a short trailing tail ("...repeat that?", "...clarify the question please")
    # but not a whole sentence, so a genuine answer that clarifies-then-answers still rates.
    r"(\s+\w+){0,3}[\s.?!]*$",
    re.IGNORECASE,
)
# Meaningful characters = letters/digits (Latin + Devanagari for Hinglish typed in
# Hindi script); punctuation and whitespace don't count toward "did they say anything".
_NONMEANINGFUL_RX = re.compile(r"[^0-9a-zऀ-ॿ]")


def is_non_substantive(text: str) -> bool:
    """Cheap, deterministic guard — True when an answer is an obvious non-answer.

    Runs BEFORE any LLM judgement so we never burn a confidence-rating prompt on a
    "don't know" / "skip" / bare clarification, even if the scoring model would
    later misjudge it as substantive. Deliberately conservative: it only fires on
    clear non-answers, so genuine (even terse) answers still get rated, and the
    debrief scoring call's `substantive` flag catches the subtler cases.
    """
    if not text:
        return True
    stripped = text.strip()
    # A timed-out question is a non-answer by construction — it reads like a sentence, so
    # the length/phrase heuristics below would otherwise wave it through as real content.
    if stripped == TIMEOUT_SKIP_TEXT:
        return True
    if _NONMEANINGFUL_RX.sub("", stripped.lower()).__len__() < MIN_SUBSTANTIVE_CHARS:
        return True
    return bool(_NONANSWER_RX.match(stripped) or _CLARIFY_RX.match(stripped))


# ── The abuse floor (Persona/Warmth item 2) ─────────────────────────────────
# Sibling of the engagement floor below: same shape (derived from the transcript, no
# column to keep in sync, resets on any clean answer), same two-strike escalation, same
# courteous wrap. It answers one question only: has this candidate ABUSED THE INTERVIEWER,
# repeatedly, such that the session should be closed courteously?
#
# THE LINE THIS DRAWS, AND WHY IT IS DRAWN THERE:
#   "This is fucking hard."   -> FRUSTRATION. Not abuse. Never wraps. Never counts.
#   "You're a fucking idiot." -> ABUSE. Counts.
#   The discriminator is whether the profanity is aimed AT A PERSON. That is deliberate
#   symmetry with the rule that binds the interviewer in Critical mode: pressure lands on
#   the answer, never on the person. We hold ourselves to it, so we measure them by it.
#
#   It matters enormously that we get this asymmetry right. A candidate swearing at the
#   DIFFICULTY is a candidate having a hard time, and the correct response is the
#   de-escalation + confidence rebuild in the persona — warmth, not a wrap. Wrapping them
#   would punish someone for finding an interview stressful, which is the single worst
#   thing this product could do. So frustration NEVER reaches this function's threshold;
#   only sustained, person-directed abuse does.
#
# WHY IT IS DELIBERATELY UNDER-SENSITIVE:
#   A false positive here ENDS A STUDENT'S INTERVIEW. A false negative means an abusive
#   candidate gets de-escalated at instead of wrapped — which is, at worst, us being too
#   patient with someone. Those costs are nowhere near symmetric, so every judgement call
#   below is resolved toward "do nothing". The lexicon is short and unambiguous rather
#   than comprehensive; the targeting requirement is strict; the threshold requires the
#   behaviour to REPEAT after we have already tried to de-escalate.
#
# SCRIPT COVERAGE — A KNOWN GAP, ACCEPTED FOR GO-LIVE:
#   The lexicon is English + Hinglish IN LATIN SCRIPT ONLY. Abuse typed in Devanagari or
#   another Indic script does not trip it. That is a false NEGATIVE — the safe direction —
#   so the failure mode is that we are too patient with someone, never that we end an
#   interview we should not have. Extending to Indic scripts is a future addition; until
#   then, the prompt-level de-escalation still handles those turns in full, because it is
#   the MODEL reading the message and it is not limited to any script. The only thing this
#   gap costs is the wrap, i.e. the rung nobody is in a hurry to reach.
#
# STATUS: the lexicon and threshold below are APPROVED as tuned (owner sign-off, go-live).
# Reviewed against real answer shapes; see tests/test_persona_warmth.py, which pins both
# directions. Retune deliberately, not casually — and if you widen the lexicon, re-read the
# asymmetry above first.
_PROFANITY_RX = re.compile(
    r"\b(fuck(er|ing|ed)?|f\*+k|shit|bastard|bitch|asshole|arsehole|dick|prick|cunt|"
    r"idiot|stupid|moron|dumbass|retard(ed)?|scum|"
    r"chutiya|chutiye|bhosdi(ke|wala)?|madarchod|behenchod|bkl|mc|bc|gandu|harami|kutta|kamina)\b",
    re.IGNORECASE,
)
# Is a person being addressed? Second-person pronouns (English + Hinglish-Latin), or a
# vocative "you <profanity>" construction. Without one of these, profanity is read as
# frustration at the task and is left entirely alone.
_SECOND_PERSON_RX = re.compile(
    r"\b(you|your|you'?re|u|ur|urself|yourself|tu|tum|tera|teri|tere|tumhara|tumhari|aap|apka)\b",
    re.IGNORECASE,
)
# A bare slur with no sentence around it ("chutiya.", "asshole!") is abuse even though it
# names no one: in a two-person conversation there is only one person it can be aimed at.
_BARE_SLUR_MAX_WORDS = 3

# Abuse aimed at the interviewer is SHORT AND HOT. Nobody composes a 60-word paragraph to
# tell you to get lost. An answer this long that contains person-directed profanity is
# almost always the BEHAVIOURAL round working exactly as intended — a candidate recounting
# a real workplace conflict and quoting what someone said to them:
#
#   "The tech lead lost his temper and told me you are an idiot for shipping on a Friday.
#    I waited until after the call, asked what specifically broke, and we agreed a rollback."
#
# That is a good answer to a STAR question. Without this ceiling the second-person test
# reads the QUOTED insult as an insult to us and de-escalates at a candidate who is calmly
# describing how they handled being insulted — which would be both absurd and insulting.
# Measured against real answer shapes; a long abusive rant slips through instead, and that
# is the direction this whole module is built to fail in.
_ABUSE_MAX_WORDS = 25

# Two strikes, mirroring checkin -> wrap. One person-directed hit gets a de-escalation and
# a way back in; a SECOND consecutive one, after we have already offered that, wraps.
#
# ENDING THE SESSION IS THE LAST RUNG OF THE LADDER, AND IT IS REACHABLE ONLY THROUGH THE
# EARLIER ONES. Because this is 2 and not 1, abuse_action() must return "deescalate" before
# it can ever return "wrap": there is no input where a candidate's first swing ends their
# interview. Setting this to 1 would not "tighten" the floor — it would delete the
# de-escalation and the confidence rebuild entirely, which are the whole point, and leave a
# product that hangs up on people. If you change this number, change it upward.
# (The wrap REASON sentinel lives next to WRAP_DISENGAGED in prompts.py, with the rest of
# the wrap family.)
ABUSE_TURNS_BEFORE_WRAP = 2


def is_abuse_at_person(text: str) -> bool:
    """True only for profanity aimed AT SOMEONE. Frustration at the task returns False.

    Pure and deterministic — no model call, no network, and cheap enough to run on every
    turn. See the block comment above for why this is tuned to under-fire.
    """
    if not text:
        return False
    stripped = (text or "").strip()
    if not _PROFANITY_RX.search(stripped):
        return False
    words = len(stripped.split())
    # A bare slur, alone: nothing else in the message to be angry at.
    if words <= _BARE_SLUR_MAX_WORDS:
        return True
    # Long enough to be an actual answer -> it is one. See _ABUSE_MAX_WORDS.
    if words > _ABUSE_MAX_WORDS:
        return False
    return bool(_SECOND_PERSON_RX.search(stripped))


def trailing_abuse(user_answers: list[str]) -> int:
    """How many of the LAST answers in a row were person-directed abuse.

    The run breaks on ANY answer that is not — including a terse or unhelpful one. Coming
    back to the actual question, in any form, is exactly what we want to reward, so it
    resets the count to zero and costs nothing.
    """
    n = 0
    for content in reversed(list(user_answers or [])):
        if not is_abuse_at_person(content or ""):
            break
        n += 1
    return n


def abuse_action(abusive_turns: int) -> str:
    """What the interview must do about abuse: "" | "deescalate" | "wrap".

    `abusive_turns` is the trailing run INCLUDING the message just submitted.
      below the threshold -> DE-ESCALATE. Name it calmly, hand them a way back in. This is
                             the response we want to give, and we give it every time.
      at/past it          -> WRAP. We already de-escalated and it continued. Close
                             courteously and neutrally, score what actually happened.
    """
    n = max(0, int(abusive_turns or 0))
    if n >= ABUSE_TURNS_BEFORE_WRAP:
        return "wrap"
    if n > 0:
        return "deescalate"
    return ""


def should_await_rating(stage: str, is_substantive: bool) -> bool:
    """True iff a just-submitted answer in `stage` must be rated before proceeding.

    Generalises the WARMUP exemption: rating-gated stages only (DOMAIN/BEHAVIOURAL/
    CASE), and only for substantive answers (FIX 1 — rate only substantive answers).
    """
    return is_rating_gated(stage) and is_substantive


# ── Sparse confidence calibration ────────────────────────────────────────────
# Asking "how confident are you, 1-5?" after EVERY scored answer breaks the speaking
# rhythm and teaches gaming — by the third ask students answer "3" and move on, which
# destroys the very calibration signal the ask exists to collect. So the rating is
# SAMPLED: the first DOMAIN answer is always asked (an anchor every session shares),
# and each later gated answer is asked with probability ~RATING_SAMPLE_P, decided by a
# hash of (session, stage, slot) — deterministic, so a refresh or a replayed turn can
# never flip the decision mid-question. Expected asks per full session: ~3.
# calibration_pairs/calibration_profile already tolerate sparse ratings (they join by
# answer_id and degrade to insufficient_data), so nothing downstream changes.
RATING_SAMPLE_P = 0.25


def sample_rating(session_id: str, stage: str, round_index: int) -> bool:
    """Should THIS answer get the confidence-rating ask? Deterministic, sparse."""
    import hashlib
    if stage == "DOMAIN" and round_index == 0:
        return True   # the shared anchor: every session rates its first domain answer
    h = hashlib.sha1(f"{session_id}|{stage}|{round_index}".encode("utf-8")).digest()
    return h[0] < int(RATING_SAMPLE_P * 256)


def consumes_question_slot(stage: str, is_substantive: bool, timed_out_skip: bool = False) -> bool:
    """FIX 2 — a non-substantive answer in a scored, rating-gated stage does NOT
    consume a planned question slot: the interviewer steps down / re-asks on the
    same topic instead, so 'a round of 4' still means 4 substantive questions.
    Every other turn (WARMUP, REVERSE, and all substantive answers) advances normally.

    E7.7 — a question whose clock ran out with nothing captured spends no slot EITHER,
    in any scored stage (WARMUP included: running out of time is not an answer, and a
    round of 2 warm-ups still means 2 real warm-ups).

    REVERSE and FEEDBACK are the exceptions: there is no question of OURS to re-ask — the
    slot is the candidate's own question, or their view of us. If they let the clock run
    out we let the round advance, otherwise a silent candidate could never reach the close.
    For FEEDBACK specifically, not advancing here would trap them: the stage would re-ask
    "so how was that session for you?" every time the clock expired, forever, and the one
    turn where nothing is being asked OF them would become the only one they cannot leave.
    """
    if timed_out_skip:
        return stage in ("REVERSE", "FEEDBACK")
    if is_rating_gated(stage) and not is_substantive:
        return False
    return True


# ── The engagement floor ─────────────────────────────────────────────────────
# A real panel does not ask six questions into silence. It stops and checks whether the
# person is still there. Ours did not — the founder's UAT session watched the interviewer
# march through the whole round list talking to nobody, burning an LLM call and a TTS bill
# on every question. This is the rule that ends that.
#
# The counter is DERIVED, not stored: consecutive skips are the trailing run of
# TIMEOUT_SKIP_TEXT answers in the transcript. That is why "any response resets the
# counter" needs no code — a real answer (even "yes") breaks the run by existing. No new
# column, no migration, nothing to keep in sync, and nothing a refresh can desynchronise.

# The check-in gets its own short clock — it is a direct question, and a question the
# candidate cannot see a clock on is a trap. The client owns the wall clock (see
# roomPolicy.CHECKIN_SECONDS); this is the same number, on the side that decides.
CHECKIN_SECONDS = 45

# How many consecutive silences we allow before breaking the question march.
#   COLD — nothing substantive has been said all session. Two is already generous: it is
#          the difference between a candidate who is thinking and a candidate who is gone.
#   WARM — they HAVE answered properly earlier. A good candidate freezing on a hard
#          question deserves more rope than a blank session, so they get a third.
SKIPS_BEFORE_CHECKIN_COLD = 2
SKIPS_BEFORE_CHECKIN_WARM = 3


def trailing_skips(user_answers: list[str]) -> int:
    """How many of the LAST answers in a row were timed-out silences.

    The run breaks on any real answer, which is exactly the "counter resets on any
    response" rule — including a bare "yes" to the check-in, which is a response even
    though it is not a substantive answer.
    """
    n = 0
    for content in reversed(list(user_answers or [])):
        if (content or "").strip() != TIMEOUT_SKIP_TEXT:
            break
        n += 1
    return n


def substantive_count(user_answers: list[str]) -> int:
    """How many real answers this candidate has given so far, all session."""
    return sum(1 for c in (user_answers or []) if not is_non_substantive(c or ""))


def checkin_threshold(substantive_so_far: int) -> int:
    """Consecutive silences we tolerate before checking in. Someone who has been
    answering properly gets more rope than someone who has said nothing at all."""
    return (
        SKIPS_BEFORE_CHECKIN_WARM if int(substantive_so_far or 0) > 0
        else SKIPS_BEFORE_CHECKIN_COLD
    )


def engagement_action(stage: str, skips: int, substantive_so_far: int) -> str:
    """What the interview must do about the silence: "" | "checkin" | "wrap".

    `skips` is the trailing run of silences INCLUDING the one just submitted.

      at the threshold  -> CHECK IN. Break off the question march and ask, in persona,
                           whether they are still there. A direct question, with a clock.
      past it           -> WRAP. They did not answer the check-in either. Close courteously
                           and score honestly what actually happened. Nothing is zeroed as
                           a punishment; there simply is not much to score.

    REVERSE and FEEDBACK are exempt: the "question" in REVERSE is the candidate's own and
    the one in FEEDBACK is about US, so there is nothing of ours to check in about — and a
    silent candidate must still be able to reach the close. Someone who does not want to
    tell us how the session went has answered the question by not answering it, and
    chasing them for it would be the single most self-regarding thing this product does.
    """
    if (stage or "").upper() in ("REVERSE", "FEEDBACK"):
        return ""
    n = max(0, int(skips or 0))
    threshold = checkin_threshold(substantive_so_far)
    if n > threshold:
        return "wrap"
    if n == threshold:
        return "checkin"
    return ""


def stage_label(stage: str, round_index: int, level: str, awaiting_rating: bool = False) -> str:
    """Human progress label, e.g. 'Behavioural · Question 2 of 4'."""
    name = STAGE_LABELS.get(stage, stage.title())
    if stage in TERMINAL_STAGES:
        return name
    # FEEDBACK is one beat and it is not a question of ours. "Your Feedback · Question 1
    # of 1" would count it like an interview question they are being marked on — which is
    # the one thing this turn is not.
    if stage == "FEEDBACK":
        return name
    total = stage_total(level, stage)
    # While rating, we reference the answer just given (round_index already
    # incremented). While answering, we reference the upcoming question.
    qnum = round_index if awaiting_rating else round_index + 1
    qnum = max(1, min(qnum, total))
    return f"{name} · Question {qnum} of {total}"


def next_action(current_stage: str, awaiting_rating: bool) -> str:
    """What the client should do next: answer | rating | reverse_question | readout | done."""
    if current_stage == "DONE":
        return "done"
    if current_stage == "READOUT":
        return "readout"
    if awaiting_rating:
        return "rating"
    if current_stage == "REVERSE":
        return "reverse_question"
    return "answer"


def advance_after_rating(current_stage: str, round_index: int, level: str) -> tuple[str, int]:
    """Called once a rating is recorded. If the current scored stage is complete,
    move to the next stage and reset the per-stage counter."""
    if round_index >= stage_total(level, current_stage):
        return next_stage(current_stage), 0
    return current_stage, round_index


def early_wrap_transition(current_stage: str) -> tuple[str, str]:
    """Interview Room (Phase E): end the interview early and go straight to the readout.

    Returns (new_stage, stage_it_was_wrapped_at). The decision is made and PERSISTED
    server-side, so refreshing cannot dodge it. Scoring is unaffected: the debrief runs
    over the rounds actually completed — we score what happened and mark what didn't.
    Nothing is zeroed as a punishment.
    """
    return "READOUT", (current_stage or "")


def advance_after_reverse(round_index: int, level: str) -> tuple[str, int]:
    """REVERSE is not rating-gated; advance to the FEEDBACK beat when complete.

    (Was: straight to READOUT. The closing ritual now puts one question between the two —
    we ask them how it went before we tell them how they went.)
    """
    if round_index >= stage_total(level, "REVERSE"):
        return "FEEDBACK", 0
    return "REVERSE", round_index


def advance_after_feedback(round_index: int, level: str) -> tuple[str, int]:
    """FEEDBACK is one turn, not scored, not rated. Then the readout."""
    if round_index >= stage_total(level, "FEEDBACK"):
        return "READOUT", 0
    return "FEEDBACK", round_index


# ── INT-03: readiness bands ────────────────────────────────────────────────

def band_for(pct) -> str:
    """Map a 0-100 score to a canonical InterviewIQ readiness band."""
    if pct is None:
        return "Not Ready"
    try:
        p = float(pct)
    except (TypeError, ValueError):
        return "Not Ready"
    if p >= settings.BAND_OFFER_READY_MIN:
        return "Offer-Ready"
    if p >= settings.BAND_INTERVIEW_READY_MIN:
        return "Interview-Ready"
    if p >= settings.BAND_BUILDING_MIN:
        return "Building"
    return "Not Ready"


def round_bands_from_scores(round_scores: dict) -> dict:
    """round_scores: {'domain': 0-100, ...} -> {'domain': 'Building', ...}."""
    out = {}
    if not isinstance(round_scores, dict):
        return out
    for key, val in round_scores.items():
        if val is None:
            continue
        out[key] = band_for(val)
    return out


# ── INT-02: calibration ────────────────────────────────────────────────────

def _categorize(rating: int, score_1_5: float) -> str:
    """Classify one rated answer. Score is already normalised to 1-5."""
    delta = rating - score_1_5
    if abs(delta) <= 1:
        return "well_calibrated"
    if rating >= 4 and score_1_5 <= 2:
        return "over_confident"
    if rating <= 2 and score_1_5 >= 4:
        return "under_confident"
    # Outside the tight band but not an extreme mismatch: lean by direction.
    if delta > 0:
        return "over_confident"
    if delta < 0:
        return "under_confident"
    return "well_calibrated"


def _coerce_int(v):
    """Best-effort int (the model may echo an id as a string or a float)."""
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _scores_by_answer_id(per_answer_scores: list, valid_answer_ids=None) -> dict:
    """INT-11: index the model's per-answer scores by the answer_id they echo.

    Only entries whose echoed answerId is a real answer (present in
    valid_answer_ids, when provided) are kept, so a hallucinated / duplicated id
    can't inject a bogus pair. Later entries win on a duplicate id.
    """
    out = {}
    for e in per_answer_scores or []:
        if not isinstance(e, dict):
            continue
        aid = _coerce_int(e.get("answerId"))
        if aid is None:
            continue
        if valid_answer_ids is not None and aid not in valid_answer_ids:
            continue
        out[aid] = e
    return out


def calibration_pairs(ratings: list, per_answer_scores: list, valid_answer_ids=None) -> list:
    """INT-11: join learner confidence ratings to model quality scores BY answer_id.

    ratings: ordered list of (answer_id, rating) — rating may be None ("prefer not
    to say"). per_answer_scores: the model's perAnswerScores, each echoing answerId.

    Returns ordered (rating, score) pairs for the answers that have BOTH a rating and
    a substantive score entry. Because the pairing is by id (not position), a
    non-substantive answer dropped from the middle of the list — or an extra/missing
    entry from the model — can never shift the remaining pairs onto the wrong answer.
    """
    by_id = _scores_by_answer_id(per_answer_scores, valid_answer_ids)
    pairs = []
    for answer_id, rating in ratings:
        e = by_id.get(_coerce_int(answer_id))
        if e is None:
            continue
        if e.get("substantive", True) is False:
            continue
        pairs.append((rating, e.get("score")))
    return pairs


def substantive_stages(per_answer_scores: list, valid_answer_ids=None) -> set:
    """INT-11: the set of stage names (e.g. {"DOMAIN", "CASE"}) that have at least
    one substantive answer, determined by the answer_id join. Used to gate round
    bands so a round in which every answer was a non-answer can't show a positive band.
    """
    by_id = _scores_by_answer_id(per_answer_scores, valid_answer_ids)
    out = set()
    for e in by_id.values():
        if e.get("substantive", True) is False:
            continue
        stage = str(e.get("stage", "")).strip().upper()
        if stage:
            out.add(stage)
    return out


def gate_round_scores(round_scores: dict, sub_stages: set) -> dict:
    """INT-11: zero any *scored* round (warmup/domain/behavioural/case) that the join
    says has no substantive answers, so band math never rewards a round of pure
    non-answers. REVERSE (and any non-answer round) is left untouched — it has no
    per-answer scores to join against and is scored separately.
    """
    scored_round_to_stage = {
        "warmup": "WARMUP", "domain": "DOMAIN",
        "behavioural": "BEHAVIOURAL", "case": "CASE",
    }
    if not isinstance(round_scores, dict):
        return {}
    out = {}
    for key, val in round_scores.items():
        stage = scored_round_to_stage.get(str(key).strip().lower())
        if stage is not None and stage not in sub_stages:
            out[key] = 0
        else:
            out[key] = val
    return out


def calibration_sentence(cal: dict) -> str:
    """E6 — ONE sentence explaining the calibration delta, for the readiness-band block.

    The delta is the distance between how good they THOUGHT an answer was and how good it
    actually was, and that distance is a skill in itself: an interviewer can hear it. This
    says what the two numbers mean and what to do about the gap. It is never a claim about
    the person — it describes two numbers and the distance between them, nothing more.
    """
    cal = cal or {}
    profile = cal.get("profile")
    conf, score, delta = cal.get("avg_confidence"), cal.get("avg_score"), cal.get("calibration_delta")
    if profile in (None, "insufficient_data") or conf is None or score is None or delta is None:
        return ""
    gap = abs(delta)
    if profile == "over_confident":
        return (
            f"You rated your answers {gap} points above where they actually landed "
            f"({conf}/5 against {score}/5) — so the work is not only the answers, it is "
            f"catching yourself in the room when one is thinner than it feels."
        )
    if profile == "under_confident":
        return (
            f"You rated your answers {gap} points below where they actually landed "
            f"({conf}/5 against {score}/5) — you are marking yourself down harder than we "
            f"did, and an interviewer hears that discount before they hear the answer."
        )
    return (
        f"Your ratings tracked your actual performance closely ({conf}/5 against "
        f"{score}/5) — knowing what you know is worth as much in the room as the "
        f"knowledge itself."
    )


def calibration_profile(pairs: list[tuple]) -> dict:
    """pairs: ordered list of (rating_or_None, score_1_5) for scored answers.

    Returns the session calibration profile. Null-rating answers are excluded.
    """
    rated = [(r, s) for (r, s) in pairs if r is not None and s is not None]
    if not rated:
        return {
            "profile": "insufficient_data",
            "avg_confidence": None,
            "avg_score": None,
            "calibration_delta": None,
            "per_answer": [],
            "rated_count": 0,
            "sentence": "",
        }

    per_answer = []
    counts = {"well_calibrated": 0, "over_confident": 0, "under_confident": 0}
    conf_sum = 0.0
    score_sum = 0.0
    for rating, score in rated:
        cat = _categorize(rating, score)
        counts[cat] += 1
        conf_sum += rating
        score_sum += score
        per_answer.append({"rating": rating, "score": round(float(score), 1), "category": cat})

    n = len(rated)
    avg_conf = conf_sum / n
    avg_score = score_sum / n

    # Modal category; tie -> over_confident (the pattern we most want to flag).
    top = max(counts.values())
    if counts["over_confident"] == top:
        profile = "over_confident"
    elif counts["under_confident"] == top and counts["under_confident"] > counts["well_calibrated"]:
        profile = "under_confident"
    elif counts["well_calibrated"] == top:
        profile = "well_calibrated"
    else:
        profile = "over_confident"

    out = {
        "profile": profile,
        "avg_confidence": round(avg_conf, 1),
        "avg_score": round(avg_score, 1),
        "calibration_delta": round(avg_conf - avg_score, 1),
        "per_answer": per_answer,
        "rated_count": n,
    }
    out["sentence"] = calibration_sentence(out)
    return out
