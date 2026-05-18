---
name: dream-review
shortcut: dream
description: Use this skill only when the user wants to manually inspect, force, or debug Hyper AI Auto Dream. Auto Dream itself is a background service, not a prompt workflow.
description_zh: 仅当用户要求手动检查、强制运行或调试 Hyper AI Auto Dream 时使用。Auto Dream 本身是后台服务，不是提示词流程。
---

# Dream Review

Manual control surface for the autonomous Auto Dream service. The normal behavior is background operation: the server gates on time, recently touched conversations, and a lock, then runs memory consolidation without waiting for a user prompt.

## Workflow

### Phase 1: Scope the Review

1. First explain that Auto Dream normally runs automatically in the background.
2. Identify whether the user wants status, a dry run, or an immediate forced consolidation pass.
3. Treat this as reflective maintenance only. Do not place trades, bind strategies, change wallets, or alter trader configuration.

### Phase 2: Inspect and Consolidate

1. Call `get_robot_architecture` with `include_recent_activity=true` to inspect Auto Dream status and architecture health.
2. Call `run_dream_review` only if the user asks to run a dream pass now or debug what it would consolidate.
3. Use `save_memories=false` for a dry run.
4. Use `save_memories=true` only when the user explicitly wants immediate memory consolidation. Leave `wait_for_memory_write=false` unless they need a synchronous result.

[CHECKPOINT] Report what was reviewed, whether memory consolidation was queued or completed, and any architecture warnings.

### Phase 3: Recommend Next Improvements

Prioritize improvements in this order:

1. Missing risk metadata or unsafe tool exposure.
2. Context compression and memory gaps.
3. Sub-agent or skill routing gaps.
4. Observability gaps such as missing traces, runtime stats, or cost tracking.

Keep recommendations operational and specific. If the dream review wrote memories, mention that future conversations can use the consolidated context.

## Safety Rules

- Auto Dream can write only long-term memories.
- Manual `run_dream_review` is not the main mechanism; it is a force/debug path.
- Never use this skill to trade, cancel orders, update bindings, delete entities, or change exchange settings.
- Do not preserve secrets in memory; credentials and tokens should be redacted or ignored.
