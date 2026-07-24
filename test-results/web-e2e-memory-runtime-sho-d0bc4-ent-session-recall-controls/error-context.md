# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: web\e2e\memory-runtime.spec.ts >> shows memory trace events and current session recall controls
- Location: web\e2e\memory-runtime.spec.ts:172:1

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/", waiting until "load"

```

# Test source

```ts
  73  |         updated_at: "2026-07-24T10:00:00.000Z",
  74  |         created_at: "2026-07-24T10:00:00.000Z",
  75  |         content: "**Decision:** React websocket state is session-aware.",
  76  |       },
  77  |       {
  78  |         name: "memory-discipline",
  79  |         description: "Memory extraction requires confidence reasons",
  80  |         type: "project",
  81  |         status: "active",
  82  |         scope: "project",
  83  |         confidence: 0.65,
  84  |         access_count: 1,
  85  |         updated_at: "2026-07-24T10:01:00.000Z",
  86  |         created_at: "2026-07-24T10:01:00.000Z",
  87  |         content: "**Decision:** Automatic memories require confidence reasons.",
  88  |       },
  89  |     ],
  90  |   };
  91  | }
  92  | 
  93  | function recallPayload() {
  94  |   return {
  95  |     session_id: SESSION_ID,
  96  |     items: [{
  97  |       session_id: SESSION_ID,
  98  |       memory_name: "react-loop",
  99  |       source: "scoped",
  100 |       score: 0.82,
  101 |       reason: "Matched terms: react, websocket, session",
  102 |       confidence: 0.85,
  103 |       scope: "project",
  104 |       injected: true,
  105 |       omitted_reason: "",
  106 |       created_at: "2026-07-24T10:04:00.000Z",
  107 |       description: "React loop state must be session-aware",
  108 |       type: "project",
  109 |       override: "",
  110 |     }],
  111 |   };
  112 | }
  113 | 
  114 | function generatedPayload() {
  115 |   return {
  116 |     session_id: SESSION_ID,
  117 |     items: [{
  118 |       name: "memory-discipline",
  119 |       description: "Memory extraction requires confidence reasons",
  120 |       type: "project",
  121 |       status: "active",
  122 |       scope: "project",
  123 |       confidence: 0.65,
  124 |       access_count: 1,
  125 |       updated_at: "2026-07-24T10:01:00.000Z",
  126 |       created_at: "2026-07-24T10:01:00.000Z",
  127 |       source_session_id: SESSION_ID,
  128 |     }],
  129 |   };
  130 | }
  131 | 
  132 | function tracePayload() {
  133 |   return [
  134 |     {
  135 |       type: "memory_recall",
  136 |       injected_count: 1,
  137 |       candidate_count: 3,
  138 |       omitted_count: 2,
  139 |       top_names: ["react-loop"],
  140 |       timestamp: "2026-07-24T10:03:00.000Z",
  141 |     },
  142 |     {
  143 |       type: "memory_written",
  144 |       name: "memory-discipline",
  145 |       description: "Memory extraction requires confidence reasons",
  146 |       source: "run_finalizer",
  147 |       confidence: 0.65,
  148 |       timestamp: "2026-07-24T10:04:00.000Z",
  149 |     },
  150 |   ];
  151 | }
  152 | 
  153 | test.beforeEach(async ({ page }) => {
  154 |   await page.route("**/api/sessions?limit=50", async (route) => route.fulfill({ json: sessionSummary() }));
  155 |   await page.route(`**/api/sessions/${SESSION_ID}`, async (route) => route.fulfill({ json: sessionDetail() }));
  156 |   await page.route(`**/api/sessions/${SESSION_ID}/messages`, async (route) => route.fulfill({ json: [] }));
  157 |   await page.route(`**/api/sessions/${SESSION_ID}/trace/events?after=0&limit=200`, async (route) => route.fulfill({ json: tracePayload() }));
  158 |   await page.route(`**/api/sessions/${SESSION_ID}/tree`, async (route) => route.fulfill({ json: { ...sessionSummary()[0], depth: 0, children: [], child_count: 0 } }));
  159 |   await page.route(`**/api/sessions/${SESSION_ID}/stats`, async (route) => route.fulfill({ json: { steps_taken: 1, max_steps: 10, total_tokens: 1200, duration_seconds: 30, tools: {} } }));
  160 |   await page.route(`**/api/sessions/${SESSION_ID}/plan`, async (route) => route.fulfill({ json: { session_id: SESSION_ID, content: "", has_plan: false } }));
  161 |   await page.route("**/api/config/models", async (route) => route.fulfill({ json: [] }));
  162 |   await page.route("**/api/skills", async (route) => route.fulfill({ json: [] }));
  163 |   await page.route("**/api/storage/stats", async (route) => route.fulfill({ json: { backend: "sqlite", total_sessions: 1, total_messages: 0, total_memories: 2, db_size_bytes: 1024 } }));
  164 |   await page.route("**/api/diffs/pending", async (route) => route.fulfill({ json: [] }));
  165 |   await page.route("**/api/memory?_expand=true", async (route) => route.fulfill({ json: memorySnapshot() }));
  166 |   await page.route(`**/api/memory/sessions/${SESSION_ID}/recalls`, async (route) => route.fulfill({ json: recallPayload() }));
  167 |   await page.route(`**/api/memory/sessions/${SESSION_ID}/generated`, async (route) => route.fulfill({ json: generatedPayload() }));
  168 |   await page.route(`**/api/memory/sessions/${SESSION_ID}/preview-recall`, async (route) => route.fulfill({ json: { ...recallPayload(), items: [{ ...recallPayload().items[0], memory_name: "memory-discipline", source: "scoped", score: 0.76 }] } }));
  169 |   await page.route(`**/api/memory/sessions/${SESSION_ID}/overrides`, async (route) => route.fulfill({ json: { session_id: SESSION_ID, memory_name: "react-loop", action: "pin" } }));
  170 | });
  171 | 
  172 | test("shows memory trace events and current session recall controls", async ({ page }) => {
> 173 |   await page.goto("/");
      |              ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  174 |   await page.getByText("Memory Runtime Session").click();
  175 | 
  176 |   await expect(page.getByText("Memory Recall")).toBeVisible();
  177 |   await expect(page.getByText("Memory Saved")).toBeVisible();
  178 | 
  179 |   await page.locator("button[data-view='memory']").click();
  180 |   await expect(page.getByText("Current session recall")).toBeVisible();
  181 |   await expect(page.getByText("1 injected · 1 recorded")).toBeVisible();
  182 |   await expect(page.getByText("Matched terms: react, websocket, session")).toBeVisible();
  183 |   await expect(page.getByText("Generated from this session")).toBeVisible();
  184 |   await expect(page.getByText("memory-discipline")).toBeVisible();
  185 | 
  186 |   const overrideRequest = page.waitForRequest(`**/api/memory/sessions/${SESSION_ID}/overrides`);
  187 |   await page.getByRole("button", { name: "Pin" }).click();
  188 |   await overrideRequest;
  189 | 
  190 |   await page.getByPlaceholder("Preview recall query...").fill("memory confidence reason");
  191 |   await page.getByRole("button", { name: "Preview recall" }).click();
  192 |   await expect(page.locator(".memory-list-meta").filter({ hasText: "memory-discipline" })).toBeVisible();
  193 | });
  194 | 
```