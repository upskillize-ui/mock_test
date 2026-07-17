"""Context-weighted scoring — the benchmark, the gates, the evidence floor.

The bug this sprint exists to kill, stated once: Easy / 10 min / raw 100 used to read
stronger than Critical / 45 min / raw 75. The first two tests below are that bug, pinned
in both directions.

Runnable with:  python -m pytest tests/test_scoring.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DATABASE_URL", "mysql+pymysql://u:p@localhost/db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("APP_ENV", "dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app import scoring as sc  # noqa: E402
from app import stages as st  # noqa: E402


def bench(raw, difficulty, duration, feedback="interview", attempted=4, offered=4, mode=None):
    return sc.compute_benchmark(
        raw, difficulty=difficulty, duration_min=duration, feedback=feedback,
        rounds_attempted=attempted, rounds_offered=offered, mode=mode,
    )


# ── ACCEPTANCE (a) + (b): the inversion is gone ─────────────────────────────

def test_easy_ten_minute_perfect_run_benchmarks_at_42():
    r = bench(100, "Easy", 10)
    assert r["benchmark"] == 42                       # 100 × .60 × .70
    assert r["raw"] == 100                            # raw is NEVER re-weighted


def test_critical_45_minute_coach_run_at_raw_75_benchmarks_at_100():
    r = bench(75, "Critical", 45, feedback="coach")
    assert r["benchmark"] == 100                      # display-capped
    assert r["benchmark_uncapped"] == 101.2           # 75 × 1.25 × 1.20 × .90 = 101.25
    assert r["benchmark_uncapped"] > r["benchmark"], "the uncapped value must survive storage"


def test_the_inversion_this_sprint_exists_to_kill():
    # The whole sprint in one assertion.
    easy_perfect = bench(100, "Easy", 10)["benchmark"]
    critical_good = bench(75, "Critical", 45, feedback="coach")["benchmark"]
    assert critical_good > easy_perfect


# ── The factors ─────────────────────────────────────────────────────────────

def test_every_factor_comes_from_the_one_table():
    r = bench(100, "Stretch", 30, feedback="coach", attempted=3, offered=4)
    assert r["factors"]["difficulty"] == sc.WEIGHTS["difficulty"]["Stretch"]
    assert r["factors"]["evidence"] == sc.WEIGHTS["evidence"][30]
    assert r["factors"]["feedback"] == sc.WEIGHTS["feedback"]["coach"]
    assert r["factors"]["coverage"] == 0.75
    assert r["weights_version"] == sc.WEIGHTS_VERSION


@pytest.mark.parametrize("duration,expected", [
    (5, 0.70), (10, 0.70), (15, 0.70),      # below/at the first rung
    (20, 1.00), (25, 1.00),
    (30, 1.10), (44, 1.10),
    (45, 1.20), (60, 1.20),                 # above the last rung
])
def test_a_duration_between_buckets_takes_the_rung_it_actually_reached(duration, expected):
    assert sc.evidence_factor(duration) == expected


def test_an_unknown_or_junk_context_never_silently_deflates_a_score():
    # A typo in a difficulty string must not cost a student a band.
    assert sc.difficulty_factor("EASY") == 0.60      # case-insensitive, still recognised
    assert sc.difficulty_factor("Brutal") == 1.00    # unknown -> neutral, never punitive
    assert sc.difficulty_factor(None) == 1.00
    assert sc.feedback_factor("COACH") == 0.90
    assert sc.feedback_factor("banana") == 1.00
    assert sc.evidence_factor(None) == 1.00
    assert sc.evidence_factor("twenty") == 1.00


def test_mode_is_live_now_that_the_intake_sprint_shipped_the_selector():
    """The dormancy this replaces was guarding one rule: nothing may be weighted by a mode
    nobody can choose. The Intake sprint made it choosable, so the factor counts — and the
    bump to 2026.07-2 is what keeps a July benchmark comparable to a September one."""
    assert sc.MODE_FACTOR_ACTIVE is True
    assert sc.WEIGHTS_VERSION == "2026.07-2"
    assert set(sc.WEIGHTS["mode"]) == {"TEXT", "AUDIO", "VIDEO"}

    assert sc.mode_factor("TEXT") == 0.90
    assert sc.mode_factor("AUDIO") == 1.00
    assert sc.mode_factor("VIDEO") == 1.00

    # The reconciled vocabulary still resolves — stored rows and older clients say these.
    assert sc.mode_factor("VOICE") == 1.00      # -> AUDIO
    assert sc.mode_factor("HYBRID") == 1.00     # -> VIDEO
    assert sc.mode_factor("text") == 0.90       # case is not a weighting decision


def test_an_unknown_mode_is_never_charged_the_text_discount():
    """1.00, not 0.90. A database without migration 009 has no session_mode, and marking a
    spoken session down for a missing column would be a penalty for OUR deploy state."""
    for m in (None, "", "junk", "AUDIO-ISH"):
        assert sc.mode_factor(m) == 1.00


def test_only_text_actually_moves_a_benchmark():
    """AUDIO and VIDEO are both 1.00, so activating the factor re-scored nobody: every
    session that existed before the bump was spoken, and scores exactly as it did."""
    assert bench(80, "Realistic", 20, mode="AUDIO")["benchmark"] == 80
    assert bench(80, "Realistic", 20, mode="VIDEO")["benchmark"] == 80
    assert bench(80, "Realistic", 20, mode=None)["benchmark"] == 80
    # Typed: same content score, a lower bar cleared.
    assert bench(80, "Realistic", 20, mode="TEXT")["benchmark"] == 72


def test_the_mode_factor_never_touches_the_raw_score():
    """skipped != failed's sibling promise: typed = spoken for CONTENT (B2). The mode
    tempers the benchmark only — the raw answer quality is what it is."""
    typed = bench(80, "Realistic", 20, mode="TEXT")
    spoken = bench(80, "Realistic", 20, mode="AUDIO")
    assert typed["raw"] == spoken["raw"] == 80
    assert typed["factors"]["mode"] == 0.90
    assert spoken["factors"]["mode"] == 1.00


# ── Coverage ────────────────────────────────────────────────────────────────

def test_coverage_tempers_the_benchmark_but_never_the_raw_score():
    r = bench(80, "Realistic", 20, attempted=2, offered=4)
    assert r["factors"]["coverage"] == 0.5
    assert r["benchmark"] == 40
    assert r["raw"] == 80, "skipped is not failed — raw is untouched by coverage"


def test_coverage_is_clamped_and_survives_nonsense():
    assert sc.coverage_factor(4, 4) == 1.0
    assert sc.coverage_factor(9, 4) == 1.0        # more attempted than offered -> 1, not 2.25
    assert sc.coverage_factor(-1, 4) == 0.0
    assert sc.coverage_factor(2, 0) == 1.0        # nothing offered -> no opinion
    assert sc.coverage_factor(None, None) == 1.0


def test_coverage_reads_the_answer_id_join_and_ignores_the_reverse_round():
    cov = sc.coverage({"DOMAIN", "CASE", "REVERSE"})
    assert cov["covered"] == ["DOMAIN", "CASE"]
    assert cov["skipped"] == ["WARMUP", "BEHAVIOURAL"]
    assert cov["attempted"] == 2 and cov["offered"] == 4
    assert cov["skipped_labels"] == ["Warm-up", "Behavioural"]
    assert "REVERSE" not in sc.COVERAGE_ROUNDS, "their questions for us are not a scored round"


# ── ACCEPTANCE (a) continued: the gates outrank the arithmetic ──────────────

def gates(earned, difficulty, duration, case=True, raw=None):
    return sc.band_gates(earned, difficulty=difficulty, duration_min=duration,
                         case_attempted=case, raw=raw)


def test_easy_caps_at_building_however_perfect_the_run():
    g = gates("Offer-Ready", "Easy", 45, raw=100)
    assert g["band"] == "Building"
    assert g["earned_band"] == "Offer-Ready"
    assert g["capped"] is True
    assert g["copy"] == ("Perfect run — Easy caps at Building. Step up to Realistic to "
                         "unlock Interview-Ready.")


def test_a_ten_minute_session_caps_one_band_below_what_was_earned():
    assert gates("Offer-Ready", "Critical", 10)["band"] == "Interview-Ready"
    assert gates("Interview-Ready", "Critical", 10)["band"] == "Building"
    assert gates("Building", "Critical", 10)["band"] == "Not Ready"
    # The floor holds — there is no band below Not Ready to fall to.
    assert gates("Not Ready", "Critical", 10)["band"] == "Not Ready"


def test_the_short_session_copy_says_we_saw_too_little_never_you_did_badly():
    copy = gates("Interview-Ready", "Realistic", 10)["copy"]
    assert "Ten minutes is a taste" in copy
    assert "20 minutes" in copy
    assert "Interview-Ready" in copy, "it names the band they actually earned"


def test_offer_ready_needs_a_real_bar_simulated():
    # All three conditions met -> it stands.
    assert gates("Offer-Ready", "Stretch", 20, case=True)["band"] == "Offer-Ready"
    assert gates("Offer-Ready", "Critical", 45, case=True)["band"] == "Offer-Ready"
    # Miss any one -> Interview-Ready.
    assert gates("Offer-Ready", "Realistic", 45, case=True)["band"] == "Interview-Ready"
    assert gates("Offer-Ready", "Stretch", 15, case=True)["band"] == "Interview-Ready"
    assert gates("Offer-Ready", "Stretch", 45, case=False)["band"] == "Interview-Ready"


def test_the_offer_ready_copy_names_exactly_what_was_missing():
    copy = gates("Offer-Ready", "Realistic", 15, case=False)["copy"]
    assert "it needs Stretch or Critical, it needs 20 minutes or more and it needs the case round attempted" in copy
    one = gates("Offer-Ready", "Stretch", 45, case=False)["copy"]
    assert "it needs the case round attempted." in one
    assert " and " not in one.split("simulated:")[1], "one missing condition, no list-joining"


def test_when_several_gates_bind_the_most_restrictive_one_wins():
    # Easy (-> Building) AND 10-min (-> Interview-Ready) AND the Offer-Ready gate.
    g = gates("Offer-Ready", "Easy", 10, case=True, raw=100)
    assert g["band"] == "Building", "the harshest cap sets the ceiling"
    assert {x["code"] for x in g["gates"]} == {"easy", "short_session", "offer_ready"}
    assert "Easy caps at Building" in g["copy"], "the copy names the gate that actually bound"


def test_a_gate_that_is_not_binding_stays_quiet():
    g = gates("Building", "Easy", 45)
    assert g["band"] == "Building"
    assert g["capped"] is False
    assert g["gates"] == [] and g["copy"] == ""


def test_no_gate_can_ever_promote_anyone():
    for earned in sc.BAND_LADDER:
        for difficulty in ("Easy", "Realistic", "Stretch", "Critical"):
            for duration in (10, 20, 45):
                for case in (True, False):
                    g = gates(earned, difficulty, duration, case=case)
                    assert sc.BAND_LADDER.index(g["band"]) <= sc.BAND_LADDER.index(earned)


def test_a_junk_band_degrades_to_not_ready_rather_than_exploding():
    assert gates("Excellent", "Realistic", 20)["band"] == "Not Ready"
    assert gates(None, "Realistic", 20)["earned_band"] == "Not Ready"


# ── ACCEPTANCE (c): the evidence floor ──────────────────────────────────────

def test_under_three_substantive_answers_there_is_no_verdict_to_give():
    assert sc.has_minimum_evidence(0) is False
    assert sc.has_minimum_evidence(2) is False
    assert sc.has_minimum_evidence(3) is True
    assert sc.has_minimum_evidence(9) is True
    assert sc.has_minimum_evidence(None) is False


def test_the_insufficient_evidence_card_is_about_the_evidence_not_the_person():
    card = sc.insufficient_evidence_card(2)
    assert card["substantive_answers"] == 2 and card["minimum"] == 3
    assert "2 substantive answers" in card["copy"]
    assert "not about you" in card["copy"]
    assert card["copy"].count("answer") >= 1
    # Singular reads like English, not like a template.
    assert "1 substantive answer," in sc.insufficient_evidence_card(1)["copy"]


def test_an_auto_submitted_partial_counts_as_evidence_but_an_empty_skip_does_not():
    # The prompt's rule, checked against the gate that actually decides it upstream.
    partial = "We migrated the reporting pipeline to Airflow and cut the nightly run"
    assert st.is_non_substantive(partial) is False
    assert st.is_non_substantive(st.TIMEOUT_SKIP_TEXT) is True
    answers = [partial, st.TIMEOUT_SKIP_TEXT, partial, st.TIMEOUT_SKIP_TEXT, partial]
    assert st.substantive_count(answers) == 3
    assert sc.has_minimum_evidence(st.substantive_count(answers)) is True


# ── ACCEPTANCE (d): tuning the table never rewrites history ─────────────────

def test_changing_a_constant_cannot_change_a_stored_benchmark(monkeypatch):
    stored = bench(100, "Easy", 10)
    assert stored["benchmark"] == 42
    assert stored["weights_version"] == sc.WEIGHTS_VERSION

    # What the table said when this attempt was scored. Captured rather than hard-coded:
    # the literal used to be "2026.07-1" and this test broke the day the Intake sprint
    # bumped it — which is a false alarm, because the version MOVING is normal and the
    # thing under test is that a stored attempt does not move WITH it.
    version_at_scoring_time = sc.WEIGHTS_VERSION

    # Ops retunes Easy upward and bumps the version.
    monkeypatch.setitem(sc.WEIGHTS["difficulty"], "Easy", 0.90)
    monkeypatch.setattr(sc, "WEIGHTS_VERSION", "2026.09-2")

    # The stored attempt is a stored VALUE — nothing recomputes it.
    assert stored["benchmark"] == 42
    assert stored["weights_version"] == version_at_scoring_time
    assert stored["weights_version"] != sc.WEIGHTS_VERSION
    # And its explanation still reads off its own stored factors, not the live table.
    assert any("×0.60" == r["value"] for r in sc.math_lines(stored)), \
        "an old attempt must explain itself with the weights it was actually scored on"
    # A NEW attempt picks the new constant up.
    assert bench(100, "Easy", 10)["benchmark"] == 63


# ── Show the math ───────────────────────────────────────────────────────────

def test_show_the_math_lists_this_attempts_factors_in_plain_words():
    r = bench(100, "Easy", 10)
    rows = sc.math_lines(r, gates("Offer-Ready", "Easy", 10, raw=100))
    keys = [row["key"] for row in rows]
    assert keys[0] == "raw"
    assert "difficulty" in keys and "evidence" in keys and "feedback" in keys and "coverage" in keys
    assert "mode" not in keys, \
        "with no mode on the attempt, 'Mode — Unknown ×1.00' explains nothing"
    assert "total" in keys
    assert any(k.startswith("gate:") for k in keys), "a cap that moved the band must be shown"
    for row in rows:
        assert row["label"] and row["note"], "every row explains itself"


def test_the_math_shows_the_mode_row_once_a_mode_is_actually_known():
    """The flip side. A TEXT session moved a number, so the readout owes the learner the
    reason — an unexplained ×0.90 is exactly the "score with no context" this whole file
    exists to stop."""
    rows = sc.math_lines(bench(100, "Easy", 10, mode="TEXT"))
    mode_rows = [r for r in rows if r["key"] == "mode"]
    assert len(mode_rows) == 1
    assert mode_rows[0]["value"] == "×0.90"
    assert "Text" in mode_rows[0]["label"]
    assert "same content bar" in mode_rows[0]["note"]


def test_a_spoken_session_says_no_adjustment_rather_than_going_quiet():
    rows = sc.math_lines(bench(100, "Easy", 10, mode="AUDIO"))
    mode_rows = [r for r in rows if r["key"] == "mode"]
    assert len(mode_rows) == 1
    assert mode_rows[0]["value"] == "×1.00"


def test_the_math_says_level_is_not_a_factor_so_nothing_is_double_counted():
    note = sc.math_lines(bench(80, "Realistic", 20))[0]["note"]
    assert "level is already built into this" in note.lower()


def test_clearing_100_is_shown_as_clearing_it_not_as_a_rounding_accident():
    rows = sc.math_lines(bench(75, "Critical", 45, feedback="coach"))
    cap = [r for r in rows if r["key"] == "cap"]
    assert cap, "an uncapped score above 100 must say so"
    assert "101.2" in cap[0]["note"] and "room to spare" in cap[0]["note"]


# ── The re-attempt window + the EcoPro hook ─────────────────────────────────

def test_the_reattempt_window_is_a_stable_shape_for_every_band():
    for band in sc.BAND_LADDER:
        w = sc.reattempt_window(band)
        assert isinstance(w["days"], int) and w["days"] > 0
        assert w["copy"]
    assert sc.reattempt_window("Interview-Ready")["days"] == 3
    assert sc.reattempt_window("Building")["days"] == 7
    assert sc.reattempt_window("nonsense")["days"] == 7, "unknown band degrades safely"


def test_the_ecopro_export_carries_the_band_the_benchmark_and_the_top_three_fixes():
    gaps = [{"gap": f"fix {i}", "tryThisNextTime": f"do {i}", "upskillizeCourse": f"c{i}"} for i in range(5)]
    x = sc.ecopro_export(band="Building", benchmark=42, gaps=gaps,
                         reattempt=sc.reattempt_window("Building"), session_id="s1")
    assert x["band"] == "Building" and x["benchmark"] == 42
    assert len(x["top_fixes"]) == 3, "top THREE, most important first"
    assert x["top_fixes"][0] == {"fix": "fix 0", "try_this_next_time": "do 0", "course": "c0"}
    assert x["reattempt_window"]["days"] == 7
    assert x["weights_version"] == sc.WEIGHTS_VERSION
    assert x["session_id"] == "s1"


def test_presence_calibration_and_focus_never_leak_into_the_ecopro_hook():
    x = sc.ecopro_export(band="Building", benchmark=42, gaps=[],
                         reattempt=sc.reattempt_window("Building"))
    for banned in ("presence", "calibration", "focus", "attention", "camera"):
        assert banned not in str(x).lower(), f"{banned} is report-only and must not reach an agent"


def test_an_unscored_session_exports_no_band_and_no_benchmark():
    x = sc.ecopro_export(band="Not Ready", benchmark=0, gaps=[], reattempt={}, scored=False)
    assert x["scored"] is False
    assert x["band"] is None and x["benchmark"] is None, \
        "an insufficient-evidence session has no verdict to hand downstream"


def test_legacy_string_gaps_still_export():
    x = sc.ecopro_export(band="Building", benchmark=42, gaps=["be specific"], reattempt={})
    assert x["top_fixes"] == [{"fix": "be specific", "try_this_next_time": "", "course": ""}]


# ── ACCEPTANCE, item 7: trend over trophy ───────────────────────────────────

def test_a_placement_view_reads_the_latest_three_never_the_best_ever():
    # Newest first: one great day in the past must not represent them today.
    assert sc.latest_average([40, 44, 48, 99, 97]) == 44.0
    assert sc.latest_average([90]) == 90.0
    assert sc.latest_average([]) is None
    assert sc.latest_average([None, "x"]) is None
    assert sc.latest_average([40, None, 50]) == 45.0, "unscored attempts are skipped, not zeroed"


# ── The wiring: what /session/end actually assembles ────────────────────────
# scoring.py is pure and tested above. These pin the JOIN between it and the endpoint —
# the layer where a readout has historically gone wrong (a band shown twice, a raw score
# rendered as a benchmark, context quietly dropped).

def _main():
    from app import main as m
    return m


SESSION_EASY_10 = {
    "role": "Data Analyst", "company": "TCS", "level": "Fresher",
    "difficulty": "Easy", "duration_min": 10, "mode": "interview",
}
SESSION_CRITICAL_45 = {
    "role": "Backend Engineer", "company": "", "level": "3-10 years",
    "difficulty": "Critical", "duration_min": 45, "mode": "coach",
}
ALL_ROUNDS = {"WARMUP", "DOMAIN", "BEHAVIOURAL", "CASE"}


def test_the_endpoint_reads_feedback_from_the_mode_column_not_a_mode_factor():
    # The session's `mode` column IS the feedback style (interview/coach). The lobby
    # renamed the heading to FEEDBACK; the column kept its name. Getting this wrong would
    # silently apply Coach's 0.90 to nobody, or to everybody.
    m = _main()
    result, _band, _cov = m._score_context(SESSION_CRITICAL_45, 75, ALL_ROUNDS)
    assert result["factors"]["feedback"] == sc.WEIGHTS["feedback"]["coach"]
    assert result["factors"]["mode"] == 1.00, "mode is dormant until the Intake sprint"
    assert result["benchmark"] == 100


def test_acceptance_a_end_to_end_easy_ten_minute_perfect_run():
    m = _main()
    result, band, cov = m._score_context(SESSION_EASY_10, 100, ALL_ROUNDS)
    assert result["benchmark"] == 42
    assert band["band"] == "Building", "Easy caps at Building however perfect the run"
    assert band["earned_band"] == "Offer-Ready"
    assert "Step up to Realistic" in band["copy"]
    assert cov["attempted"] == 4


def test_the_case_gate_reads_the_answer_id_join_not_the_stage_plan():
    # "Offer-Ready needs the case attempted" must mean a case answer actually landed —
    # not merely that the plan offered a case round.
    m = _main()
    _r, band_with, _c = m._score_context(
        {**SESSION_CRITICAL_45, "mode": "interview"}, 90, ALL_ROUNDS)
    assert band_with["band"] == "Offer-Ready"
    _r2, band_without, _c2 = m._score_context(
        {**SESSION_CRITICAL_45, "mode": "interview"}, 90, ALL_ROUNDS - {"CASE"})
    assert band_without["band"] == "Interview-Ready"
    assert "case round attempted" in band_without["copy"]


def test_the_profile_strip_never_guesses_a_mode_it_was_not_given():
    m = _main()
    cov = sc.coverage({"DOMAIN", "CASE"})
    p = m._session_profile(SESSION_EASY_10, cov)
    assert p.role == "Data Analyst" and p.company == "TCS"
    assert p.difficulty == "Easy" and p.duration_min == 10
    assert p.feedback == "interview"
    assert p.mode is None, "TEXT/VOICE/HYBRID lands with the Intake sprint — until then, no guess"
    assert p.rounds_covered == ["Domain", "Case"]
    assert p.rounds_skipped == ["Warm-up", "Behavioural"]


def test_a_scored_readout_carries_the_band_the_benchmark_and_the_working():
    m = _main()
    result, band, cov = m._score_context(SESSION_EASY_10, 100, ALL_ROUNDS)
    d = {"oneLine": "You opened with the number.", "subScores": {"clarity": 8},
         "gaps": [{"gap": "g1", "tryThisNextTime": "t1", "upskillizeCourse": "c1"}]}
    r = m._debrief_response(
        "s1", SESSION_EASY_10, d, overall_band=band["band"], round_bands={"domain": "Building"},
        calibration={}, delivery_profile={}, presence_block={}, early_wrap=None,
        scored=True, substantive=6, result=result, band_result=band, cov=cov,
    )
    assert r.scored is True
    assert r.overall_band == "Building"
    assert r.score.benchmark == 42 and r.score.raw == 100
    assert r.score.earned_band == "Offer-Ready" and r.score.capped is True
    assert r.score.math, "show-the-math must ride with the score"
    assert r.reattempt_window["days"] == 7
    assert r.ecopro["band"] == "Building" and r.ecopro["benchmark"] == 42
    assert r.profile.difficulty == "Easy"


def test_an_unscored_readout_carries_no_band_no_benchmark_and_no_tiles():
    # ACCEPTANCE (c). The evidence floor renders a card, not a verdict — and crucially not
    # "Not Ready · 0/10", which is what scoring a no-show looks like.
    m = _main()
    r = m._debrief_response(
        "s1", SESSION_EASY_10, {"oneLine": "x", "subScores": {"clarity": 3}},
        overall_band="", round_bands={"domain": "Not Ready"}, calibration={},
        delivery_profile={}, presence_block={}, early_wrap=None,
        scored=False, substantive=2, result=None, band_result=None,
        cov=sc.coverage(set()),
    )
    assert r.scored is False
    assert r.overall_band == "" and r.round_bands == {} and r.sub_scores == {}
    assert r.score is None
    assert r.reattempt_window == {}
    assert r.evidence["substantive_answers"] == 2 and r.evidence["minimum"] == 3
    assert r.ecopro["band"] is None and r.ecopro["benchmark"] is None
    # The context strip survives — it is the one thing that is true either way.
    assert r.profile.role == "Data Analyst"


def test_presence_and_delivery_ride_the_readout_but_never_the_benchmark():
    # Item 11/12: report-only means report-only.
    m = _main()
    result, band, cov = m._score_context(SESSION_EASY_10, 100, ALL_ROUNDS)
    presence_block = {"measured": True, "events_total": 9, "by_type": {"window_blur": 9},
                      "coaching_note": "note"}
    r = m._debrief_response(
        "s1", SESSION_EASY_10, {"oneLine": "x"}, overall_band=band["band"], round_bands={},
        calibration={"profile": "over_confident", "avg_confidence": 5, "avg_score": 2},
        delivery_profile={"enough_data": True, "avg_wpm": 210}, presence_block=presence_block,
        early_wrap=None, scored=True, substantive=6, result=result, band_result=band, cov=cov,
    )
    assert r.professional_presence["events_total"] == 9
    assert "band" not in r.professional_presence, "item 9 — presence carries no band"
    assert r.calibration["profile"] == "over_confident"
    # Nine attention events and a wild calibration delta changed the benchmark by nothing.
    assert r.score.benchmark == 42
    assert set(r.score.factors) == {"difficulty", "evidence", "feedback", "coverage", "mode"}


def test_the_math_note_matches_what_actually_happened():
    # "Rounds you didn't reach" printed under "4 of 4 rounds" is a small lie that costs
    # trust in every other number on the page.
    full = [r for r in sc.math_lines(bench(80, "Realistic", 20, attempted=4, offered=4)) if r["key"] == "coverage"][0]
    assert "reached every scored round" in full["note"]
    assert "didn't reach" not in full["note"]
    partial = [r for r in sc.math_lines(bench(80, "Realistic", 20, attempted=2, offered=4)) if r["key"] == "coverage"][0]
    assert "aren't marked against your answers" in partial["note"]
