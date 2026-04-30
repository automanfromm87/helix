"""Recovery prompt — invoked when a task fails after the configured retries.

The planner sees the original goal, what's already been completed, the
specific task that failed (with the error), and the remaining queue. It
submits a structured decision via `submit_recovery_decision`:

  * `replan`  — rewrite the remaining tasks to work around the failure
  * `abandon` — accept that the original goal can't be reached, summarize
                what was actually delivered
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

Remaining tasks (would have run after the failed one):
{remaining}

Working language: {language}

Decide:
- "replan"  — rewrite the remaining tasks to either work around the failure
              or take a different path that still serves the original goal.
              The failed task is finalized as FAILED — your new tasks come
              AFTER it. Do not repeat work that's already completed.
- "abandon" — the original goal is no longer reachable from this state.
              Summarize what was achieved and explain why we are stopping.

Output: call the `submit_recovery_decision` tool with `decision`,
`message` (in the working language), and the `tasks` array (empty when
abandoning).
"""
