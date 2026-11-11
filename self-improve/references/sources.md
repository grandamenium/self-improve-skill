# Sources

Primary pages opened and checked 2026-11-11. These are concise paraphrases. The research motivates reflection and reusable knowledge; it does not validate this extractor or guarantee better performance, token savings or safe autonomous editing. No paper prompts or benchmark tables are bundled.

## Documentation and research

- **S1. [Skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).** Evaluate observed behavior, refine instructions, and keep the main skill concise with directly linked references.
- **S2. [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview).** Skills use metadata and progressively loaded instructions. Trigger descriptions matter.
- **S3. [Explore the .claude directory](https://code.claude.com/docs/en/claude-directory).** Describes local transcript files and privacy implications. Only inspect authorized history.
- **S4. [Claude Code hooks guide and reference](https://code.claude.com/docs/en/hooks-guide).** Explains event-specific hook controls. A PreToolUse hook can block before execution; post-action events cannot undo a completed call.
- **S5. [Claude Code memory](https://code.claude.com/docs/en/memory).** Covers instruction files, auto-memory, loading limits and the distinction between model context and enforcement.
- **S6. [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/research/equipping-agents-for-the-real-world-with-agent-skills).** Explains skill architecture and iterating from observed real usage.
- **S7. [Anthropic skill-creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md).** A public workflow for drafting skills, evaluating results, gathering feedback and iterating. Linked as reference, not bundled.
- **S8. [Effective context engineering for AI agents](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents).** Discusses context selection, persistent notes and the costs of expanding context.
- **S9. [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366).** Studies feedback-derived reflective text retained across trials, without updating model weights.
- **S10. [Voyager: An Open-Ended Embodied Agent with Large Language Models](https://arxiv.org/abs/2305.16291).** Studies a growing executable skill library and feedback-driven program refinement in Minecraft.
- **S11. [Self-Refine: Iterative Refinement with Self-Feedback](https://arxiv.org/abs/2303.17651).** Studies repeated generation, feedback and refinement using the same model.
- **S12. [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442).** Studies observations, memory retrieval, reflection and planning in a simulated social environment.
- **S13. [ExpeL: LLM Agents Are Experiential Learners](https://arxiv.org/abs/2308.10144).** Extracts reusable natural-language insights from experience for later decisions.
- **S14. [Agent Workflow Memory](https://arxiv.org/abs/2409.07429).** Induces reusable workflows and evaluates them on web navigation tasks.
- **S15. [SkillWeaver: Web Agents can Self-Improve by Discovering and Honing Skills](https://arxiv.org/abs/2504.07079).** Builds reusable website interaction APIs through exploration and practice.
- **S16. [Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models](https://arxiv.org/abs/2510.04618).** Studies incremental context updates and warns that repeated rewriting can discard useful detail.
- **S17. [Dynamic Cheatsheet: Test-Time Learning with Adaptive Memory](https://arxiv.org/abs/2504.07952).** Studies reusable strategies and code snippets retained during inference.

S4 companion: [Hooks reference](https://code.claude.com/docs/en/hooks). Hook behavior depends on the event, decision fields and installed version.

## Installation references

- [Claude Code skills](https://code.claude.com/docs/en/skills): local personal and project skill discovery.
- [Codex skills](https://developers.openai.com/codex/skills/): local `.agents/skills` locations and explicit skill invocation.

This kit is an implementation of a propose-only review workflow. Study conditions, models and tasks differ from a local skill review. Follow the primary links for methodology and limitations.
