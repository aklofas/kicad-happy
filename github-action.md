# GitHub Action — Automated KiCad Design Review

Add automated design review to any KiCad project. Every push and PR that touches KiCad files gets a **commit status check** (green/red with findings summary). On PRs, a structured review comment is posted covering power tree, protocol compliance, voltage derating, SPICE results, EMC risk analysis, thermal analysis, component health, and PCB stats.

No account needed — just add the workflow file.

## Basic setup

```yaml
# .github/workflows/kicad-review.yml
name: KiCad Design Review
on:
  push:
    paths: ['**/*.kicad_sch', '**/*.kicad_pcb']
  pull_request:
    paths: ['**/*.kicad_sch', '**/*.kicad_pcb']

permissions:
  contents: read
  pull-requests: write
  statuses: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - run: sudo apt-get install -y ngspice poppler-utils
      - uses: aklofas/kicad-happy@v3
        id: analysis
      - uses: thollander/actions-comment-pull-request@v3
        if: github.event_name == 'pull_request'
        with:
          file-path: ${{ steps.analysis.outputs.report-path }}
          comment-tag: kicad-happy-review
          mode: upsert
```

The PR comment updates on re-pushes. A [full report](skills/kicad/references/report-generation.md) is available on the Actions run page. SPICE-enhanced mode activates automatically when ngspice is installed. EMC and thermal analysis run automatically after schematic/PCB analysis.

## Diff-based PR reviews

Enable `diff-base: true` to show only what changed between the PR and the base branch — component additions/removals, signal parameter shifts, new/resolved EMC findings, and SPICE status transitions. The PR comment includes a "Changes from Base" section.

```yaml
      - uses: aklofas/kicad-happy@v3
        id: analysis
        with:
          diff-base: true
```

## AI-powered review (optional)

Chain with [`anthropics/claude-code-action`](https://github.com/anthropics/claude-code-action) for Claude to read the analysis + datasheets and write a natural-language design review. The deterministic analysis (schematic, PCB, EMC, thermal) is always free. The cost estimates below come from Anthropic API calls made by `claude-code-action` — there's no additional cost when reviewing locally with a Claude Code or OpenAI Codex subscription.

### Quick review (~$1-3 per PR via API, 5-10 min)

```yaml
      - uses: anthropics/claude-code-action@v1
        if: github.event_name == 'pull_request' && env.ANTHROPIC_API_KEY != ''
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          prompt: |
            The kicad-happy deterministic analysis has already been run.
            Read the markdown report at ${{ steps.analysis.outputs.report-path }}.

            Do NOT re-run analysis scripts. Review the findings and:
            1. Verify the top 3-5 IC pinouts against datasheets
            2. Check WARNING findings for accuracy
            3. Note anything the analysis may have missed

            Post a concise summary (under 2000 chars) as a PR comment.
            Focus on actionable findings only.
          claude_args: '--model claude-sonnet-4-6 --max-turns 25'
```

### Thorough review (~$5-15 per PR via API, 10-20 min)

```yaml
      - uses: anthropics/claude-code-action@v1
        if: github.event_name == 'pull_request' && env.ANTHROPIC_API_KEY != ''
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        with:
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          prompt: |
            The kicad-happy deterministic analysis has already been run.
            Read the JSON at ${{ steps.analysis.outputs.schematic-json }}
            and the report at ${{ steps.analysis.outputs.report-path }}.

            Do NOT re-run analysis scripts. Perform a thorough review:
            1. Read datasheets for every IC and verify pinouts
            2. Check voltage divider/feedback calculations against datasheets
            3. Verify application circuit compliance for regulators
            4. Check power sequencing and enable chain logic
            5. Review protection device coverage on external interfaces
            6. Note any design concerns the analysis missed

            Post your review as a PR comment. Include specific datasheet
            page references for each finding.
          claude_args: '--model claude-sonnet-4-6 --max-turns 50'
```

### Setup

Get an API key from [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys), then add it as a repository secret named `ANTHROPIC_API_KEY` in Settings → Secrets → Actions. Cost depends on design complexity — see [Anthropic pricing](https://www.anthropic.com/pricing).

## Codex-powered review (alternative)

If you use OpenAI Codex, you can chain the deterministic analysis with [`openai/codex-action@v1`](https://github.com/openai/codex-action) for AI-powered PR reviews:

```yaml
      - uses: openai/codex-action@v1
        if: github.event_name == 'pull_request' && env.OPENAI_API_KEY != ''
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        with:
          prompt: |
            The kicad-happy deterministic analysis has already been run.
            Read the markdown report at ${{ steps.analysis.outputs.report-path }}.

            Do NOT re-run analysis scripts. Review the findings and:
            1. Verify the top 3-5 IC pinouts against datasheets
            2. Check WARNING findings for accuracy
            3. Note anything the analysis may have missed

            Post a concise summary (under 2000 chars) as a PR comment.
            Focus on actionable findings only.
```

You can also trigger reviews from PR comments with `@codex review` if the Codex GitHub app is installed on the repo.

## opencode-powered review (alternative)

If you use [opencode](https://github.com/sst/opencode), chain the deterministic analysis with [`anomalyco/opencode/github`](https://github.com/anomalyco/opencode) for AI-powered PR reviews. opencode is provider-agnostic (BYOK across Anthropic, OpenAI, Google, Zhipu, and 75+ others via [Models.dev](https://models.dev)), so pick whichever model fits your budget and latency.

```yaml
      - uses: anomalyco/opencode/github@latest
        if: github.event_name == 'pull_request' && env.ANTHROPIC_API_KEY != ''
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          model: anthropic/claude-sonnet-4-6
          agent: build
          use_github_token: true
          prompt: |
            The kicad-happy deterministic analysis has already been run.
            Read the markdown report at ${{ steps.analysis.outputs.report-path }}.

            Do NOT re-run analysis scripts. Review the findings and:
            1. Verify the top 3-5 IC pinouts against datasheets
            2. Check WARNING findings for accuracy
            3. Note anything the analysis may have missed

            Post a concise summary (under 2000 chars) as a PR comment.
            Focus on actionable findings only.
```

Set the `model` field to any Models.dev id (e.g. `openai/gpt-5`, `zai-coding-plan/glm-5.1`) and match the env var to that provider's key. `use_github_token: true` lets opencode post the review comment via the workflow's `GITHUB_TOKEN`. See the [opencode providers catalog](https://opencode.ai/docs/providers) for the full model list.

For comment-triggered reviews (e.g. `/oc` or `/opencode` on a PR or issue), `anomalyco/opencode/github` supports `issue_comment` and `pull_request_review_comment` triggers with a filter on comment body — see [corv89/kicad-happy's interactive workflow example](https://github.com/corv89/kicad-happy/blob/main/action/examples/opencode-interactive.yml) for the verified pattern.

## More examples

See [`action/examples/`](action/examples/) for fork-safe workflows, distributor API keys for datasheet download, and advanced configuration.
