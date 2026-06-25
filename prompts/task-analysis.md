Please answer the following question about the repository at {repo_path}.

## Task
{description}
{issue_section}
## Instructions
- Read the relevant code to find the answer
- Be efficient: use targeted searches and reads, don't browse aimlessly
- If the user limits which files may be read, use only those files as evidence
- Do not cite memory, prior knowledge, or files you did not read in this round as proof
- If the allowed files are insufficient to prove a claim, say that explicitly instead of inferring from memory
- For analysis conclusions, cite recorded evidence ids such as `[ev_xxx]` for confirmed claims when available
- Once you have enough information, respond directly with a clear answer
- Do NOT make any file changes unless explicitly asked

## Broad Analysis Strategy

For broad read-only tasks such as architecture review, module audit, optimization roadmap, or "summarize how X works":

- First classify the task scope: targeted lookup vs. broad analysis
- Before source reads in broad analysis, use discovery/search first and submit a compact read plan for the key files you intend to inspect, why each file matters, and a small per-file read budget
- Do not bulk-read every file in a directory by default
- Start with discovery/search to identify entry points, registries, base classes, managers, routers, and config
- Prefer abstraction and wiring files before leaf implementation files
- After reading 3-5 key files, synthesize what you know before reading more
- Read additional implementation files only to verify a specific claim or fill a named gap
- After synthesis, prefer `evidence_list`, `evidence_get`, `artifact_search`, and `artifact_read` to revisit captured evidence before broadening source reads
- If evidence is incomplete, state the uncertainty instead of exhaustively reading the whole module
