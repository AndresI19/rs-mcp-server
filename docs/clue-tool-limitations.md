# `solve_clue` coverage investigation

**Branch:** `clue-tool-investigation` · **Method:** drove `solve_clue` against a real
example of every step type the wiki documents (`Treasure Trails/Guide/*` subpages),
sourcing handled-format examples from the tool's own index. Reproduction script:
`scratch_probe_clues.py` (not part of the test suite — hits the live wiki).

## TL;DR

The tool indexes **4 of ~10 OSRS** and **3 of ~13 RS3** documented clue step types.
It solves the four text formats it knows (anagram, cryptic, emote, cipher) and returns
a generic "No matching clue found" for **everything else** — including step types that
are pure text and fully indexable today.

## What the tool indexes

`_PAGES` hard-codes four guide pages per game and builds one flat index from them:

| Format | OSRS | RS3 |
|--------|------|-----|
| anagram | ✅ | ✅ |
| cryptic | ✅ | ✅ |
| emote | ✅ | ✅ |
| cipher | ✅ | ✅ (no RS3 dataset) |

Empirically all four solve correctly on both games (e.g. OSRS anagram `AN EARL`,
cipher `BMJ UIF LFCBC TFMMFS`, RS3 cryptic, emote — all return rendered solutions).

## What it can't do (every example returned **NO MATCH**)

The wiki documents these additional step types, none of which the tool indexes:

### Tier 1 — Addressable now, same parser pattern (highest ROI)
| Step type | Games | Wiki shape | Notes |
|-----------|-------|-----------|-------|
| **Challenge scrolls** | OSRS (med/hard/elite) | **one `NPC \| Question \| Answer` wikitable** | Verified: rows like `Ironman tutor \| How many snakeskins… \| 666`. This is the single biggest gap — challenge scrolls are a *sub-step inside* medium+ clues the tool silently can't help with. Parseable with the existing `_CluesParser` approach almost verbatim. |

### Tier 2 — Addressable with more parsing work
| Step type | Games | Wiki shape | Notes |
|-----------|-------|-----------|-------|
| **Coordinates** | both | 167 per-coordinate tables/anchors | coordinate → dig location + route. Data is all text, but spread across many small sections rather than one table. Common clue type; worth the effort. |
| **Simple clues** | RS3 | text steps | "Speak to the bartender of the Rusty Anchor…" — plain text lookups. |

### Tier 3 — Recognizable, but no single text "answer"
`Hot/cold` (OSRS), `Compass` (RS3), `Scan` (RS3). These depend on in-game feedback
(a proximity device, a direction arrow, a scanner). Confirmed non-tabular — the RS3
Compass page has **0 wikitables**. The tool can't *solve* these, but it could *detect*
the type and return the relevant guide + how the mechanic works.

### Tier 4 — Inherently visual / interactive (can't be solved from text)
`Maps` (hand-drawn image), `Puzzle boxes`, `Light boxes` (OSRS), `Celtic knots`,
`Lockboxes`, `Towers` (RS3). No fixed text query exists. Best achievable: identify the
type and link the guide / solver image.

## Recommendations to increase capacity

1. **Add a `challenge` format (Tier 1).** Index the Challenge scrolls page into
   `{question, answer, npc, tier}` entries; match on the question text. Small, high-value,
   reuses the existing parser. *Start here.*
2. **Add `coordinate` (Tier 2).** Normalise the coordinate query (degrees/minutes) and
   map to location + route. More parsing, but coordinate clues are frequent.
3. **Cross-cutting: type-aware fallback.** Today any miss returns one generic message.
   Detect the likely step type from the query (a `NN degrees …` pattern → coordinate; a
   trailing `?` → challenge; "map"/"puzzle"/"compass"/"scan" keywords → that type) and
   route to the specific guide with a one-line explanation of the mechanic. This turns
   every Tier 3/4 dead-end into useful guidance without claiming to "solve" it.
4. **Surface supported scope in the tool description** so the agent knows what it can and
   can't attempt (avoids confidently feeding it a map/puzzle clue).

## Bottom line

The tool works well within its 4-format scope. The fastest capacity win is **challenge
scrolls** (one table, existing parser). The most useful structural change is the
**type-aware fallback**, which makes the tool helpful across *all* step types even where
a single answer isn't possible.
