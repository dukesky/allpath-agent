---
name: repository-analysis
description: Inspect a repository safely and produce an evidence-based architecture explanation.
---

# Repository Analysis

1. Start with metadata and top-level files instead of reading the whole repository blindly.
2. Use `search_files` to find entry points, configuration, tests, and important symbols.
3. Use `read_file` in bounded ranges and follow imports only when they affect the user's question.
4. Distinguish observed behavior from inference.
5. Cite relative file paths and line numbers in the final explanation.
6. Do not modify files unless the user explicitly asks; if they do, read first and use `patch` with the returned SHA-256.
