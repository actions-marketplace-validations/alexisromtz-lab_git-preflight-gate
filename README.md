<!-- HUELLA-README-EN-20261105 -->
**Language:** English · [Español](README.es.md)

# CI Authority Gate

**Repository:** [`git-preflight-gate`](https://github.com/alexisromtz-lab/git-preflight-gate) · **Marketplace:** [Install the action](https://github.com/marketplace/actions/ci-authority-gate)

**An integrity gate for autonomous AI agents: so that a bot does not dirty the tree
and does not commit concurrency collisions either.**

Before an agent writes a line, the gate demands a destination tuple —
`TARGET` (absolute) · `BLOB_PRE` · `HUELLA` · `LINEAS_PRE` — and returns a code that
**authorizes or blocks** the write. Without a prior run ending in `RC 0`, nothing is written.

## Install

```bash
pip install git-preflight-gate        # Python CI gate (PyYAML comes with it)
ci-authority-gate /path/to/your/repo  # RC 0 = pass · RC > 0 = fail-closed, cause printed
```

Two doors, measured separately — do not confuse them:

| door | command | what it needs |
|---|---|---|
| **CI authority gate** | `pip install git-preflight-gate` | Python ≥ 3.9 + PyYAML (pip resolves it) |
| **pre-write gate (bash)** | `curl -fsSL https://raw.githubusercontent.com/alexisromtz-lab/git-preflight-gate/main/preflight-gate.sh -o preflight-gate.sh` | bash + git, **zero dependencies** |

The wheel ships the Python gate (`sim/`); the bash gate ships in the source distribution and in the repository, and is deliberately dependency-free so it can run on a machine with nothing installed. Neither is a wrapper around the other.

### The pre-write gate, at the shell

```bash
bash preflight-gate.sh /absolute/path/file.py <blob_pre> <exclusive_marker> <lineas_pre>
```

## The codes (fail-closed)

| RC | meaning |
|---:|---|
| `0` | PRE-FLIGHT OK — the target accepts an edit on `BLOB_PRE` |
| `10` | the object does not exist (creation) |
| `11` | **the marker already lives in the target** ⇒ collision: the row is already written |
| `12` | measured blob ≠ contract ⇒ the tree moved |
| `13` | dirty git state ⇒ unadjudicated modifications |
| `14` | the target is not inside a git tree ⇒ the gate cannot verify identity |
| `15` | line count differs from the contract |
| `20` | misuse (incomplete tuple, or `TARGET` not absolute) |

Every code comes out **with its cause printed**. A correct `RC` for the wrong reason is not a gate: it is a coincidence.

## Why `RC 11` is the case that matters

The most expensive defect of an agent is not picking the wrong path: it is **writing again something another hand already wrote**, and reporting success. The marker is an exclusive literal fragment of the text to be inserted; if it is already in the target, the write is rejected before the file is touched. The gate does not guess intent: it denies the collision.

## Why `TARGET` must be absolute

The gate rebases with `git -C <directory>` to measure the blob and the state. A relative path would be counted from **two different bases** (`cwd` and the object's directory) and could hash *another* file that does exist. Fail-closed: relative path ⇒ `RC 20`.

## Why `RC 14` exists

Without a git tree, `git status` returns 128 with empty output. A naive gate reads that empty output as "clean" and goes green. Here the impossibility is declared: without a tree there is no blob identity worth anything.

## Case bank

```bash
bash tests/must_fail.sh
```

9 cases, **9/9**, each verifying the code **and** the cause: `20` (incomplete tuple), `20` (relative path), `10`, `11`, `12`, `15`, `13`, `14`, and the positive control `0`. A bank without a positive control only proves the instrument knows how to say no.

## Out-of-band telemetry

Each run records 7 fields (`hora_utc target blob_pre blob_medido rc hash_arbol_ini hash_arbol_fin`) in `${GATE_TELEMETRIA_LOG:-$HOME/preflight-telemetria.log}`. Telemetry **cannot move the RC**, **cannot abort** and **cannot refresh the index** (`--no-optional-locks`). The path is never relative: a log inside the tree becomes an untracked file, and then the gate ends up measuring its own telemetry — the instrument counting itself.

## Declared limits

- On a nonexistent `TARGET` the gate stops at `RC 10` **before** comparing blob and lines: in the creation branch, the tuple is a **contract**, not a measurement. It is declared, not repaired (fail-closed is correct).
- It does not judge content: it certifies identity and collision, not correctness.

## The root Action: CI Authority Gate

The `action.yml` at this repository's root is a **composite action** running a second instrument, `sim/gate_workflows_ci.py`: a structural verifier of the authority topology in `.github/workflows/`. Five counting invariants, seven typed causes, `RC = min(causes)`, `UNIVERSO_VACIO` = cause `31` (zero files is failure, not approval).

Measured identity of the instrument copied into this tree:

| property | value |
|---|---|
| lines / bytes | 615 / 21470 |
| git blob | `ff9c69a944e7965b3fda0901f7745d80a9e85c7c` |
| sha256-16 | `073954a84f3c84fd` |

Using it as a consumer:

```yaml
- uses: alexisromtz-lab/git-preflight-gate@v0.1.4
  with:
    workflows-dir: .github/workflows
    fail-on-red: "true"
```

<!-- HUELLA-RELEASE-V013-20261031 -->
`v0.1.3`, `v0.1.2` and `v0.1.1` run the same `action.yml` (`9ef420ec`) and the same `sim/gate_workflows_ci.py` (`ff9c69a9`): the gate's code did not change across the three. What changes is the adoption wrapper — `v0.1.2` added `templates/platino-gate.yml` and `v0.1.3` added `action-selftest.yml`, the manifest alignment and this documentation. If you pin by SHA, use the commit — not the tag.

The four inputs (`workflows-dir`, `root`, `python-bin`, `fail-on-red`) and the two
outputs (`rc`, `veredicto`) preserve the contract of the `action.yml` that this
repository **replaces**: any CI that pointed at the root action of a working repository
migrates by changing only the repository name in `uses:`; the rest of the `with:` block
does not change.

The action does not guess the domain: the instrument resolves a single point, `<root>/.github/workflows`. That is why `workflows-dir` routes to `--file` when the path exists and to `--root` when it does not. A `--root` that accepted any directory with YAML files would be editing the ruler so the demo fits.

Single dependency: `PyYAML==6.0.3`, declared as an optional extra (`pip install ".[ci-authority-gate]"`). The rest is stdlib. The instrument does not read the network, does not write files, does not use randomness and does not consult the clock.

Installable without cloning the repository, from the release wheel. The
`ci-authority-gate` extra is mandatory for the CLI: without PyYAML the instrument does
not measure and exits `RC=30` (fail-closed), not green.

```bash
pip install "git-preflight-gate[ci-authority-gate] @ https://github.com/alexisromtz-lab/git-preflight-gate/releases/download/v0.1.4/git_preflight_gate-0.1.4-py3-none-any.whl"
ci-authority-gate --self-test   # built-in must-fail bank; touches no disk
ci-authority-gate --root .      # measures <root>/.github/workflows and returns its RC
```

<!-- HUELLA-README-V014-20261106 -->
`v0.1.4` does not change the gate: `action.yml` (`9ef420ec`) and
`sim/gate_workflows_ci.py` (`ff9c69a9`) are the same blobs as in `v0.1.3`. What changes
is the package: `MANIFEST.in` makes the sdist carry the product, and the manifest
declares the `sim` package and the `ci-authority-gate` script. Before this change the
wheel was 6 768 B of `dist-info` only and no CLI existed. It is not on PyPI yet: the
only `pip` path today is the release URL.

Measured positive control: workflow with `permissions: contents: read` and `uses` pinned by full SHA ⇒ `CAUSAS PRESENTES: ninguna`, `VEREDICTO: PASA`, `RC=0`. Negative control: `pull_request_target` + `permissions: write-all` + `curl | bash` + `actions/checkout@v4` ⇒ `CAUSAS PRESENTES: [1, 2, 5]`, `RC=1`. Empty universe ⇒ `CAUSAS PRESENTES: [31]`, `RC=31`.

## The two instruments are not to be confused

| instrument | question | form |
|---|---|---|
| `preflight-gate.sh` | may this agent write *this file* now? | bash CLI, target tuple |
| `sim/gate_workflows_ci.py` | does this CI topology concentrate authority without control? | composite action + Python CLI |

The first protects a write; the second audits a workflow tree. They share the doctrine (fail-closed, printed cause, zero files = declared impossibility), not the code.

## Install it in your repository in 1 minute

<!-- HUELLA-BADGE-PLATINO-README-20261031 -->

```bash
mkdir -p .github/workflows
curl -fsSL https://raw.githubusercontent.com/alexisromtz-lab/git-preflight-gate/main/templates/platino-gate.yml \
  -o .github/workflows/platino-gate.yml
git add .github/workflows/platino-gate.yml
git commit -m "ci: platino preflight gate"
git push
```

That is all: the workflow fires on the next `push` or PR.

### The file must be named `platino-gate.yml` (this is a contract, not advice)

If you rename it — `ci.yml`, `gate.yml`, `platino-gate.yaml` — the first job fails closed with `RC 20` and tells you why. The reason is measured, not aesthetic: the status badge resolves **by file name** (`.../workflow/status/YOUR-REPO/YOUR-REPO/platino-gate.yml`). With another name, the badge would read *your* CI workflow, not this gate, and would publish a green that measures nothing. The contract lives inside the workflow, not on this page.

Falsified by `tests/test_platino_gate_template.py`: 5 name cases and 5 structural cases, `RC 0` only if all 10 agree; a template mutated to accept any `.yml` returns `RC 1` naming the offending row.

## The badge

When the run finishes, the **Summary** tab publishes the badge already filled in with your `owner/repo`. There are two, and they are not the same:

| badge | what it claims | permissions it asks for |
|---|---|---|
| **status** (dynamic) | the real result of the most recent run of `platino-gate.yml` | `contents: read` |
| **seal** (static) | "this repository passed the gate" | `contents: read` |

```markdown
[![Platino Preflight Gate](https://img.shields.io/github/actions/workflow/status/OWNER/REPO/platino-gate.yml?label=preflight%20gate&branch=main)](https://github.com/alexisromtz-lab/la-auditora)

[![Audited by Platino Labs](https://img.shields.io/badge/audited_by-Platino_Labs-6f42c1)](https://github.com/alexisromtz-lab/la-auditora)
```

The status one cannot lie: GitHub draws it from the run. **The seal can**: it is a literal anyone can paste in green without having run anything. Use it only when the run is green — the gate cannot verify that for you.

**Zero write permissions, in both cases.** The workflow does not touch your README, does not ask for `contents: write` and needs no service of ours: the badge is a `shields.io` URL that reads the public status of your own workflow. There is no endpoint to host, no token to expire.

### What it measures and what it does not

| measures | does not measure |
|---|---|
| authority topology in `.github/workflows/`: `permissions`, triggers, `uses` pinned by SHA, execution sinks | whether your code does what it says |
| seven typed causes, `RC = min(causes)`, `UNIVERSO_VACIO` = cause `31` | default `GITHUB_TOKEN` permissions at organization level |
| the tree you have, at the commit that runs | OIDC / Trusted Publishing trust in the destination registry |

The second block is printed on every run, under `RESIDUO DECLARADO`. A gate that does not declare its limits is not a gate: it is a promise.

### How the wrapper tests itself

<!-- HUELLA-BADGE-SELFTEST-DOC-20261031 -->
`action.yml` is not tested by reading its YAML: it is executed. On every push to `main`, the workflow [`action-selftest.yml`](.github/workflows/action-selftest.yml) runs the action twice with `uses: ./` — once on this repository itself, where it demands `rc=0` / `PASA`, and once on a poisoned fixture in `tests/fixtures/sumidero`, where it demands `rc=2` / `SUMIDERO_IMPUDO`. If the extra's installation (`pip install "<action_dir>[ci-authority-gate]"`) or the input routing breaks, it goes red here before going red on your runner.

A self-test that only knows how to be green discriminates nothing: that is why the second case demands the action **fail** with the correct cause.

## License

MIT. See `LICENSE`.
