# helixcli

Deterministic project scaffolder for the Helix sandbox. See `SPEC.md`
for the design.

## Quick start (host testing)

```bash
# Editable install — re-run after editing source without reinstalling
uv tool install --force --editable /path/to/helixcli

# Scaffold a fresh project
cd /tmp
helixcli init demo
cd demo

# Install deps + start both dev servers
helixcli install
helixcli up                   # http://localhost:5173 + http://localhost:8000
helixcli down

# Generators
helixcli page Login           # frontend page + test + route
helixcli endpoint POST /api/v1/login
helixcli migration init_users
```

## Why

Replaces the LLM's framework-decision turn with a CLI that emits
byte-stable output. See `SPEC.md` §0 for the full premise.
