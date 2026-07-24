# Plan: unify frontend Plan / Plans entry

## Goal

Remove the confusing top-level distinction between `Plan` and `Plans`. Keep one top-level `Plan` tab and make the page clearly represent the planning area. Since "current plan" is not a useful mental model for the user, avoid that wording in the UI.

## Current state

- `web/src/App.tsx` exposes both `plan` and `plans` as top-level tabs.
- `web/src/components/PlanView.tsx` handles the selected session's plan workflow: generated proposal, approval, save, revision, discard.
- `web/src/components/PlansView.tsx` handles the plan library: list all generated plans, inspect, edit, delete, and open the originating session.
- `web/src/styles.css` already has styles for both plan workflow and plan library.
- Existing e2e tests cover the `Plan` tab and do not appear to require a visible top-level `Plans` tab.

## Proposed UX

Top-level tabs become:

`Chat | Plan | Reviews | Stats | Memory | Trace`

Inside `Plan`, add a small segmented switch:

- `Review plan` — the selected session's generated proposal and approval flow.
- `Plan library` — all saved/generated plans across sessions.

Use wording like `Review plan` / `Plan library`, not `Current Plan`, because the latter is unclear.

## Implementation steps

1. Update `web/src/App.tsx`
   - Remove the `plans` entry from `TABS`.
   - Remove the direct `{activeView === "plans" && <PlansView />}` top-level render.
   - Remove the `PlansView` import from `App.tsx`.
   - Keep top-level `Plan` rendering `PlanView`.

2. Update `web/src/components/PlanView.tsx`
   - Import `PlansView`.
   - Add local state for an internal plan subview, defaulting to `"review"`.
   - Render a compact subnav/segmented control near the hero:
     - `Review plan`
     - `Plan library`
   - When `review` is selected, render the existing plan workflow unchanged.
   - When `library` is selected, render `PlansView` in embedded mode.

3. Update `web/src/components/PlansView.tsx`
   - Add an optional prop such as `{ embedded?: boolean }`.
   - In embedded mode:
     - Do not render its own full hero, to avoid nested duplicate plan headers.
     - Keep the catalog/detail library UI, edit/delete/open-session behavior, loading/error/toast/confirm modal.
   - In standalone mode keep existing behavior if other code imports it later.

4. Update `web/src/styles.css`
   - Add styles for the Plan internal subnav, reusing existing tab/segment visual language.
   - Ensure embedded library spacing works within `PlanView`.
   - Keep existing `.plans-*` styles where possible.

5. Update tests if needed
   - Adjust any e2e expectation that assumes a top-level `Plans` tab.
   - Add/modify a lightweight test to verify the Plan tab can switch to `Plan library` and show the library layout.

## Verification

Run the relevant frontend tests after implementation, likely:

- `npm`/Playwright command used by this repo for the web e2e suite, or at minimum the specific tests covering Plan navigation.

If the repo's test command is not immediately clear, inspect `web/package.json` / root `package.json` first and run the narrowest relevant test command.
