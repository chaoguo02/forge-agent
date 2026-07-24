# Plan: make Chat own plan/diff workflow and make Review useful

## Goal

Align the UI with the user's mental model:

- `Plan` and pending file diffs are session workflow artifacts, so they should live in Chat/session context rather than as standalone top-level pages.
- `Review` should become a more useful quality/readiness surface, not just a pending diff approval queue.

## Current state

- `web/src/App.tsx` still has top-level `Plan` and `Reviews` tabs.
- `ChatView` already has some plan handling in-session:
  - plan mode progress indicator
  - `plan_ready` timeline event rendering through `WsEventBlock`
  - approval/reject controls in the composer footer when `planApproval.isWaiting`
- `WsEventBlock` currently tells users to review the plan "below or in the Plan tab", which reinforces the redundant Plan page.
- `DiffReviewView` is currently a global pending diff queue backed by `/api/diffs/pending`.
- Session-specific diffs are already surfaced in `SessionStatsDrawer` as counts, but not as a first-class Chat/session workflow UI.

## Product direction

Top-level navigation should move toward:

`Chat | Review | Stats | Memory | Trace`

Where:

- `Chat` owns the live work loop:
  - planning state
  - plan approval/rejection
  - tool approvals
  - inline diff/tool output cards
  - final responses and verification output
- `Review` becomes a quality/readiness dashboard:
  - selected session health
  - execution summary
  - verification signals inferred from session output/events
  - changed file/diff summary
  - unresolved pending decisions
  - global pending queue as a secondary section, not the whole page

## Implementation steps

1. Remove top-level `Plan`
   - In `web/src/App.tsx`, remove the `PlanView` import.
   - Remove `{ key: "plan", label: "Plan" }` from `TABS`.
   - Remove the `plan` icon branch.
   - Remove the `activeView === "plan"` render branch.
   - Leave `PlanView.tsx` and `PlansView.tsx` files in place for now to avoid a larger deletion/refactor in this pass.

2. Make Chat's plan UI self-contained
   - Update `WsEventBlock` copy for `plan_ready` so it no longer references the Plan tab.
   - Keep plan approval controls in Chat composer footer.
   - Optionally make the `plan_ready` timeline block copy more explicit: the plan can be reviewed inline and approved/rejected from the composer area.

3. Redesign `DiffReviewView` into a useful Review page
   - Keep the component name for a smaller code diff, but change the UI concept from "pending diffs only" to "Review dashboard".
   - Load current `activeId` session stats/steps/diffs using existing APIs:
     - `getSessionStats(activeId)`
     - `getSessionSteps(activeId)`
     - `getSessionDiffs(activeId)`
   - Continue loading `/api/diffs/pending` as a secondary queue.
   - Add a hero that explains the real purpose: quality, verification, and change readiness.
   - Add cards for:
     - Session readiness / status
     - Verification signals from recent tool steps and message/event text
     - Changed files / diff counts for the active session
     - Pending decisions, including current session pending diffs and global pending diffs
   - Keep approve/reject for pending diffs, but place it under a secondary "Pending change decisions" section.

4. Update tests
   - Update tab navigation e2e to no longer click top-level Plan.
   - Ensure it verifies Chat and Review still render.
   - Existing plan approval tests that explicitly go to `Plan` will need to be rewritten or skipped/repointed to Chat, because plan approval now belongs in Chat.

5. Verification
   - Run `npm run build` in `web`.
   - Run relevant Playwright specs:
     - `e2e/batch4.spec.ts`
     - `e2e/phase17-18-unification.spec.ts`

## Non-goals for this pass

- Delete backend plan or diff APIs.
- Remove `PlanView.tsx` / `PlansView.tsx` completely.
- Build a full static analyzer/code-review engine.
- Change how diffs are created or applied on the backend.

This pass is an information-architecture and usefulness improvement, not a backend behavior rewrite.
