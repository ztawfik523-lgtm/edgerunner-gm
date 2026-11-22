---
name: prompt-authoring
description: Use when writing or revising task prompts, agent instructions, specialist requests, or handoffs. Clarifies the intended outcome, context, requirements, boundaries, and useful completion evidence without over-specifying routine methods.
---

# Prompt authoring

Give the recipient enough context to act correctly and enough room to use judgment.

- Lead with the outcome or question. Say whether the work is design, investigation, implementation, review, or verification when that distinction matters.
- Supply relevant decisions, prior findings, source locations, dependencies, and constraints. Link authoritative material instead of copying it wholesale.
- Distinguish approved requirements and established rules from suggestions, examples, and open decisions.
- State what completion looks like and how it can be checked. For research, identify the question and evidence needed; for implementation, identify the behavior that must work.
- Explain consequential open choices and their impact. Ask for a decision where needed, while allowing unrelated approved work to continue.
- Keep restrictions tied to a concrete reason. Prefer positive desired behavior; retain prohibitions for real boundaries.
- Remove duplicate, conflicting, or superseded instructions. Leave ordinary methods, formatting, and implementation choices to the recipient unless they affect the result.
- Scale prompt length to task complexity: a straightforward request can be short; a complex handoff should preserve settled decisions, reliable findings and locations, completed work, and specific next steps.

For this project’s task briefs and handoffs, see [AGENT_INTENT_AND_PROMPTING.md](../../../docs/AGENT_INTENT_AND_PROMPTING.md).
