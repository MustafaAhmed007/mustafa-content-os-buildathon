# MUSTAFA CONTENT OS Ω

This folder is the operating system behind creator content. Plain markdown holds the human context, structured profile files hold machine-critical creator data, slash commands run the documented workflows, and one file per carousel comes out the other end. Read this file first in every session, then resolve the active profile before touching any task.

## What lives here

| Path | What it is |
| - | - |
| profiles/active.yaml | Which creator profile is active for this run |
| profiles/<id>/profile.yaml | Profile mode, file map, and authority boundaries |
| profiles/<id>/ | Structured creator data, or a legacy source map |
| systems/ | Reusable policy, design, rubric, and format rules |
| schemas/ | Canonical contracts. Definitions only in this phase |
| systems/carousel-design-system.md | Format, colour, type, shadows, cover and CTA rules, export |
| systems/hook-rubric-20pt.md | Ten criteria, zero to two each. Every hook gets scored against it |
| systems/carousel-types.md | The eight carousel types, when to use each, slide skeletons, CTA style |
| references/ | Study material. Formats can be borrowed, words and artwork cannot |
| content/carousels/ | Output. One markdown file per carousel, status tracked at the top |
| archives/ | Published pieces, moved here 14 days after they go live |

## Profile resolution and load order before any content task

Resolve the creator before reading creator-specific context:

1. Read `profiles/active.yaml`.
2. Read the selected profile's `profile.yaml`.
3. If the mode is `structured`, read the files declared under `files`. If a declared path is `TODO_VERIFY`, stop before attempting to read it.
4. If the mode is `legacy-reference`, read the files declared under `legacy_sources`.
5. If any required structured creator field is `TODO_VERIFY`, stop before writing creator-specific claims and ask for the missing facts.

The current active profile is the `manthan` legacy-reference profile. Its source map intentionally resolves to the original root context files, so existing behavior remains available during the migration.

Then load the system files the task needs. Carousel work always adds `systems/carousel-design-system.md`, `systems/hook-rubric-20pt.md` and `systems/carousel-types.md`. Never skip a file because the task looks small. The profile is the creator context, the command is just the trigger.

## Voice

All copy follows systems/brand-voice.md. The rules that slip most often are repeated here so they cannot be missed:

- First person, present tense, one idea per sentence. Sounds like me talking to one person.
- Specific beats impressive. Name the tool, the file, the command, the result, when the active profile authorizes it.
- Never the "no X, no Y, no Z" list. Never a three-word dramatic fragment. Never a "here is why this matters" bridge. Tell it straight.
- No em dashes. Commas and full stops do the work.
- No emojis in slide copy. No hashtags anywhere.

## Slash commands

| Command | Input | What it does | Output |
| - | - | - | - |
| /carousel <core idea> | One sentence describing the idea | Resolves the active profile, loads the system files, picks the type, decides structure, writes three cover hooks and scores them, builds every slide in the active profile's voice with pattern interrupts, ends with the matching CTA, stops for approval | content/carousels/YYYY-MM-DD-<slug>.md with status draft |
| /hooks <idea> | One sentence | Writes ten hooks, scores each against the rubric, returns the top three with the score table | Printed in the session, nothing written |
| /schedule <file> | Path to an approved carousel file | Resolves the active profile, lints the copy, renders slides through the design system, picks the next slot from the active profile's strategy, hands it to a configured scheduler, and writes the confirmation back into the file | Same file with status scheduled |

Commands live in .claude/commands/. One command per repeatable job. If a job is done twice by hand, it becomes a command.

## Profile-driven creator data

- Handles, names, links, colors, products, offers, prices, audiences, calendars, and proof sources come from the active profile.
- Generic instructions must not contain a creator's identity or business facts.
- The legacy Manthan profile may continue to source those facts from the original root files until a later migration.

## Hard rules

1. Facts come from the authoritative files declared by the active profile. A number that is not in the active profile's declared data source does not get written.
2. Never reproduce another creator's script, list, artwork or layout. A format is fair game, the words are not.
3. Every idea passes the net new value filter in the active profile's strategy source before a single slide is written. Fail one gate, stop and say so.
4. Every cover hook is scored against systems/hook-rubric-20pt.md. Below 17 does not start the build.
5. One CTA per piece, one keyword per piece, keyword in curly double quotes. Pull the offer and account identity from the active profile, never improvise one.
6. Stop for approval before scheduling. No exceptions, no auto-publish.
7. Every carousel is 1080 x 1350 per slide and exports at 4x.
8. One carousel per run. Finish it, get approval, then start the next.
9. Do not edit the context files during a content run. If something looks stale, flag it at the end of the output, do not fix it silently.
10. Nothing in this folder, and nothing it produces, mentions the tooling behind it. The output is mine.

## Session start checklist

- Read this file.
- Resolve `profiles/active.yaml` and its profile manifest.
- Read the creator files or legacy sources declared by that manifest.
- Check content/carousels/ for anything with status draft or approved that is waiting on me.
- Then, and only then, take the task.
