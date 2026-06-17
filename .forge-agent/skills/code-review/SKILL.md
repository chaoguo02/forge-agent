---
name: code-review
description: Review code changes for bugs, security issues, and style improvements.
---

You are performing a thorough code review. Analyze the changes carefully.

$ARGUMENTS

## Review Checklist

1. **Logic errors**: Off-by-one, null/undefined access, race conditions, edge cases
2. **Security**: Injection vulnerabilities, hardcoded secrets, unsafe deserialization
3. **Style**: Naming conventions, dead code, overly complex expressions
4. **Performance**: Unnecessary allocations, O(n^2) patterns, missing caching opportunities

## Output Format

For each issue found:
- File path and line number
- Severity (critical / warning / suggestion)
- What's wrong and why
- Suggested fix (code snippet if applicable)

If no issues found, state "No issues found" and highlight what was done well.
