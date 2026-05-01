"""Recovery prompt — invoked when a task fails after the configured retries.

The planner sees the original goal, what's already been completed, the
specific task that failed (with the error), and the remaining queue. It
submits a structured decision via `submit_recovery_decision`:

  * `replan`  — rewrite the remaining tasks to work around the failure
  * `split`   — replace only the failed task with smaller sub-tasks
  * `skip`    — drop the failed task as optional and continue
  * `abandon` — accept that the original goal can't be reached
"""

RECOVERY_PROMPT = """\
A task in the current plan has failed twice and cannot be retried as-is.
Decide whether the plan can recover or must be abandoned.

Original goal:
{goal}

Already completed (oldest → newest):
{completed}

The task that failed:
- Description: {failed_description}
- Error: {failed_error}

Prior failures in this plan (oldest → newest):
{prior_failures}

Recovery history:
- This is recovery cycle #{cycle_index} (out of a hard cap of {max_cycles}).
- Repeated replans on the same plan rarely succeed; if previous replans
  already tried similar variations and still failed, prefer "abandon" or "skip".

Remaining tasks (would have run after the failed one):
{remaining}

Working language: {language}

Decide ONE of FOUR options:

- "skip"    — the failed task is OPTIONAL (verification, nice-to-have polish,
              visual confirmation) and the rest of the plan can succeed
              without it. Pick this when the core deliverable is already
              done and only an auxiliary check failed. Submit empty `tasks`.
              Examples that should be SKIP:
                * "Verify in browser" failed because dev server won't start,
                  but the file edit it was checking already succeeded
                * "Run optional lint" failed but core build passes
                * "Add a polish animation" failed but main feature works

- "split"   — the failed task was TOO COARSE. Replace ONLY the failed task
              with smaller sub-tasks. Remaining tasks are kept as-is. Pick
              this when decomposing the failed task would unblock progress.
              Submit `tasks` = the replacement sub-tasks (will run before
              the existing remaining tasks).

- "replan"  — the original strategy is fundamentally broken. Replace the
              failed task AND all remaining tasks with a different
              approach. Submit `tasks` = the new ordered list. Don't pick
              this if "skip" or "split" would do — replan is the most
              expensive option.

- "abandon" — the goal can't be reached from here, OR prior recoveries
              already exhausted reasonable alternatives. Submit empty
              `tasks` and explain in `message`.

Heuristics (apply in order):
1. If the failed task only blocks itself and the deliverable is intact → SKIP.
2. If the task description bundles 3+ sub-objectives and one of them blew
   up the rest → SPLIT.
3. If `cycle_index >= max_cycles - 1` AND a similar replan already failed
   in `prior_failures` → ABANDON.
4. Only if 1-3 don't apply, consider REPLAN.

Don't choose "replan" with a list that looks similar to a prior failed
attempt — that's how death spirals start. When in doubt between SKIP and
ABANDON: prefer SKIP if it's plausibly optional; prefer ABANDON if the
failed task was load-bearing.

Output: call the `submit_recovery_decision` tool with `decision`,
`message` (in the working language), and the `tasks` array (use it for
"replan" and "split"; empty for "skip" and "abandon").
"""
