# Frontend Function Pruning and Visual Unification

## Problem Statement

From the user's perspective, the web app has too many low-value or low-frequency surfaces competing for attention, and the visual design does not yet feel like one coherent workbench.

The current frontend is usable, but it can feel crowded and inconsistent:

- core workflows are present, but the main work area is visually noisy
- auxiliary views are too visually loud compared with the core surfaces
- some controls and labels repeat too often
- cards, spacing, and status treatments do not yet feel unified
- the app does not yet read as a calm, professional agent workbench

The user does **not** want core functionality removed at random. They want the product to keep the important surfaces, reduce visual noise, and make the interface feel more deliberate and coherent.

## Solution

The frontend should keep all core workflows, but visually reorganize them so the product feels more restrained, professional, and easier to scan.

The main design direction is:

- preserve core surfaces like Chat, Plan, Memory, Trace, sidebar/session navigation, tool approval, and subagent evidence
- de-emphasize lower-frequency surfaces like Stats, Reviews, and Events without deleting them
- make the Chat experience lighter and more readable
- make the Sidebar feel like a clean work queue instead of a notice board
- make Plan, Memory, and Trace feel like first-class workbench areas
- unify card language, spacing, borders, titles, and status labels across the app
- reduce redundant auxiliary information and oversized control clusters

This is a **visual unification and function-pruning** effort, not a feature-removal project.

## User Stories

1. As a developer, I want the core work surfaces to remain available, so that I can still use the product for the same workflows after the visual refresh.
2. As a developer, I want Chat to remain the primary session workspace, so that I can follow the current conversation and execution stream without distraction.
3. As a developer, I want Plan to remain a structured plan review surface, so that I can inspect and approve plans without losing context.
4. As a developer, I want Memory to remain a dedicated long-term context panel, so that I can inspect and manage persistent knowledge.
5. As a developer, I want Trace to remain a dedicated execution evidence surface, so that I can inspect runtime behavior even if the current content is sparse.
6. As a developer, I want the Session sidebar to remain visible, so that I can switch sessions and see the current work queue.
7. As a developer, I want the Session tree to remain available, so that I can navigate subagent and child-session structure when needed.
8. As a developer, I want Tool Approval to remain visible and actionable, so that I can explicitly review tool requests.
9. As a developer, I want auxiliary surfaces like Stats, Reviews, and Events to remain accessible, so that I can inspect diagnostics without losing the functionality.
10. As a developer, I want auxiliary surfaces to be visually de-emphasized, so that they do not compete with the main workflow.
11. As a developer, I want the Chat stream to feel lighter, so that long sessions are easier to scan.
12. As a developer, I want message and tool cards to use a more consistent visual language, so that the main timeline feels like one coherent system.
13. As a developer, I want redundant auxiliary labels to be reduced, so that repeated state text does not clutter the interface.
14. As a developer, I want the Sidebar to feel like a work queue, so that I can quickly identify active sessions and their status.
15. As a developer, I want the active session state to be visually prioritized over metadata, so that I can see the most important session information first.
16. As a developer, I want the Plan workspace to feel like a reviewable proposal area, so that plans read as deliberate and structured.
17. As a developer, I want the Memory workspace to feel like a knowledge surface, so that long-term context looks like something I can search and consult.
18. As a developer, I want the Trace workspace to feel like an evidence surface, so that it looks ready for execution records even when the current content is minimal.
19. As a developer, I want the app to use a restrained, professional visual style, so that it feels like a serious engineering workspace instead of a noisy dashboard.
20. As a developer, I want spacing, borders, titles, and status tags to be consistent, so that the UI feels unified across different panels.
21. As a developer, I want buttons and secondary controls to be visually calmer, so that the primary work is easier to spot.
22. As a developer, I want secondary action areas to stay functional but less visually prominent, so that I can still access them without letting them dominate the page.
23. As a developer, I want the center work area to remain the visual focus, so that the product feels center-first and task-oriented.
24. As a developer, I want side rails to behave as supporting surfaces, so that they help the main workflow instead of competing with it.
25. As a developer, I want tool approval cards to be compact and readable, so that approval decisions feel lighter without losing necessary detail.
26. As a developer, I want subagent-related evidence to remain available but not dominant, so that delegated work stays accessible without hijacking the main conversation.
27. As a developer, I want low-frequency tabs to be visually quieter, so that the navigation hierarchy better reflects usage frequency.
28. As a developer, I want empty states and placeholder states to look intentional, so that incomplete surfaces still feel polished.
29. As a developer, I want the app to feel more coherent after the visual work, so that I can trust it as a long-lived workbench.
30. As a developer, I want the interface to support information-dense workflows without feeling crowded, so that I can work for long sessions without fatigue.
31. As a developer, I want the main workflow to remain unchanged semantically, so that a visual pass does not accidentally change behavior.
32. As a developer, I want the screen to communicate hierarchy at a glance, so that I can tell what matters first, second, and third without reading everything.
33. As a developer, I want repeated status text to be reduced, so that the same state is not announced in five different places.
34. As a developer, I want high-value surfaces to stay easy to reach, so that the product remains practical even after aesthetic simplification.
35. As a developer, I want the page to feel like one system instead of many mismatched widgets, so that the product looks mature and trustworthy.

## Implementation Decisions

- The product will keep the core surfaces: Chat, Plan, Memory, Trace, Session sidebar, Session tree, and Tool Approval.
- Stats, Reviews, and Events will remain accessible but visually de-emphasized.
- The design direction is restrained, professional, information-dense, and not crowded.
- The center work area will remain the visual priority, with side rails acting as supporting surfaces.
- The main first pass will focus on layout and card language unification rather than feature removal.
- Chat will be visually lightened while preserving full content.
- Tool and event presentation in Chat will be compact, with details available on demand rather than always dominating the stream.
- Sidebar presentation will be converted into a clearer work queue with stronger session-state hierarchy.
- Plan, Memory, and Trace will be styled as first-class workbench areas rather than secondary utility pages.
- Auxiliary controls and low-frequency tabs will keep their functionality but lose visual dominance.
- Cards will use lighter borders, lighter shadows, and less boxiness.
- Titles, spacing, and status tags will be normalized across the main surfaces.
- Empty states will be upgraded to look intentional and polished.
- The existing navigation model should be retained, with priority and visual weight adjusted rather than replaced.
- The highest-value visual change is unified layout and card language, because it yields broad improvement without changing behavior.
- The preferred test seam is the existing web UI routes and views, using visible workflow behavior as the external assertion surface.

## Testing Decisions

- Good tests should verify externally visible behavior, not implementation details.
- Good tests should confirm that core surfaces still exist and remain reachable.
- Good tests should confirm that secondary surfaces remain available but are visually less dominant.
- Good tests should confirm that the main work area reads more clearly after the visual changes.
- Good tests should confirm that the same workflows still function after the refactor.
- Good tests should focus on the existing web UI routes and view switching as the highest seam.
- Good tests should verify accessible rendering states, not fragile pixel-by-pixel internals unless there is already a visual regression practice in place.
- Existing prior art in the codebase includes the current visual baseline workflow, web component tests, and route-level UI checks.
- For the first pass, the most valuable tests are view-presence checks, hierarchy checks, and workflow-preservation checks across the main tabs.
- Tests should cover the main surfaces: Chat, Plan, Memory, Trace, sidebar, and auxiliary tabs.

## Out of Scope

- Removing core workflows outright.
- Hiding or deleting evidence surfaces that are important for harness confidence.
- Replacing the entire design system from scratch.
- Rewriting backend behavior just to make the interface look cleaner.
- Collapsing all views into one monolithic page.
- Making product semantics simpler at the cost of losing useful functionality.
- Pursuing visual novelty for its own sake.
- Changing the current workflow architecture.

## Further Notes

This effort is deliberately conservative about feature deletion.

The main design statement is:

> Keep the core functionality, reduce the noise, and make the visual hierarchy match the actual workflow hierarchy.

The current best implementation seam is the existing web UI route/view layer, with the main app shell, chat workspace, sidebar, and supporting panels as the primary surfaces.

If you want, I can turn this into the next ticket chain with separate slices for layout unification, chat simplification, sidebar work-queue styling, and secondary-panel de-emphasis.
