"""Offline tests for the self-healing loop's escalation policy.

No board, no Keil, no serial port -- `fold_iteration_outcome` is a pure function, so the
rule that decides "stop and ask a human" can be pinned down here.

Why this file exists: the loop used to compare each failure only against the immediately
previous one. That caught an AI hammering the same error, but not the far more common
failure mode -- oscillating between two wrong fixes (A/B/A/B), which reset the counter
every round and let the loop burn every remaining iteration before giving up.
"""
import unittest

from autodebug.engine import fold_iteration_outcome, fresh_loop_state


def run(signatures, threshold=2, window=6, passed_at=None):
    """Replay a sequence of failure signatures; return the 1-based iteration that stalled.

    `passed_at` marks an iteration (1-based) that succeeds instead of failing.
    Returns None when the loop never escalates.
    """
    state = fresh_loop_state()
    for i, sig in enumerate(signatures, 1):
        state, _repeated, stalled = fold_iteration_outcome(
            state, sig, passed=(i == passed_at), threshold=threshold, window=window)
        if stalled:
            return i
    return None


class StallDetection(unittest.TestCase):
    def test_identical_failure_escalates_at_threshold(self):
        self.assertEqual(run(["A", "A", "A", "A"]), 2)

    def test_two_way_oscillation_is_caught(self):
        """The regression this policy exists for: A/B/A/B must not run forever."""
        self.assertEqual(run(["A", "B", "A", "B"]), 3)

    def test_three_way_rotation_is_caught(self):
        self.assertEqual(run(["A", "B", "C", "A", "B", "C"]), 4)

    def test_genuine_progress_never_escalates(self):
        """Every round a brand-new error: the AI is moving, do not interrupt it."""
        self.assertIsNone(run(["A", "B", "C", "D", "E", "F"]))

    def test_threshold_is_configurable(self):
        self.assertEqual(run(["A", "A", "A", "A"], threshold=3), 3)
        self.assertEqual(run(["A", "B", "A", "B", "A"], threshold=3), 5)

    def test_signature_outside_the_window_is_forgotten(self):
        """A repeat far enough back is not evidence of being stuck."""
        self.assertIsNone(run(["A", "B", "C", "D", "A"], window=3))

    def test_consecutive_repeat_counts_even_with_a_tiny_window(self):
        self.assertEqual(run(["A", "A"], window=1), 2)


class PassResetsEverything(unittest.TestCase):
    def test_success_clears_the_history(self):
        state = fresh_loop_state()
        for sig in ("A", "B"):
            state, _, _ = fold_iteration_outcome(state, sig, passed=False)
        state, repeated, stalled = fold_iteration_outcome(state, "A", passed=True)

        self.assertFalse(repeated)
        self.assertFalse(stalled)
        self.assertEqual(state, fresh_loop_state())

    def test_failures_after_a_pass_start_from_zero(self):
        self.assertIsNone(run(["A", "A"], passed_at=1))


class RepeatedFailureFlag(unittest.TestCase):
    """`repeated_failure` tells the AI its last patch changed nothing."""

    def test_first_sighting_is_not_flagged(self):
        _, repeated, _ = fold_iteration_outcome(fresh_loop_state(), "A", passed=False)
        self.assertFalse(repeated)

    def test_second_sighting_is_flagged(self):
        state, _, _ = fold_iteration_outcome(fresh_loop_state(), "A", passed=False)
        _, repeated, _ = fold_iteration_outcome(state, "A", passed=False)
        self.assertTrue(repeated)

    def test_flagged_across_an_oscillation_too(self):
        state = fresh_loop_state()
        for sig in ("A", "B"):
            state, _, _ = fold_iteration_outcome(state, sig, passed=False)
        _, repeated, _ = fold_iteration_outcome(state, "A", passed=False)
        self.assertTrue(repeated)


class StatePersistenceShape(unittest.TestCase):
    """The state round-trips through .autodebug/state.json, so keep it JSON-safe."""

    def test_state_is_json_serialisable(self):
        import json
        state = fresh_loop_state()
        for sig in ("A", "B", "A"):
            state, _, _ = fold_iteration_outcome(state, sig, passed=False)
        self.assertEqual(json.loads(json.dumps(state)), state)

    def test_window_bounds_the_stored_history(self):
        state = fresh_loop_state()
        for i in range(50):
            state, _, _ = fold_iteration_outcome(state, f"SIG{i}", passed=False, window=6)
        self.assertLessEqual(len(state["recent_signatures"]), 6)

    def test_state_written_before_this_feature_still_loads(self):
        """Old state.json files have no `recent_signatures` key."""
        legacy = {"iteration": 3, "last_signature": "A", "repeat_count": 1}
        state, _, stalled = fold_iteration_outcome(legacy, "A", passed=False)
        self.assertTrue(stalled)               # consecutive repeat still detected
        self.assertEqual(state["recent_signatures"], ["A"])


if __name__ == "__main__":
    unittest.main()
