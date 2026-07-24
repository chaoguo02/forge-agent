# Phase 17 Plan: Frontend Function Pruning and Visual Unification

## Goal

This phase improves the web experience without removing core workflow capability.

The product should keep the important surfaces that users rely on, but become calmer, more readable, and more coherent.

## Product principles already aligned

- Do not randomly delete features
- Keep core workspaces visible
- Make the main work area feel more professional and less crowded
- Reduce visual noise without reducing functionality
- Preserve secondary evidence panels, but make them lighter and more recessive
- Prefer clearer hierarchy, spacing, and card rhythm over adding more chrome

## Core UX decisions already aligned

### Keep as core surfaces

- Chat: current session conversation and execution stream
- Plan: current plans and structured planning output
- Memory: long-term context / knowledge surface
- Trace: execution evidence surface, even if the current content is still growing
- Session sidebar: work queue and session switching
- Session tree: subagent / child-session navigation
- Tool approval: explicit permission workflow

### Keep, but visually de-emphasize

- Stats
- Reviews
- Events
- auxiliary action buttons
- repetitive status labels
- oversized tool and event cards
- side evidence blocks that compete with the main conversation

## Design direction

- style: restrained, professional, information-dense but not crowded
- layout: center-first work area, side rails as supporting surfaces
- hierarchy: one dominant content area, secondary evidence stays accessible but quieter
- spacing: more breathing room between semantic groups, less heavy framing
- cards: lighter borders, lighter shadows, less boxiness
- controls: fewer visually loud buttons, but no functional deletion of core controls

## What should stay in the product

1. Chat remains the primary work surface for the selected session
2. Plan remains the structured review surface for plans
3. Memory remains a dedicated long-term context panel
4. Trace remains the evidence / execution surface
5. Sidebar remains the work queue and session switcher
6. Session tree remains the subagent navigation structure
7. Tool approval remains visible and actionable
8. Subagent-related evidence remains available, but should not dominate the main conversation flow

## What should be visually reduced

1. repeated auxiliary status text
2. heavy card framing in the chat stream
3. oversized button clusters
4. low-frequency tabs that compete with the core workflow
5. bulky event and stats presentation
6. duplicated labels that do not help immediate understanding

## Phase 17 scope

The first pass should focus on the highest-yield visual wins:

- unify the main layout and information hierarchy
- lighten the chat stream cards
- make the sidebar feel more like a work queue
- make tool/approval/evidence blocks more compact and collapsible
- give plan, memory, and trace more polished “workbench” styling
- de-emphasize stats / reviews / events without removing them

## Suggested implementation slices

### Batch 1 — layout and card language unification

Goal: make the page feel like one coherent workbench instead of a collection of mismatched panels.

Likely affected areas:

- global page layout
- top-level pane widths and rhythm
- shared card spacing, borders, and title treatment
- shared status/label language

Outcome:

- the app reads as one system, not many unrelated widgets

### Batch 2 — chat stream simplification

Goal: make the main conversation visually lighter and easier to scan.

Likely affected areas:

- message blocks
- tool call/result blocks
- approval cards
- subagent evidence blocks in the main flow

Outcome:

- the main work stream stays information-rich but less oppressive

### Batch 3 — sidebar and queue styling

Goal: make the sidebar behave like a work queue rather than a cluttered information board.

Likely affected areas:

- session list
- active session status
- tree navigation
- batch actions and secondary controls

Outcome:

- sessions are easier to parse at a glance

### Batch 4 — plan, memory, and trace polish

Goal: give the supporting work areas a more deliberate and professional visual identity.

Likely affected areas:

- plan review surface
- memory knowledge surface
- trace evidence surface
- empty states and placeholder states

Outcome:

- the supporting surfaces feel intentional even before they are full

### Batch 5 — secondary surface de-emphasis

Goal: keep the auxiliary views available while reducing their visual competition with core work.

Likely affected areas:

- stats
- reviews
- events
- auxiliary buttons and secondary tabs

Outcome:

- the main workflow stays dominant while the auxiliary surfaces remain accessible

## What is out of scope

- removing core workflows outright
- merging the main work surfaces into a single monolithic page
- redesigning backend functionality for the sake of appearance only
- introducing a totally new design system from scratch
- hiding evidence surfaces that are needed for harness confidence
- changing product semantics just to make the UI look simpler

## Acceptance criteria

- Core surfaces remain present and reachable
- Chat feels lighter without losing information
- Sidebar reads like a work queue instead of a notice board
- Plan, Memory, and Trace feel like first-class work surfaces
- Stats / Reviews / Events remain available but no longer dominate the visual hierarchy
- Tool approvals and subagent evidence remain usable and easier to scan
- The app feels more coherent, calmer, and more professional overall

## Suggested test seam

Use the existing web UI routes / views as the highest seam.

The best external behaviors to verify are:

- whether the core surfaces are still present
- whether the main work area hierarchy is clearer
- whether secondary views remain reachable but less dominant
- whether the app still supports the same workflows after the visual changes

## Notes for implementation

This phase is intentionally conservative about feature deletion.

The main objective is to make the interface feel more deliberate and less noisy while preserving the important surfaces the user explicitly wants to keep.
