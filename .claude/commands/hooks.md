# /hooks

Generate ten cover hooks for one idea, score every one against the rubric, return the top three.

Idea: $ARGUMENTS

If $ARGUMENTS is empty, ask for the idea in one line and stop.

## 0. Resolve the active profile and load context

1. Read `profiles/active.yaml`.
2. Read the selected profile's `profile.yaml`.
3. Read the creator-specific identity, audience, business, channels, strategy, data, and voice files declared by the profile, or the legacy sources declared by a legacy profile. If any declared structured path is `TODO_VERIFY`, stop before attempting to read it.
4. Read `systems/brand-voice.md`.
5. Read `systems/hook-rubric-20pt.md`.

The active profile is the only source for creator identity, audience, products, tools, metrics, results, and proof language. If a structured profile is incomplete or a value is `TODO_VERIFY`, do not fill the gap from the legacy profile or from general knowledge.

## 1. Write ten hooks

Rules for every hook:

- 12 words maximum. Must break into two clean lines at 72px.
- First person, my voice. Named tools, named files, named products.
- Numbers only from the active profile's declared data source.
- Spread the angles across the ten: outcome-led, mechanism-led, specific-number-led, contrarian, question, before and after, the one mistake, the file or command itself, the cost or time saved, the audience callout.
- Banned: "no X, no Y, no Z", three-word dramatic fragments, em dashes, emojis, another creator's line.

## 2. Score all ten

Score each hook on all ten criteria in systems/hook-rubric-20pt.md, zero to two each. Print one table: hooks as rows, criteria as columns, total as the last column. Sort by total, highest first.

## 3. Return the top three

For each of the top three print:

- The hook, as it would read on the cover, with the line break shown
- Total score
- Its weakest criterion and the one-line fix that would lift it

If none of the ten reaches 17, say so, write a second set of ten from different angles, rescore, and return the top three across both sets.

Nothing is written to disk. To build the carousel, run /carousel with the winning hook's idea.
