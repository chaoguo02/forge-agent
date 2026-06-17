## Auto Memory Guidelines

### When to save
- **At the start** of a task, use memory_list to check if there's relevant prior knowledge
- **Save** useful information you discover: build commands, debugging tricks, project conventions, user preferences
- When the **user corrects you**, save the correction as a memory (type: feedback)
- Save **concrete, actionable** facts — not vague observations
- Use memory_write with descriptive names like "build-commands", "debugging-tips", "api-conventions"

### What NOT to save
- Code patterns, architecture, or file paths derivable from the current codebase
- Git history or recent changes — use git log / git blame instead
- Debugging solutions or fix recipes — the fix is in the code, the commit message has context
- Ephemeral task details: in-progress work, temporary state, current conversation context
- Anything already documented in project README or config files

### Before using a memory
- Memories can become stale. Before acting on a memory that names a specific file, function, or flag, **verify it still exists** (use find_files or search_text)
- If a memory conflicts with what you observe in the code, trust the code and update/delete the memory
- Treat memories as hints, not facts — they describe what WAS true, not necessarily what IS true

### Maintenance
- If a memory is **no longer relevant**, use memory_delete to keep the index clean
- If you discover a memory is outdated, update it with memory_write (same name overwrites)