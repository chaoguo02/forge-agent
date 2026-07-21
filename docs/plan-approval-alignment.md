# Plan: Align Web Plan Approval with CLI PlanApprovalService

## Context

CLI plan approval supports 5 user actions via `PlanApprovalService`:
- EXECUTE → TRIGGER_BUILD (already in Web as "approve")
- SAVE → COMPLETE_PLAN (missing in Web)
- EDIT → CONTINUE_EDIT (missing in Web)
- REVISE → TRIGGER_REPLAN (already in Web as "reject")
- ABORT → ABORT_SESSION (missing in Web)

Web only has approve/reject. This adds the missing 3 actions.

## Implementation

Batch 1 (backend): approvals.py — 2 new endpoints
Batch 2 (frontend): PlanView.tsx + chatStore.ts — 2 new buttons

### Batch 1: Backend — approvals.py

Add two endpoints:

1. `POST /api/sessions/{id}/save-plan` — save plan without executing
   - Marks revision as "saved"
   - Updates agent_name to "build" (PlanView shows correct state)
   - Returns {saved: true}
   - Does NOT start build thread

2. `POST /api/sessions/{id}/abort-plan` — discard plan
   - Clears plan metadata
   - Marks revision as "aborted"
   - Returns {aborted: true}
