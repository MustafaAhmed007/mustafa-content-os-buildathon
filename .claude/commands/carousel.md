# /carousel

Build one complete Instagram carousel from a single core idea, in my voice, through my system, then stop for approval.

Arguments: $ARGUMENTS

Supported syntax:

- `/carousel <idea>` selects `active_profile` for this run.
- `/carousel --profile <id> <idea>` selects a declared profile for this run only.

Only a leading `--profile <id>` is an option. Treat the remaining text as the core idea. Never edit `profiles/active.yaml` or activate a profile as a side effect.

If $ARGUMENTS is empty, ask for the core idea in one line and stop. Do not guess a topic.

## 0. Resolve the selected profile and load context

1. Read `profiles/active.yaml`.
2. Run `python3 -B scripts/carousel_workflow.py prepare -- "$ARGUMENTS"` with the actual argument string safely quoted. It returns the selected `profile`, original `idea`, manifest, declared source paths, and a deterministic `readiness` report. This defaults to private drafting for Instagram. For an explicitly public build, use `prepare --mode public --platform instagram -- "$ARGUMENTS"` before writing copy. A nonzero exit or `FAIL` stops the run. Do not generate on a hard readiness blocker, including an explicitly selected testing profile.
3. Read the returned profile's `profile.yaml`.
4. Read the resolved creator-specific sources returned by preparation, or the legacy sources declared under `legacy_sources`. Never attempt to read an unresolved path. A required unresolved source blocks the run; an optional unresolved source supplies no facts or authorization.
5. Read `systems/brand-voice.md`.
6. Read `systems/carousel-design-system.md`.
7. Read `systems/carousel-types.md`.
8. Read `systems/hook-rubric-20pt.md`.

The selected profile is the only source for creator identity, audience, business, offers, channels, strategy, voice, brand, calendar, and creator-specific data. An override changes this run's context, not global activation. Never fall back to another creator's profile. If the selected structured profile is incomplete or a required value is `TODO_VERIFY`, stop before writing creator-specific content and report the missing field.

### Deterministic required-field contract

`readiness.checks` records `profile`, `check`, `path`, `status` (`PASS`/`FAIL`), `reason`, `blocking`, and its draft/public/CTA scope. `draft_ready`, `public_ready`, and `cta_ready` are separate decisions. Only blockers for the requested mode make preparation fail. Readiness errors use `READINESS_BLOCKED` and `phase: readiness`, not content-validation errors.

For a structured profile:

- Drafting requires readable identity, voice, strategy, and design-system sources; matching manifest/domain `profile_id`; and manifest status `active` or `draft`.
- Identity requires `identity.name`, `professional_positioning.primary_title`, `professional_positioning.positioning_statement`, and resolved ready statuses on both records. Voice requires a ready `specification_status` and nonempty resolved `tone` and `writing_rules` lists.
- Strategy requires ready `status`, `active_selection_status`, and `novelty_gate.status`. `novelty_gate.configured_rules` must map each of `non_obvious`, `one_of_none`, and `highly_tactical` to resolved rule text or a nonempty list of rule text. `active_pillar_ids` must select existing named active/verified pillar records. A selected content pillar must match an active ID or exact name. Ready status values are `active`, `verified`, `ready`, or `configured`, except pillar records require `active`/`verified`.
- Public readiness additionally requires an active manifest, public identity/positioning permissions, and exactly one channel record matching the selected platform. Its `handle_or_url`, `content_types` (explicitly including `carousel` or `carousels`), ready `status`, `publishable: true`, `public_use: public`, and `verification_status: verified` must be configured. An unavailable/unconfigured account blocks public use and never produces a fallback handle.
- CTA readiness requires resolved `cta_policy.primary_mechanic`, `keyword`, `delivery_asset`, HTTP(S) `destination_url`, `offer_selection`, and an independently configured `conversion_path`, plus explicit local/inherited public permission. The selected offer must exist exactly once and have resolved `name`, `description`, `target_customer`, ready `status`, `publishable: true`, and public permission. Explicit policy status/enabled/publishable flags and selected-record enabled flags must permit use. Supplied content `keyword`/`offer_id` metadata must match that policy. This checks configuration, not the semantics of rendered CTA prose or actual fulfillment.
- Legal identity, location, metrics, testimonials, proof templates, offer pricing/proof, pillar rank, unselected records, writing samples, visual assets, and scheduling/calendar details are outside this text-carousel readiness contract. Unknown optional fields do not become authorized facts or promises.

The legacy-reference contract uses the declared Markdown identity and voice sections, the three explicit novelty rules and content pillars, the selected platform's account table row, the primary offer/destination, CTA mechanic/delivery policy, and current-data keyword inventory. It preserves the established format without synthesizing structured creator data.

If `draft_ready` passes while `public_ready` fails, only a local/private draft is allowed. Report the public blockers. If `cta_ready` fails, omit CTA copy, `cta_mechanics`, keyword/offer metadata, and CTA-slide headline/body, using an empty `cta` field. Private omission is permitted by draft-ready manifest status unless `cta_policy.allow_private_draft_without_cta` explicitly denies or leaves that permission unresolved. This permission never authorizes a CTA. Do not invent a keyword, offer, destination, deliverable, conversion path, account handle, price, calendar slot, or missing visual token. If the requested output needs an unresolved component, stop instead of filling it. Finalization rejects supplied CTA copy when its required configuration is unresolved.

Then run the core idea through the net new value filter in the selected profile's strategy source, including its additional proof/editorial gates. Print one line per gate (non-obvious, one of none, highly tactical) with pass or fail. If any gate fails, stop and say which one and why. Do not build a carousel that fails the filter.

Before generation, write a temporary JSON strategy checkpoint containing `profile`, `idea`, `source` (the returned strategy path), `source_sha256` (the returned strategy checksum), and `gates`. The three gate keys are `non_obvious`, `one_of_none`, and `highly_tactical`. Each is an object with a boolean `pass` and a specific `reason`. These are your judgments against the source, not automatically inferred originality scores. Run:

```bash
python3 -B scripts/carousel_workflow.py gate "<checkpoint.json>"
```

Any failure stops before generation. All three must explicitly pass. For a public build use `gate "<checkpoint.json>" --mode public --platform instagram`. Gate checks re-read authoritative readiness configuration, so an all-true checkpoint cannot override unresolved novelty rules or active selection. The selected strategy source/checksum is still required. The checkpoint is rechecked at finalization and embedded in the Markdown artifact for later revalidation.

## 1. Pick the carousel type

Match the core idea against the type table in systems/carousel-types.md. Pick exactly one. Print:

- Type chosen
- Why this type and not the runner-up (one sentence each)
- Which day in the weekly calendar in the selected profile's strategy source this type belongs to

For a structured profile, select an explicitly active pillar ID or exact name and rerun preparation with `--pillar "<selection>"` before writing hooks or slides, retaining the requested mode/platform. Do not guess a pillar or calendar slot; unresolved calendar fields remain omitted from a private text draft.

## 2. Decide the slide structure

Take the skeleton for the chosen type and fill in the slide count. Rules:

- Total slides between 8 and 12 including cover and CTA. Prompt lists may go longer when the count is the hook.
- Slide 1 is always the cover. The last slide is always the CTA.
- Print a one-line plan per slide: slide number, job of the slide, the one thing it must land.
- Mark pattern interrupt slots now, before writing. Place them at roughly one third and two thirds through the body slides. Never on the cover, never on the CTA, never on two adjacent slides. The two interrupts must be different types (see step 4).

## 3. Write three cover hooks and score them

Write three cover hook variations for the core idea. Each hook is at most 12 words and must break across two lines cleanly at 72px. Use different angles: one outcome-led, one mechanism-led, one contrarian or specific-number-led.

Score every hook against all ten criteria in systems/hook-rubric-20pt.md. Print the score table with criteria as rows and hooks as columns, plus a total row. Then:

- 17 to 20: ship it.
- 14 to 16: rewrite the two lowest-scoring criteria, rescore once, print the new table.
- 13 or below: discard and write a fresh set of three.

State the winner and the single sentence that explains why it won. The winner becomes the slide 1 headline word for word.

## 4. Build the carousel slide by slide

Write every slide in my voice per systems/brand-voice.md. For each slide output:

- Headline (max 8 words, this is the display text)
- Body (max 40 words, one idea, reads at scroll speed)
- Visual note (what is on the canvas, using the design family and colours from systems/carousel-design-system.md, with real project names, real file names and real tool names)
- Pattern interrupt marker on the two slots chosen in step 2, with its type

Pattern interrupt types, pick two different ones:

- Format switch: a real screenshot, a terminal, a file tree or a device mockup replaces the text layout.
- Direct question: one question to the reader, no answer on the slide.
- Contrarian line: one sentence that pushes against what the previous slides implied.
- Split slide: left half versus right half, two states side by side.
- Zoom: one detail from an earlier slide blown up to fill the frame.

Retention rules while writing:

- Every body slide ends on something that pulls to the next slide. A half-finished thought, a number without its meaning yet, a step that needs the next step.
- Numbers and factual results only from the selected profile's declared data sources. Tools, files, products, channels and offers only from the selected profile.
- For a registry-backed profile, select existing claim IDs while writing factual/profile-specific copy. Read `knowledge/claims.yaml` and `knowledge/evidence.yaml` and verify their scope matches the selected profile. Populate top-level `claims` for the whole item and each slide's `claim_refs` where it uses those facts. Every factual/profile-specific statement needs a suitable existing claim ID. If none exists, stop and report the unsupported statement. Never manufacture a claim, weaken its publication rule, or extract claims from prose automatically.
- Bind registry-backed assertions to the actual copy using the applicability contract below. A valid reference is not permission to use it for a different assertion. Identity and positioning never support hours saved, percentages, performance, revenue, deployments, customers, adoption, or outcomes.
- A legacy-reference profile continues to use its declared original sources. It has no registered claim/evidence coverage in this phase. Use `claims: []` and empty slide references, explicitly report that limitation, and review facts against the original sources. Do not borrow another profile's IDs or create legacy claim/evidence records.
- Banned: the "no X, no Y, no Z" list, three-word dramatic fragments, "here is why this matters" bridges, em dashes, emojis, hashtags, any mention of another creator's content.
- Never mislabel a selected profile offer. Never say link in bio.

## 5. End with the CTA that matches the content type

Open the selected profile's offers source, find the row that matches this content type, and use its primary plug and keyword style. Resolve the account handle from the selected profile's channels source. The CTA slide always contains, in this order:

For structured profiles, first require `cta_ready` and an explicitly configured account for the selected platform. Use the configured offer and CTA mechanic rather than importing the legacy DM mechanic below. A private body-only draft with unresolved CTA configuration omits this section. If the selected account identifier is unresolved, do not write a follow/account line. Every destination, keyword, delivery asset, and conversion path comes from the authorized policy. Write creative CTA wording and classify its mechanics separately using the contract in step 7.

1. The selected profile's approved keyword in curly double quotes
2. follow for more.
3. The selected profile's approved handle

The caption CTA line reads: comment "KEYWORD" and I will send it straight to your DMs. State the value first, then the mechanic. One keyword, one offer, never stacked.

## 6. Write the caption

500 words or more, in the selected profile's approved voice, with no hashtags. Open with the hook restated in a new sentence, then tell the full story of the carousel with more detail than the slides had room for, then the keyword CTA, then one relevant offer line from the selected profile. Do not invent an offer or price.

For a private body-only draft whose CTA configuration is unresolved, omit the keyword CTA and offer line. Preserve that limitation in the readiness report and build notes.

## 7. Write the structured draft, validate, and stop

Keep `content/carousels/YYYY-MM-DD-<slug>.md` as the human-facing output. The content contract also needs a canonical structured companion at the same stem with `.yaml`. Do not migrate or rewrite existing examples.

Write the structured companion against `schemas/content-item.schema.json`, with at least:

- `schema_version: "1.0"`
- `content_id`: the dated filename stem
- `profile`: the explicit selected profile ID
- `status: draft`
- `platform: instagram`
- `content_type`: the chosen carousel type
- `pillar`, `angle`, and `idea` (the exact original idea from profile resolution)
- `hook`: the winning hook
- `slides`: every slide with `number`, `role`, `headline`, `body`, `visual_note`, and explicit `claim_refs` where required
- `caption`, `cta`, and top-level `claims`
- `keyword` and `offer_id` when supplied by the selected profile
- `cta_mechanics` for a structured profile's supplied CTA, using the authorization contract below

### Structured claim applicability

For registry-backed content, add an `assertions` array. Each assertion records:

- `assertion_id`: unique kebab-case ID.
- `target`: an exact copy pointer, `/hook`, `/caption`, `/cta`, or `/slides/<zero-based-index>/headline`, `/body`, or `/visual_note`.
- `text`: the exact target text. For a portion of mixed copy, add `span: {start: <inclusive>, end: <exclusive>}` using character offsets and bind `text` to that exact slice.
- `assertion_type`: `identity`, `positioning`, `repository_existence`, `project_existence`, `quantitative_result`, `operational_performance`, or `externally_attributed` for factual assertions.
- `subject` and assertion-local `claim_refs`: explicit support for this assertion. Top-level/slide reference inventories do not automatically support every assertion.
- Optional assertion-local `evidence_refs`, `public_usage`, `basis`, `temporal_scope`, and `attribution` when applicable. Content cannot change verification classifications or override registry public-use permissions.

Every public copy field must be fully covered by bound assertions, except an exact supported identity/positioning literal from its attached claims. Uncovered text and `unknown` public assertions fail closed. `non_factual` with empty claim references explicitly declares procedural/non-factual copy; it cannot carry factual references, evidence, or measurement metadata. This declaration is an author classification, not proof that arbitrary prose is non-factual. Never mislabel a factual result to bypass support checks. Private unclassified drafting remains possible; typed factual assertions are still checked.

The backward-compatible claim contract adds optional authoritative `applicability` metadata: `assertion_types`, optional approved `statements`, scoped `quantitative`, `temporal_scope`, and `attribution`. It can only narrow the underlying `claim_type`, never turn an identity claim into a result claim. Existing identity/positioning records retain narrow exact-statement/literal compatibility. Existing profile repository observations support only historical repository existence, not implementation, ownership/control, deployment, current availability, adoption, or results. Do not edit registries during generation to create support.

Quantitative assertions require `quantitative: {metric, value, unit, period}`. Supported metric labels are `time_saved`, `cost_reduction`, `revenue`, `performance`, `latency`, `growth`, `conversion`, `adoption`, `customer_result`, and `benchmark`. Values must be finite numbers, with resolved scope and exact agreement with authoritative claim metadata. Result/performance assertions require `metric_claim` or `result_claim` support. External attribution requires a scoped `testimonial_claim` and matching attribution.

Result/performance/attribution support requires verified claim-owned evidence, matching subject and an intact structured captured payload containing `subject` and the claim's exact `statement`, plus matching `quantitative` or `attribution` where applicable. Accepted result verification classes are `verified`, `first_party_verified`, and `third_party_verified`; self-reporting, source-only observations, screenshots/proof signals, or visual-only material are not promoted. Every attached claim must support the assertion, and direct evidence references cannot replace missing claim-owned support. Applicable evidence types are metric/first-party/third-party/document for results and testimonial/third-party for attribution.

Statements must match the claim's exact registered text, an explicitly approved statement in its authoritative applicability metadata, or its narrowly scoped captured identity/positioning literal. Do not invent paraphrase authorization, new claims, or evidence. This is deterministic scope/literal checking, not natural-language truth detection or proof of source authenticity.

Legacy-reference finalization keeps its declared-source compatibility coverage without claiming registered applicability verification. Explicit assertions, when supplied, still undergo applicability checks. Any applicability failure produces FAIL with `continue: false`, prevents export, and retains the existing terminal failure record.

### Structured CTA authorization

Keep `cta` as creative copy. For a structured profile's CTA, add `cta_mechanics` with these required, resolved string fields:

| Content field | Authoritative configuration |
| - | - |
| `cta_type` | `cta_policy.primary_mechanic` |
| `keyword` | `cta_policy.keyword` |
| `offer_id` | `cta_policy.offer_selection`, selecting exactly one offer |
| `destination` | `cta_policy.destination_url`, an explicit HTTP(S) URL |
| `delivery_asset` | `cta_policy.delivery_asset` |
| `conversion_path` | `cta_policy.conversion_path`, independently configured |
| `account` | Selected channel's `handle_or_url`, selected by content `platform` |

All mechanics must exactly match the selected profile's declared sources. Existing top-level `keyword`/`offer_id`, when present, must agree. The selected offer and channel must be available, publishable with true boolean flags, and permitted for public use. The channel must be verified and explicitly support carousels. A local permission restriction overrides inherited offer permission; an explicit disabled flag cannot be overridden by a ready status. Do not infer a conversion path from the CTA type, borrow another account, or use a claim/evidence reference as mechanics authorization.

The optional offer-policy fields `enabled`, `publishable`, `status`, and `public_use` can restrict CTA use; `allow_private_draft_without_cta` controls private omission. Boolean permissions require actual booleans. Missing, null, empty, unresolved, `TODO_VERIFY`, unknown, inferred, model-generated, disabled, or unavailable components do not authorize use, even if content repeats the same sentinel. Generated `authorized`, status, permission, or override fields in `cta_mechanics` are forbidden.

Wording may vary freely while retaining the authorized mechanics and the assertion/copy bindings required above. The authorizer checks explicit metadata, not the truth or semantic consistency of prose, destination availability, or actual fulfillment. Never use creative wording to promise different mechanics. If the content contains a CTA but lacks its classified mechanics, validation fails. The schema addition is optional for backward compatibility; public/export-ready structured carousels still require authorization. Private body-only omission reports `omitted: true`, `authorized: false`; non-carousel content with no CTA receives no mechanics authorization.

`cta_authorization` is a deterministic read-only report with `valid`, `result`, `continue`, `authorized`, `omitted`, `required`, `coverage`, per-component `checks` (`component`, `path`, `status`, `reason`), and structured `errors`. Authorization failures use `CTA_UNAUTHORIZED` and `phase: cta_authorization`, stop export, and remain terminal for the artifact. An inconsistent or malformed authorization response cannot grant continuation.

Legacy-reference content retains declared-source compatibility and reports `coverage: legacy declared-source compatibility; rendered mechanics are not structurally authorized`, with `authorized: false`. Its established source/readiness checks still apply. Do not attach newly invented structured mechanics to a legacy profile or describe legacy PASS as structured authorization. The report and exported validation metadata preserve this limitation.

Encode pattern interrupt markers in `visual_note`; do not add unsupported schema fields. Write temporary Markdown build notes containing the calendar day, design family, selected offer's exact label and supplied price, filter commentary, hook score table, slide plan, and open questions. For legacy sources without an offer ID, preserve the original `| offer | <approved label/price> |` metadata row in those notes; do not invent a machine ID. Copy lives in the structured companion, not independently edited notes.

Run:

```bash
python3 -B scripts/carousel_workflow.py finalize "content/carousels/YYYY-MM-DD-<slug>.yaml" --strategy "<checkpoint.json>" --notes "<build-notes.md>" --status draft
```

The workflow order is profile/readiness, strategy, generation, claim applicability, CTA authorization, final validation decision, then export. Finalization first rechecks readiness for the artifact's explicit platform, selected pillar, CTA usage, and requested status. A readiness failure stops before `scripts/validate_content.py`, leaves `validation: null`, and creates no successful export. Once readiness passes, the existing validator runs on a staged structured artifact, checks applicability before CTA authorization, and returns its final decision. The finalizer independently re-reads CTA authorization at the export boundary; a validator PASS cannot override changed or unauthorized mechanics. Draft/review uses internal validation; approved/public uses public-facing validation. The narrow `expected_profile`/`--profile` scope parameter keeps both registries and content aligned without changing validation rules. Registry-backed profiles use the authoritative registries. Legacy profiles use temporary empty scoped compatibility registries: this is schema/reference validation, not registered proof verification. Nonempty unresolved legacy references fail. Draft Markdown distinguishes draft, public, and CTA readiness from content-reference validation, and records CTA authorization coverage.

The only authoritative success is `valid: true` AND `result: "PASS"` AND an empty `errors` list, with `continue: true` from finalization. A PASS phrase in notes, old output, or a nested diagnostic never overrides the controller result.

On authoritative PASS, the helper writes the Markdown copy from the structured companion, embeds the strategy checkpoint/build notes, and records validation coverage. Any other result, exception, or nonzero exit terminates this invocation: print the failure reasons and return control to the user immediately. Do not edit the canonical YAML or checkpoint, retry finalization, change validation mode, or continue to approval/export after failure. There are zero automatic validation correction attempts and no recursive command calls.

The dated YAML stem is the deterministic artifact identity: `content_id` must equal that stem. The finalizer preserves the first failure in `<dated-stem>.validation-failure.json`, bound to both `artifact_id` and the repository-relative artifact path. It also keeps a durable transaction journal in `content/carousels/.workflow-state/<dated-stem>.json` and serializes access with an artifact lock. A `RUNNING` journal from an interrupted process is recovered as terminal failure, and a `FAIL` journal blocks later attempts even if the visible failure report is deleted or a PASS Markdown view is restored. That terminal record blocks subsequent finalization for the same artifact, including a new CLI process, edited YAML, or draft-mode retry. Reusing the failed `content_id` under another filename fails closed. A new intentional run needs a new dated artifact identity and matching `content_id`; it cannot silently reuse the rejected identity. Do not remove/edit the failure record or journal, or rename the artifact to evade the failed run. Restart authorization is outside this phase; a later human-requested correction is a separate workflow, not an automatic retry of this failed invocation.

Before validation, the finalizer snapshots the canonical YAML, active-profile manifest, declared profile/system sources, claim and evidence registries, and content schema. It compares those fingerprints after validation and again immediately before export. Any authoritative input change produces `VALIDATION_INPUT_CHANGED`, preserves a terminal failure report, and prevents export. The machine-readable result reports `artifact_id`, `artifact_path`, and `validation_inputs`; human-readable notes never override those fields.

A rejected first attempt does not export a Markdown carousel. Existing linked output is marked FAIL and demoted to draft; an explicit kill request records killed instead, still with no ready state. Do not describe failed content as ready, approved, or public.

Print the file path and the winning hook, then stop. Do not schedule. Wait for one of these replies:

- approved: first run `python3 -B scripts/carousel_workflow.py finalize "<structured-companion.yaml>" --status approved`. The embedded checkpoint is rechecked and public-facing validation must PASS before either artifact becomes approved. Only then may the existing `/schedule` handoff continue for the default legacy profile when the artifact profile still matches `active_profile`. An explicitly selected inactive profile is never handed to the active-profile scheduler. The helper itself does not schedule or publish.
- change <notes>: edit the structured companion, rescore the hook if it changed, refresh the checkpoint if the idea or strategy source changed, and rerun finalization with `--status draft`. Stop again. Do not edit the Markdown copy independently of its structured source.
- kill: finalize with `--status killed`, leave both files in place for the record, and stop.
