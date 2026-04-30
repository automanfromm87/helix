"""Domain-wide constants.

Anything hard-coded in multiple places that's part of the agent/sandbox
contract belongs here so a value change is one edit, not a grep-and-pray.
"""

# Where project-level attachments are mirrored inside the sandbox container,
# and where the workspace surveyor scans for code context. The path lives
# inside the sandbox image; backend code only ever passes it through to the
# sandbox API, so it's a pure protocol value.
SANDBOX_PROJECT_DIR = "/home/ubuntu/project"
