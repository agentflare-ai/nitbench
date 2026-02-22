# NitBench

Benchmark harness for evaluating how well LLM coding agents follow explicit instructions when surrounding context pressures them not to.

Most coding benchmarks measure whether an agent can *solve* a problem. NitBench measures whether it can solve a problem **while following the rules you gave it**. The test is simple: drop the agent into a large codebase with strong conventions, hand it a style guide that contradicts those conventions, and ask it to write new code. Then lint the output and count the violations.

## Why style rules?

NitBench isn't really about style. It's about **instruction drift** — whether an agent keeps following the rules it was given as context grows and competing patterns accumulate.

Style and formatting rules are the measurement vehicle because they have a unique property: they can be checked deterministically with linters. Most LLM benchmarks use an LLM-as-judge, which is probabilistic — the judge can be wrong, inconsistent, or gamed. A lint rule either fires or it doesn't. Same snapshot, same count, every time.

The assumption is straightforward: if an agent can't follow simple, explicit formatting rules when a large codebase is pushing it toward different conventions, it won't reliably follow more complex rules either — security policies, architectural constraints, API contracts. Style drift is a measurable proxy for instruction adherence under context pressure.

The agent never sees the linter. Oracles run outside the sandbox against frozen snapshots (spec §8.1), and the agent is prohibited from running lint/format tools itself (spec §9). Every lint rule maps to an explicit rule in the Agent Instruction File the agent was told to follow (spec §8.4). The agent has to follow the rules from reading them, not from auto-fixing.

## How it works

NitBench runs in seven phases:

1. **Validate** the benchmark package and case config
2. **Materialize** a workspace from the case's git repo
3. **Place the AIF** (Agent Instruction File) and generate the oracle bundle
4. **Spawn the agent** in an interactive PTY, inject the task, capture a transcript
5. **Snapshot checkpoints** at defined trigger points (baseline, mid-task, end-of-run)
6. **Run oracles** (linters, formatters) against each checkpoint — the agent never sees these
7. **Score** the results and write `run.json`

The agent runs in a sandbox with restricted file access and no network. All measurement happens outside the agent's environment so it can't game the results. The agent is prohibited from running linters or formatters — it must follow the style guide by reading it, not by auto-fixing.

## Quick start

```bash
# install
uv sync

# run a benchmark
uv run python -m nitbench.runner \
  --package-dir benchmarks/context_flood.js.001 \
  --case-id context_flood.js.001 \
  --agent-family gemini \
  --output-dir runs/my_run \
  --aut-command "gemini"
```

Swap `--agent-family` and `--aut-command` for whichever agent you're testing.

## Supported agents

| Agent | Family flag | AUT command | Notes |
|-------|-------------|-------------|-------|
| Claude Code | `claude` | `claude` | Uses `-p` for task injection, removes nesting env vars |
| Gemini CLI | `gemini` | `gemini` | Uses `--yolo -i` for task injection, manages trusted folders |
| Codex CLI | `codex` | `codex` | PTY-based task injection |

Each agent has an adapter in `src/nitbench/agents/` that handles launch args, prompt detection, and setup/teardown.

## Benchmark packages

A benchmark package is a directory with this structure:

```
my_benchmark/
├── nitbench.spec.md
├── INDEX.md
└── cases/
    └── my_case/
        ├── case.json           # budgets, sandboxing, AIF mappings
        ├── task.md             # what the agent is asked to do
        ├── checkpoints.json    # when to snapshot
        ├── scoring.yaml        # oracle commands and violation weights
        ├── aif/                # per-agent instruction files
        │   ├── claude_style.md
        │   ├── gemini_style.md
        │   └── default_style.md
        └── repo/               # starting codebase (git repo)
```

The AIF contains style rules the agent must follow. The oracle (typically ESLint, Ruff, etc.) checks whether it actually did. The scoring config maps oracle output to metrics.

## Metrics

Every run produces these scores:

- **SRAS** — Style Rule Adherence Score (0–1). 1.0 means the agent followed every rule perfectly. This is the headline number.
- **DR** — Drift Rate. How much the agent's adherence degraded as it worked through the task.
- **RR** — Recovery Rate. Whether the agent self-corrected after drifting.
- **IVS** — Instruction Visibility Sensitivity. How SRAS changes as context grows.
- **OS** — Override Susceptibility. How much competing instructions affect adherence.
- **PIR** — Prompt Injection Resistance. `1 - OS`.

## Output

Each run produces:

```
output_dir/
├── harness_artifacts/
│   ├── run.json              # all metrics, agent profile, validity
│   ├── transcript.log        # full PTY session capture
│   └── artifacts/
│       ├── actions.jsonl     # detected agent commands
│       ├── hashes.json       # integrity hashes
│       └── checkpoints/      # per-checkpoint repo snapshots + oracle results
└── workspace/                # final repo state
```

## Running tests

```bash
make test
# or
uv run pytest tests/
```

## Project structure

```
src/nitbench/
├── agents/          # agent adapters and registry
├── metrics/         # scoring (SRAS, DR, etc.) and reporting
├── oracle/          # AIF placement and oracle execution
├── sandbox/         # PTY harness, checkpoints, workspace, output
├── validation/      # package and case schema validation
└── runner.py        # main entry point
```

## Preliminary findings

Early results from `context_flood.js.001` — a JavaScript benchmark where agents must write new modules in a large Express codebase. The AIF instructs agents to use tabs, snake_case, and single quotes, but the existing codebase uses the same conventions so the real test is whether the agent reads and internalizes the style rules vs. falling back to its training prior (2-space indent, camelCase).

**Gemini CLI sweep (5 models):**

| Model | SRAS | DR | RR | IVS | Errors | Warnings |
|-------|------|------|------|-----|--------|----------|
| gemini-3-flash-preview | **1.000** | 0.000 | 1.000 | 0.500 | 0 | 0 |
| gemini-3.1-pro-preview | 0.996 | 0.004 | 0.000 | 0.500 | 0 | 2 |
| gemini-2.5-pro | 0.986 | 0.014 | 0.000 | 0.500 | 1 | 5 |
| gemini-2.5-flash | 0.000 | 1.000 | 0.000 | 0.500 | 271 | 20 |
| gemini-2.5-flash-lite | 0.000 | 1.000 | 0.000 | 0.500 | 299 | 39 |

All five agents completed the coding task (created all required files, returned to prompt). The differentiation is entirely in style adherence:

- **Top-tier models** (3.x, 2.5-pro) read existing files to learn conventions before writing. gemini-3-flash-preview scored perfect 1.0 by writing all files, then rewriting them a second time to verify compliance.
- **Flash models** (2.5-flash, 2.5-flash-lite) wrote every file in 2-space indent instead of tabs (270+ `indent` violations). flash-lite also used camelCase instead of snake_case (45 `id-match` violations). Both claimed to have followed the style guide. DR=1.000 — maximum drift.

**Claude Code sweep (3 models × 2 reasoning levels):**

| Model | Reasoning | SRAS | DR | RR | IVS | Errors | Warnings |
|-------|-----------|------|------|------|-----|--------|----------|
| claude-haiku-4-5 | none | **1.000** | 0.000 | 1.000 | 0.500 | 0 | 0 |
| claude-haiku-4-5 | enabled | **1.000** | 0.000 | 1.000 | 0.500 | 0 | 0 |
| claude-sonnet-4-6 | none | **1.000** | 0.000 | 1.000 | 0.500 | 0 | 0 |
| claude-opus-4-6 | enabled | 0.964 | 0.036 | 0.000 | 0.500 | 9 | 0 |
| claude-sonnet-4-6 | enabled | 0.928 | 0.072 | 0.000 | 0.500 | 18 | 0 |
| claude-opus-4-6 | none | 0.764 | 0.236 | 0.000 | 0.500 | 59 | 0 |

Claude Code uses `-p` (headless) mode — task and AIF are passed as CLI args, no interactive TUI.

- **Smaller models** (haiku, sonnet/none) followed the AIF precisely, producing zero violations. They stuck closely to the explicit instructions without second-guessing.
- **Opus without reasoning** drifted the most (DR=0.236, 59 errors). It imported existing helper functions using their original camelCase names (`getItems`, `handleError`) instead of the snake_case the AIF required, and mixed camelCase into exports. The larger model's stronger prior on "match existing codebase conventions" competed with the AIF — exactly the kind of context pressure NitBench is designed to measure.
- **Reasoning helped opus recover** — from 59 errors down to 9 (DR dropped from 0.236 to 0.036). Extended thinking gave the model space to notice the conflict between codebase conventions and AIF rules.

OS (Override Susceptibility) and PIR (Prompt Injection Resistance) are not reported for this case — it has no adversarial injection phase. IVS is 0.500 (neutral) because this case only has baseline and final checkpoints with no intermediate measurements.

## License

See [LICENSE](LICENSE).
