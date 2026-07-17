"""THE INTAKE BOUNDARY — one place where a session's context is decided.

WHY THIS FILE EXISTS
Session context used to be assembled inline in `/session/start`: gather the LMS rows,
stitch them into prose, glue the result onto `body.intro`, insert, and hope. That worked,
and it hid three separate classes of bug:

  1. NOBODY OWNED THE MERGE. The form said "Data Analyst", ProfileIQ said "Full Stack
     Developer", and which one won depended on which line of the endpoint you read.
  2. SANITIZING HAPPENED AT RENDER TIME, over and over, in prompts.py — once per prompt
     build, per turn, forever. A sanitiser called N times is a sanitiser whose contract
     nobody can state.
  3. VALIDATION HAPPENED AFTER SPEND. A config with no role still reached the LLM before
     anything checked it, because the check lived downstream of the call.

So: ONE function does the gathering, ONE does the merge, free text is cleaned EXACTLY
ONCE here, and nothing paid-for happens until the config has been validated. Downstream
code — prompts, scoring, the readout — receives a `SessionConfig` and TRUSTS it.

THE RULES, IN ORDER (they are the phase spec, A1–A6):
  A1 GATHER          — LMS context + the lobby form.
  A2 MERGE, FORM WINS— anything the student typed beats anything we inferred.
  A3 SANITIZE ONCE   — here, at the boundary, with the caps declared here.
  A4 VALIDATE BEFORE — every check completes before the first rupee of LLM or TTS.
     SPEND
  A5 VENDOR SEATBELT — TTS dead ≠ session dead. Offer TEXT, honestly.
  A6 ONE OBJECT      — the merged config is the single source of truth: the confirmation
                       card, the Session Profile strip and the attempt record all render
                       THIS, so they cannot drift apart.

ONE HONEST EXCEPTION TO "DOWNSTREAM NEVER RE-SANITIZES" — READ BEFORE DELETING ANYTHING:
  prompts.py still calls sanitize_untrusted on the text it renders, and that is deliberate.
  Every session stored BEFORE this boundary existed holds RAW text: sanitising used to
  happen at render time, so it was never applied at rest. Strip that pass out and every
  historical session replays its un-defused JD straight into the model — a security
  regression bought with a tidier diagram.

  It costs nothing to keep, because sanitize_untrusted is IDEMPOTENT: the tag regex has
  nothing left to strip, the phrase regex cannot re-match "[REDACTED]", and the cap is the
  same number in both places. sanitize(sanitize(x)) == sanitize(x), which is exactly what
  acceptance test (b) asserts when it looks for double-encoding.

  So the contract holds where it matters: NEW context is cleaned exactly once, here, and
  what prompts.py does to already-clean text is a no-op that also happens to protect the
  rows we cannot go back and fix.
"""

import logging
from dataclasses import dataclass, field

from .db import get_student_context
from .prompts import FACT_CITY_PREFIX, FACT_INTERESTS_PREFIX, sanitize_untrusted

log = logging.getLogger(__name__)


# ── MODE: how the student answers ────────────────────────────────────────────
# NOT to be confused with `vyom_sessions.mode`, which is the FEEDBACK style
# (interview | coach) and predates this. The column keeps its name; this concept gets a
# new one. Two different things called "mode" is the single easiest way to break this
# sprint — `feedback` and `session_mode` are the names that survive.
#
# The weights for these live in scoring.WEIGHTS["mode"] and NOWHERE ELSE (B4).
MODES = ("TEXT", "AUDIO", "VIDEO")
DEFAULT_MODE = "AUDIO"

# The vocabulary the phase doc used before this sprint reconciled it. Kept so an older
# client, a stored row or a half-applied deploy resolves instead of falling over.
# scoring.MODE_ALIASES holds the same mapping for the weights table.
MODE_ALIASES = {"VOICE": "AUDIO", "HYBRID": "VIDEO"}


def normalise_mode(mode) -> str:
    """Any spelling of a mode → one of MODES. Unknown/empty → DEFAULT_MODE.

    Never raises: a junk mode must not be the reason a session fails to start. It is a
    presentation choice, not a permission.
    """
    key = str(mode or "").strip().upper()
    key = MODE_ALIASES.get(key, key)
    return key if key in MODES else DEFAULT_MODE


def mode_wants_tts(mode: str) -> bool:
    """TEXT spends nothing at Sarvam. Not 'less' — nothing (B2)."""
    return normalise_mode(mode) != "TEXT"


def mode_wants_mic(mode: str) -> bool:
    """TEXT never asks for the microphone. We do not request a permission the mode cannot
    use — an unused prompt is a scary dialog charged against our credibility for nothing.
    """
    return normalise_mode(mode) != "TEXT"


def mode_wants_camera(mode: str) -> bool:
    """VIDEO turns the camera on and shows the self-view.

    Presence metrics (gaze, posture, expression) are PHASE D and are not computed here —
    the camera is on because the student chose a mode that says "video" on the tin, and a
    chip that promises video while nothing video happens is a lie we would be shipping.
    Phase D later adds metrics on top of a camera that is already running.
    """
    return normalise_mode(mode) == "VIDEO"


def mode_allows_typing(mode: str) -> bool:
    """TEXT types by definition; VIDEO may type or speak, per question, switching freely
    (B3). AUDIO is the spoken path and keeps the capture gate exactly as it is.
    """
    return normalise_mode(mode) in ("TEXT", "VIDEO")


# ── The caps. Declared once, applied once. ───────────────────────────────────
# These were spread across prompts.py as magic numbers at the call sites. They are a
# property of the INPUT, not of the prompt that happens to render it.
CAP_SELF_INTRO = 4000
CAP_JD = 2000
CAP_RESUME = 3000
CAP_NAME = 120
CAP_ROLE = 120
CAP_COMPANY = 120
CAP_FOCUS_ITEM = 80
CAP_CITY = 80
CAP_INTERESTS = 200
CAP_AI_PROFILE = 2000
CAP_SKILLS = 500
CAP_EDUCATION = 200


@dataclass(frozen=True)
class SessionConfig:
    """The definitive session config. Frozen: once the boundary has spoken, nothing
    downstream gets to quietly disagree with it.

    Everything in here is ALREADY SANITISED. That is the contract, and it is why this is
    a type and not a dict — a dict invites "just one more field" from a caller who has no
    idea whether the value passed the boundary.
    """
    # ── From the form. The student typed these; they win (A2).
    role: str
    level: str
    difficulty: str
    duration_min: int
    mode: str                      # TEXT | AUDIO | VIDEO  (how they answer)
    feedback: str                  # interview | coach     (when they hear about it)
    round: str = ""
    round_label: str = ""
    round_detail: str = ""
    company: str = ""
    focus: tuple = ()
    self_intro: str = ""
    jd: str = ""

    # ── From the LMS. Context, never an override.
    name: str = ""
    city: str = ""
    interests: str = ""
    education: str = ""
    current_status: str = ""
    current_role: str = ""
    employer: str = ""
    skills: str = ""
    ai_profile: str = ""
    resume_text: str = ""
    psycho: dict = field(default_factory=dict)
    enrollments: tuple = ()

    # ── Provenance. What actually answered, and what the student overrode.
    sources: tuple = ()
    overrides: tuple = ()

    @property
    def jd_used(self) -> bool:
        """The confirmation card's honest yes/no (A6)."""
        return bool(self.jd.strip())

    @property
    def wants_tts(self) -> bool:
        return mode_wants_tts(self.mode)

    @property
    def wants_mic(self) -> bool:
        return mode_wants_mic(self.mode)

    @property
    def wants_camera(self) -> bool:
        return mode_wants_camera(self.mode)

    def card(self) -> dict:
        """The confirmation card / Session Profile payload — A6's "defined once, rendered
        everywhere". The lobby card, the readout strip and the attempt record all read
        THIS, so there is no third place for them to drift apart in.
        """
        return {
            "role": self.role,
            "level": self.level,
            "difficulty": self.difficulty,
            "duration_min": self.duration_min,
            "mode": self.mode,
            "feedback": self.feedback,
            "round": self.round_label or self.round,
            "focus": list(self.focus),
            "jd_used": self.jd_used,
        }


class IntakeError(Exception):
    """A config that must never reach a paid call (A4).

    `offer_text_mode` is the seatbelt (A5): the session is not invalid, the voice vendor
    is simply unavailable, and TEXT is a real answer rather than an apology.
    """

    def __init__(self, errors: list[str], offer_text_mode: bool = False):
        self.errors = errors
        self.offer_text_mode = offer_text_mode
        super().__init__("; ".join(errors))


# ── A1: GATHER ───────────────────────────────────────────────────────────────

def gather(user_id: str, db) -> dict:
    """The LMS half. `db.get_student_context` does the reading; this owns the failure
    policy — a dead LMS costs us context, never a session.

    NOTE FOR TESTS: patch `intake.get_student_context`, not `main.get_student_context`.
    The gather moved here, so main's copy is no longer the one that runs — a patch there
    binds nothing and the test passes for the wrong reason.
    """
    try:
        return get_student_context(user_id, db) or {}
    except Exception as e:
        log.warning("intake.gather failed for uid=%s: %s", user_id, e)
        return {}


# ── A2 + A3: MERGE (form wins) and SANITIZE (exactly once) ───────────────────

def merge(form, ctx: dict, resume_text: str = "") -> SessionConfig:
    """One merge step, one sanitise pass, one definitive object.

    FORM WINS, and the rule is deliberately dumb: if the student typed it, it is true. Not
    "if it looks more specific", not "if ProfileIQ is more recent". They are sitting in
    front of the form telling us what they want to practise, and an LMS row from March
    does not get a vote. What the LMS supplies is everything they did NOT type.
    """
    ctx = ctx or {}
    overrides = []

    def s(v, cap):
        # THE only sanitise call for any of this data. Everything downstream trusts the
        # result — see the module docstring, A3.
        return sanitize_untrusted(str(v or ""), cap).strip()

    role = s(getattr(form, "role", ""), CAP_ROLE)
    if role and ctx.get("current_role") and role.lower() != str(ctx["current_role"]).lower():
        # Not a conflict to resolve — a fact to record. The card shows what they chose.
        overrides.append("role")

    # The form's name field is a courtesy; the LMS is authoritative for identity, because
    # the student does not get to interview as someone else.
    name = s(ctx.get("name") or getattr(form, "name", ""), CAP_NAME)

    focus = tuple(
        f for f in (s(x, CAP_FOCUS_ITEM) for x in (getattr(form, "focus", None) or []))
        if f
    )

    return SessionConfig(
        role=role,
        level=s(getattr(form, "level", ""), 40),
        difficulty=s(getattr(form, "difficulty", ""), 20),
        duration_min=int(getattr(form, "duration_min", 0) or 0),
        mode=normalise_mode(getattr(form, "session_mode", None)),
        feedback=s(getattr(form, "mode", "") or "interview", 20).lower() or "interview",
        round=s(getattr(form, "round", ""), 40),
        round_label=s(getattr(form, "round_label", ""), 80),
        round_detail=s(getattr(form, "round_detail", ""), 1000),
        company=s(getattr(form, "company", ""), CAP_COMPANY),
        focus=focus,
        self_intro=s(getattr(form, "intro", ""), CAP_SELF_INTRO),
        jd=s(getattr(form, "jd", ""), CAP_JD),

        name=name,
        city=s(ctx.get("city"), CAP_CITY),
        interests=s(ctx.get("interests"), CAP_INTERESTS),
        education=s(ctx.get("education"), CAP_EDUCATION),
        current_status=s(ctx.get("current_status"), 40),
        current_role=s(ctx.get("current_role"), CAP_ROLE),
        employer=s(ctx.get("employer"), CAP_COMPANY),
        skills=s(ctx.get("skills"), CAP_SKILLS),
        ai_profile=s(ctx.get("ai_profile"), CAP_AI_PROFILE),
        resume_text=s(resume_text, CAP_RESUME),
        psycho=dict(ctx.get("psycho") or {}),
        enrollments=tuple(ctx.get("enrollments") or ()),

        sources=tuple(ctx.get("source") or ()),
        overrides=tuple(overrides),
    )


# ── A4: VALIDATE BEFORE SPEND ────────────────────────────────────────────────

def validate(cfg: SessionConfig, *, tts_available: bool = True,
             minutes_remaining: int | None = None) -> None:
    """Every check, completed BEFORE the first LLM or TTS call. Raises IntakeError.

    The ordering is the whole point. These are cheap, local checks — the only reason they
    were ever downstream of a paid call is that nobody had a place to put them.
    """
    errors = []

    if not cfg.role:
        errors.append("Pick a target role before we start.")
    if not cfg.level:
        errors.append("Pick an experience level.")
    if cfg.duration_min <= 0:
        errors.append("Pick a session length.")
    if cfg.mode not in MODES:
        errors.append("Pick how you'd like to answer.")

    if minutes_remaining is not None and cfg.duration_min > minutes_remaining:
        errors.append(
            f"This session is {cfg.duration_min} minutes and you have "
            f"{minutes_remaining} left today."
        )

    if errors:
        raise IntakeError(errors)

    # A5 — the seatbelt. Voice being down is not the student's problem to solve, and it is
    # not a reason to burn their allowance on a session that cannot speak. TEXT is a real
    # session, so we offer it rather than apologising.
    if cfg.wants_tts and not tts_available:
        raise IntakeError(
            ["Voice is unavailable right now — continue in text?"],
            offer_text_mode=True,
        )


# ── The background block the persona reads ───────────────────────────────────

def background_lines(cfg: SessionConfig) -> list[str]:
    """The LMS context, as the prose the interviewer is given. Moved here from the
    endpoint: it is part of deciding what a session KNOWS, not part of serving a request.

    Everything here is already sanitised (A3). Nothing here re-cleans it.
    """
    lines = []

    if cfg.enrollments:
        rows = []
        for e in cfg.enrollments:
            status = "Certified" if e.get("certified") else f"{e.get('progress')}% complete"
            rows.append(f"  - {e.get('course')} ({status})")
        lines.append("ENROLLED COURSES:\n" + "\n".join(rows))

    if cfg.education:
        lines.append(f"EDUCATION: {cfg.education}")

    if cfg.current_status == "working_professional" and (cfg.current_role or cfg.employer):
        who = (f"{cfg.current_role} at {cfg.employer}"
               if cfg.current_role and cfg.employer else (cfg.current_role or cfg.employer))
        lines.append(
            f"CURRENT STATUS: Working professional — currently {who}. "
            f"They are targeting this new role. Probe their motivation for the change "
            f"and what they're seeking in this opportunity. Ask naturally — do not make it sound interrogative."
        )
    elif cfg.current_status == "working_professional":
        lines.append(
            "CURRENT STATUS: Working professional with experience. "
            "Probe their reason for exploring this role. Treat them as experienced — "
            "raise the bar accordingly."
        )
    elif cfg.current_status == "student_or_fresher":
        lines.append(
            "CURRENT STATUS: Student or fresher — no full-time work experience. "
            "Focus on academic projects, internships, learning experiences. "
            "Do NOT ask 'why are you leaving your current job' or 'current employer'."
        )

    if cfg.skills:
        lines.append(f"STATED SKILLS (test at least 2 of these): {cfg.skills}")

    # The ice-breaker's raw material, and the ONLY personal facts allowed near it. Both are
    # sparse — most students have neither — so the persona is told plainly that a missing
    # one means SKIP, never guess. See prompts.build_kickoff BEAT 2.
    if cfg.city:
        lines.append(
            f"{FACT_CITY_PREFIX} {cfg.city}. This is a FACT from their profile, not a "
            f"guess — it is safe for one light opening line if you want one."
        )

    if cfg.interests:
        lines.append(
            f"{FACT_INTERESTS_PREFIX} {cfg.interests}. From their profile, not inferred — "
            f"safe for one light opening line."
        )

    if cfg.ai_profile:
        lines.append(
            "AI-GENERATED PROFILE (highest quality data — use for deep personalization):\n"
            + cfg.ai_profile
        )

    # NOTE: the résumé is deliberately NOT here. It carries a delimiter the splitter cuts
    # on, so it is `intro_blob`'s to place — emitting it mid-background is precisely how
    # the JD used to get eaten. See intro_blob.

    if cfg.psycho:
        top = ", ".join(cfg.psycho.get("top") or []) or cfg.psycho.get("type", "")
        lines.append(
            f"PERSONALITY (psychometric test result): {cfg.psycho.get('type','')} — "
            f"dominant traits: {top}. "
            f"Analytical types → data-heavy questions with numbers. "
            f"Execution types → scenario-based action questions. "
            f"Collaboration/HR types → people-dynamic and stakeholder questions."
        )

    return lines


def intro_blob(cfg: SessionConfig) -> str:
    """What gets stored in `vyom_sessions.intro`.

    The delimiter format is inherited, not chosen: prompts._split_intro cuts this back
    apart on `--- RESUME ---` then `--- JOB DESCRIPTION ---`. Keeping the shape means no
    stored session has to be migrated to stay readable.

    THE ORDER IS LOAD-BEARING, and getting it wrong is not hypothetical — it was wrong.
    The old assembly was:

        [self_intro] --- JOB DESCRIPTION --- [jd] [lms background] --- RESUME --- [resume]

    and the splitter looks for RESUME *first*: everything before it became `self_intro`,
    so a JD pasted by a student who also had a résumé on file was swallowed whole into the
    self-intro section and `jd_section` came out EMPTY. The JD was in the prompt, but never
    in the slot that the JD-tailoring instructions actually read.

    The splitter wants RESUME, then JD, in that order. So that is what we write:

        [self_intro + lms background] --- RESUME --- [resume] --- JOB DESCRIPTION --- [jd]
    """
    head = []
    if cfg.self_intro:
        head.append(cfg.self_intro)
    # The LMS background belongs with the self-intro half: it is who they are, not the
    # role they are chasing. It must land BEFORE the résumé delimiter or the splitter will
    # read it as part of the résumé.
    lines = background_lines(cfg)
    if lines:
        head.append("\n\n".join(lines))

    blob = "\n\n".join(head)
    if cfg.resume_text:
        blob += "\n\n--- RESUME ---\n" + cfg.resume_text
    if cfg.jd:
        blob += "\n\n--- JOB DESCRIPTION ---\n" + cfg.jd
    return blob.strip()
