---
description: Save current context to persistent project memory
---
# Context Memorization Workflow

This workflow compresses current insights into a persistent memory file to save tokens in future sessions.

1. Create the directory `.agents/memory/` if it does not exist using the `run_command` tool (`mkdir -p .agents/memory`).
// turbo
2. Identify the core topic of the current discussion (e.g., "API Routing", "User Preferences").
3. Summarize the key facts, decisions, and context into a concise markdown format. Avoid verbose language.
4. Use `write_to_file` to save or append this summary to `.agents/memory/[topic_name].md`.
5. Notify the user that the memory has been successfully saved to the project's local knowledge base.
