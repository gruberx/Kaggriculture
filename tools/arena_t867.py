"""T8.67 arena: animal opening vs shipped defaults.
Not part of the committed test suite."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness, tuning
from kagg.policy.params import DEFAULT_PARAMS
W = os.path.join(os.environ.get("CLAUDE_JOB_DIR", "/tmp"), "tmp", "arena67"); os.makedirs(W, exist_ok=True)
new = tuning.write_candidate_agent(dict(DEFAULT_PARAMS, animal_opening=True, animal_opening_fill_cheaper=False), W)
old = tuning.write_candidate_agent(dict(DEFAULT_PARAMS), W)
blocks = harness.load_seed_blocks()
b = harness.run_block(new, old, list(blocks.tuning_seeds), jobs=None)
print(f"arena new vs old (tuning seeds): {b.wins_a}W/{b.wins_b}L/{b.ties}T win_rate={b.win_rate_a:.2f}")
held = getattr(blocks, "heldout_seeds", None) or getattr(blocks, "held_out_seeds", None)
if held:
    h = harness.run_block(new, old, list(held), jobs=None)
    print(f"arena new vs old (held-out seeds): {h.wins_a}W/{h.wins_b}L/{h.ties}T win_rate={h.win_rate_a:.2f}")
