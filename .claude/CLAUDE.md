# graphify
- **graphify** (`.claude/skills/graphify/SKILL.md`) - any input to knowledge graph. Trigger: `/graphify`
When the user types `/graphify`, invoke the Skill tool with `skill: "graphify"` before doing anything else.

# Session Management — MANDATORY RULES

## Start of Every Session
1. Read `SESSION.md` before doing anything else to restore context from the previous session.
2. Read `docs/MODULE_REGISTRY.md` to know the current module landscape.

## After Every Action (file change, research, decision)
Update `SESSION.md`:
- Add an entry under "What Was Done This Session" with today's date and a brief description
- Add/update rows in the "Recent File Changes" table for any files touched
- Update "Open Tasks" to reflect remaining work

## Before Modifying Any File
1. Check `docs/MODULE_REGISTRY.md` — find the module's row and open its `docs/modules/<name>.md`
2. Review the **Used By** (dependents) list — assess if the change breaks any consumer
3. If the change affects the public interface or behavior, update the module doc after the change

## When Creating a New File/Module
1. Create `docs/modules/<name>.md` using the template in `docs/MODULE_REGISTRY.md`
2. Add a row to the registry table in `docs/MODULE_REGISTRY.md`
3. Update any modules it depends on: add this new module to their "Used By" section
4. Log the creation in `SESSION.md`

## At End of a Session / Long Task
- Move the current session block to "Session History" in `SESSION.md` with a one-line summary
- Start a new session block with a fresh session ID (format: YYYY-MM-DD-NNN)

# Frontend Spec — MANDATORY

Whenever a feature is added, changed, or removed (new endpoint, new model field, changed response shape, new page, new business rule), you MUST update `docs/FRONTEND_SPEC.md` to reflect the change before committing. This keeps the spec in sync with the implementation so the frontend developer always has accurate information.
