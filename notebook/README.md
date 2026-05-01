---
type: index
description: Notebook root and navigation
---

# Miner's Notebook

A persistent log for a 1st-person mining RPG on a distant planet. The user narrates; this notebook records — no advice, no strategy, just memory.

## Files

| File | Type | Description |
|------|------|-------------|
| `journal.md` | observations | Chronological session entries (append-only) |
| `people.md` | characters | Named NPCs, roles, relationships |
| `locations.md` | locations | Facilities, levels, yards, sectors, exterior zones |
| `todo.md` | quests | Open objectives, blockers, retrieval tasks, story hooks |
| `quests.md` | quests | Unresolved questions, locked doors, unexplained things |
| `resources.md` | items | Ores, materials, key items, tech components |
| `rigs_and_drones.md` | equipment | Drilling rigs, laser drills, cargo drone assignments |
| `deaths.md` | hazards | Death markers, hazards, places to be careful |

## File structure

Each file has YAML frontmatter:
```yaml
---
type: <entity type>
description: <brief description>
---
```

Entities within files use standardized headers:
```markdown
## Entity Name
**Status:** active | open | resolved | unknown
**Location:** where it is
**Related:** [[Link]], [[To]], [[Others]]

- Bullet points with details
```

## Recording rules

- Always preserve user's first-person tone in journal entries
- When a fact gets corrected, update the canonical entry and note the correction in journal
- Cross-reference using `[[wiki-links]]` for entity relationships
- Tag uncertain info as "probable" / "likely" until confirmed in-world
- History is chronological (oldest first, newest at bottom)

## Quick map summary

```
Surface base (outside) — my real home + Climber surface station ✅
   |
   | (Climber elevator)
   |
Massive Cave System
 ├ Level 1 — Habitat (old mining complex hub)
 ├ Level 2 — Site Beta — Rig #2 (kalynite)
 ├ Level 3 — Rig #3 (kaloxite) + pools + unreachable upper area
 ├ Level 4 — Crater bottom — Facility Delta — Rig #5 (meteorite/meteor glass)
 │           Rig #4 nearby + unnamed outpost (gold+kalynite)
 │           Climber elevator current top station
 ├ Level 5 — Facility Epsilon (Climber, secure storage, crew quarters A/B/C, canteen, airlock)
 │           → Airlock exits to "lost world" jungle
 │             ├ Yard with N gate (tangrite) and S gate (unexplored)
 │             ├ NE: Facility Theta (small fenced area near Lambda? — probable)
 │             ├ SE: Facility Lambda (radioactive swamp, damaged reactor)
 │             └ Beyond Theta-fence: Facility Mu (gate now open, needs power cell for O₂ dome)
 └ Level 6 — Facility Omicron (currently inaccessible)
```
