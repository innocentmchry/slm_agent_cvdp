# SLM Agent for the CVDP Benchmark

An iterative-refinement agent that writes Verilog/SystemVerilog for [CVDP benchmark](https://github.com/NVlabs/cvdp_benchmark) problems. It generates RTL with a language model, compiles it, runs the problem's own test harness inside the agent container, and feeds the errors back to the model for up to three attempts.

This repository is a fork of `NVlabs/cvdp_benchmark`. It differs from the original in three ways:

1. **The agent** in this directory (`main_agent/SLM_agent/`) is new.
2. **The benchmark harness** (`run_benchmark.py`, `run_samples.py` and `src/`) is modified so the agent can see the test harness, runs can be resumed, and evaluation can be re-run on its own.
3. **Two model backends** are added for running the benchmark without the agent: Claude and a local model server.

See [Changes to the original benchmark](#changes-to-the-original-benchmark) for the full list.

The original documentation is unchanged and still applies to everything not covered here: `README.md`, `README_AGENTIC.md`, `README_NON_AGENTIC.md`, `README_DEVELOPER.md`, `README_FULL.md` and `LOCAL_INFERENCE_GUIDE.md` at the repository root.

## Contents

- [Quick start](#quick-start)
- [Model modes](#model-modes)
- [Building the agent image](#building-the-agent-image)
- [Running the benchmark with the agent](#running-the-benchmark-with-the-agent)
- [Running the benchmark without the agent](#running-the-benchmark-without-the-agent)
- [Output files](#output-files)
- [How the agent works](#how-the-agent-works)
- [Configuration](#configuration)
- [Features that are currently switched off](#features-that-are-currently-switched-off)
- [Changes to the original benchmark](#changes-to-the-original-benchmark)
- [Utility scripts](#utility-scripts)
- [Troubleshooting](#troubleshooting)

## Quick start

All paths are relative to the benchmark root (the directory containing `run_benchmark.py`). This example uses OpenAI `gpt-4o-mini`.

```bash
# 1. Put your OpenAI key in the .env at the benchmark root (the file is git-ignored)
echo 'OPENAI_USER_KEY=sk-...' >> .env

# 2. Build the simulation image once (compiles Icarus, Yosys and Verilator; takes a while)
docker build -f docker/Dockerfile.sim -t nvidia/cvdp-sim:v1.0.0 .

# 3. Build the agent image
API_TYPE=openai SLM_MODEL=gpt-4o-mini ./main_agent/SLM_agent/build_agent.sh gpt-agent

# 4. Run the benchmark with the agent
./run_benchmark.py \
  -f ./example_dataset/cvdp_v1.1.0_example_nonagentic_code_generation_no_commercial_with_solutions.jsonl \
  -l -g gpt-agent --force-agentic --force-agentic-include-harness \
  -p gpt-4o-mini-run1
```

Results are written to `gpt-4o-mini-run1/report.txt`.

This fork targets CVDP v1.1.0 datasets, whose tests need cocotb 2. Older v1.0.x datasets do not run on the v1.1.0 simulation image.

## Model modes

The agent talks to a model in one of three ways. The mode and model are fixed when the image is built.

| Mode (`API_TYPE`) | What it calls | Needs |
|---|---|---|
| `slm` (default) | A model server you run on the host machine | A server listening on a port, 8001 by default |
| `openai` | OpenAI Chat Completions API | `OPENAI_USER_KEY` in the root `.env` |
| `claude` | Anthropic Messages API | `CLAUDE_API_KEY` or `ANTHROPIC_API_KEY` in the root `.env` |

### API keys

Keys are never stored in the image or written to the run directory. The harness reads them from the root `.env` and passes them to the agent container by name when it starts.

| Mode | Set in root `.env` | The agent also accepts |
|---|---|---|
| `openai` | `OPENAI_USER_KEY` | `OPENAI_API_KEY` |
| `claude` | `CLAUDE_API_KEY` or `ANTHROPIC_API_KEY` | |

Optionally set `CLAUDE_API_URL` in `.env` to use a different Claude endpoint.

To pass any other variable to the agent, list its name in `CVDP_AGENT_ENV`, for example `CVDP_AGENT_ENV=MY_VAR,OTHER_VAR`.

### Local model server (`slm` mode)

The agent sends `POST {SLM_API_URL}/generate` with this JSON body:

```json
{"prompt": "...", "max_length": 32768, "model": "phi", "temperature": 0.7, "top_p": 0.95}
```

It reads the generated text from the first of these response fields that exists: `generated_text`, `text`, `response`, `output`, `result`.

By default the agent calls `http://host.docker.internal:<port>`, where the port is chosen at build time. The harness makes `host.docker.internal` resolve to the host machine. The model server must listen on `0.0.0.0`, not only on `127.0.0.1`, or the container cannot reach it.

To point an existing image at a different server without rebuilding, set `SLM_API_URL` in the root `.env` or in the shell before running the benchmark:

```bash
SLM_API_URL=http://localhost:8002 ./run_benchmark.py ...
```

The harness replaces `localhost`, `127.0.0.1` or `host.docker.internal` in that URL with the host's network address, so the container can reach it.

`docker-compose-agent-hostnet.yml.template` is an alternative for running the agent by hand with host networking. The harness does not use it.

## Building the agent image

```bash
cd main_agent/SLM_agent
./build_agent.sh [image-name] [slm-port]
```

The mode and model are set with environment variables. Without them, the image uses `slm` mode with model `phi`.

```bash
# Local model server
./build_agent.sh                                              # model "phi", port 8001, image "slm-agent-8001"
SLM_MODEL=granite4 ./build_agent.sh                           # a different local model
SLM_MODEL=deepseek ./build_agent.sh slm-agent-8002 8002       # server on port 8002

# OpenAI
API_TYPE=openai SLM_MODEL=gpt-4o-mini ./build_agent.sh gpt-agent

# Claude
API_TYPE=claude SLM_MODEL=claude-sonnet-4-6 ./build_agent.sh claude-agent
```

`SLM_MAX_LENGTH`, `SLM_TIMEOUT`, `SLM_TEMPERATURE` and `SLM_TOP_P` can be overridden the same way. See [Configuration](#configuration).

The equivalent plain Docker command is:

```bash
docker build -t gpt-agent --no-cache \
  --build-arg API_TYPE=openai --build-arg SLM_MODEL=gpt-4o-mini .
```

The image is built on top of the benchmark simulation image `nvidia/cvdp-sim:v1.0.0`, the same one the harness evaluates with, so the agent's own test runs use the same cocotb, pytest, Icarus Verilog and Verilator. Build that image first (see [Quick start](#quick-start)); `build_agent.sh` stops with a message if it is missing. Set `BASE_IMAGE` to build on a different image.

Packages that a harness installs at run time are held to the versions already in the image, so they cannot replace its cocotb.

Rebuild the image after any change to the agent's Python code, because the code is copied into the image.

## Running the benchmark with the agent

Run these from the benchmark root. Replace `gpt-agent` with your image name and `<dataset>` with a `.jsonl` dataset file.

| Flag | Meaning |
|---|---|
| `-f <dataset>` | Dataset file |
| `-l` | Evaluate model output instead of the reference solution |
| `-g <image>` | Agent Docker image to run |
| `-p <dir>` | Output directory for this run |
| `--force-agentic` | Convert a non-agentic dataset to the agentic format. Not needed for agentic datasets |
| `--force-agentic-include-harness` | Give the agent the test harness. **Required**: this agent uses the harness to check its own code |
| `-t <n>` | Number of problems to run in parallel |

### Fresh run

Use an output directory that does not exist yet.

```bash
./run_benchmark.py -f <dataset> -l -g gpt-agent \
  --force-agentic --force-agentic-include-harness -p <new-dir>
```

### Resume a run

Use this when a run stopped partway. It skips the agent for every problem before the one you name, runs the agent from that problem onward, then evaluates all problems.

```bash
./run_benchmark.py -f <dataset> -l -g gpt-agent \
  --force-agentic --force-agentic-include-harness -p <existing-dir> \
  --start cvdp_copilot_signed_adder
```

`--start` (alias `--start-from`) accepts the dataset problem ID, the problem directory name (`cvdp_copilot_...`), or a path such as `cvdp_copilot_signed_adder/harness/1`. Problems are ordered as they appear in the dataset.

Without `--start`, re-running on an existing directory runs the agent again on every problem.

### Evaluate only

Skips preparation and the agent, and re-runs only the test harness on the RTL already in the output directory.

```bash
./run_benchmark.py -f <dataset> -l -g gpt-agent \
  --force-agentic --force-agentic-include-harness -p <existing-dir> --evaluate
```

This needs `<existing-dir>/prompt_response.jsonl` from an earlier run. It cannot be combined with `-i`.

### Single problem

```bash
./run_benchmark.py -f <dataset> -l -g gpt-agent \
  --force-agentic --force-agentic-include-harness -p <dir> -i <problem-id>
```

### Multiple samples

`run_samples.py` repeats a run several times (`-n`, default 5) into `<dir>/sample_1`, `<dir>/sample_2` and so on, then combines the results. It takes the same options as `run_benchmark.py`; see the root `README.md`.

One option is added in this fork: `--sample <n>` re-evaluates a single existing sample without running the agent, then recomputes the combined report from all samples.

```bash
./run_samples.py -f <dataset> -l -g gpt-agent \
  --force-agentic --force-agentic-include-harness -n 5 -p <dir> --sample 2
```

`<dir>/sample_2/prompt_response.jsonl` must already exist.

### Re-run one agent by hand

Each problem directory contains the script the harness used:

```bash
cd <dir>/cvdp_copilot_signed_adder/harness/1
./run_docker_agent.sh        # run the agent again
./run_docker_agent.sh -d     # open a shell in the agent container instead
```

## Running the benchmark without the agent

The benchmark can also call a model directly, once per problem, with no refinement loop. Use `-m` instead of `-g`. Two backends are added in this fork.

```bash
# Claude. Needs CLAUDE_API_KEY or ANTHROPIC_API_KEY in the root .env
./run_benchmark.py -f <dataset> -l -m claude-sonnet-4-6 -p <dir>

# Local model server
./run_benchmark.py -f <dataset> -l -m local_server -p <dir>
```

The local server backend is configured in the root `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `LOCAL_SERVER_URL` | `http://127.0.0.1:8002` | Server address |
| `LOCAL_SERVER_API_STYLE` | `auto` | Request format: `auto`, `openai`, `claude` or `slm` |
| `LOCAL_SERVER_MODEL` | none | Model name to send to the server |
| `LOCAL_SERVER_API_KEY` | none | Key, if the server needs one |
| `LOCAL_SERVER_MAX_CONCURRENCY` | 1 | Parallel requests. `-t` is capped to this value |
| `LOCAL_SERVER_MAX_TOKENS` | 12288 | Maximum output tokens |
| `LOCAL_SERVER_REQUEST_TIMEOUT` | 0 | Seconds per request; 0 means no limit |
| `LOCAL_SERVER_STARTUP_TIMEOUT` | 600 | Seconds to wait for the server to become healthy |
| `LOCAL_SERVER_HEALTH_PATH` | `/health` | Health-check path |
| `LOCAL_SERVER_STARTUP_POLL_INTERVAL` | 2 | Seconds between health checks |

## Output files

```
<dir>/
├── report.txt, report.json        Pass/fail summary
├── raw_result.json                Per-problem results
├── prompt_response.jsonl          Prepared runs; its presence makes the directory reusable
├── run.log
└── cvdp_copilot_<name>/
    ├── reports/
    │   ├── <n>_agent.txt          Agent console output: every prompt, response and extracted code
    │   └── <n>.txt                Final harness evaluation log
    └── harness/<n>/
        ├── rtl/                   RTL written by the agent
        ├── docs/, verif/, src/    Problem files and test harness
        ├── environment/env.txt    Problem category and difficulty
        ├── rundir/agent_detailed.log   Detailed agent log
        ├── rundir/agent_metrics.json   Tokens, latency and outcome of every LLM call and iteration
        ├── agent_changes.patch    What the agent changed
        ├── docker-compose-agent.yml, run_docker_agent.sh
        └── docker-compose.yml, run_docker_harness_*.sh
```

A problem passes when every harness service exits with code 0. A harness that times out is recorded with exit code 124.

## How the agent works

For each problem, the harness starts one agent container with the problem directory mounted at `/code`.

1. **Read the task** from `/code/prompt.json`.
2. **Gather context**: the files under `rtl/`, `docs/` and `verif/`, in that order. Context is limited to about 75% of the model's token budget (`SLM_MAX_LENGTH`). When it does not fit, RTL is kept and documentation and verification files are truncated.
3. **Pick the target file**: an empty file in `/code/rtl` if there is one. Otherwise the name comes from `VERILOG_SOURCES` in the harness file `/code/src/.env`, falling back to `<TOPLEVEL>.sv`.
4. **Refinement loop**, up to 5 iterations:
   1. Build the prompt. The first prompt contains the system prompt, a category-specific instruction, the task and the context files. Later prompts add the previous code and its errors.
   2. Call the model.
   3. Extract the Verilog from the response and check it has balanced `module`/`endmodule`. If the top module name does not match `TOPLEVEL`, rename the closest-named module.
   4. **Compile check** with `verilator --lint-only`, falling back to Icarus Verilog if Verilator is unavailable. Other RTL files in `/code/rtl` are included so multi-file designs compile. Warnings alone count as a pass.
   5. If it compiles, write the code to `/code/rtl`.
   6. **Run standalone testbenches** found in `/code/verif` with Icarus Verilog. A failure here does not stop the loop; it is reported to the model as extra feedback.
   7. **Run the harness tests** inside the agent container.
   8. Stop if the harness tests pass. Otherwise go to the next iteration.
5. The agent always exits with code 0. The harness evaluation that follows decides pass or fail.

Code that does not compile is never written to `/code/rtl`, so the last compiling attempt is what gets evaluated.

### Running the harness inside the agent

The real harness runs each test in its own Docker container. The agent cannot start containers, so `testing/test_runner.py` reproduces the harness in-process:

- Reads `/code/docker-compose.yml` and, for each service, the referenced Dockerfile.
- Installs the `pip` packages the Dockerfile and command ask for.
- Loads the service's `env_file`.
- Extracts the `pytest` command, rewrites its paths to work from `/code`, and runs it.

Two safeguards stop runaway simulations: a 180-second timeout, and a watchdog that kills the test when system memory use reaches 90% (`SIM_MEMORY_KILL_THRESHOLD_PCT`).

### Refinement prompts

The refinement prompt depends on what failed:

| Situation | Template |
|---|---|
| Compilation failed | `REFINEMENT_TEMPLATE_1` |
| Compiled, tests failed, no lint warnings | `REFINEMENT_TEMPLATE_2` |
| Compiled, tests failed, lint warnings present | `REFINEMENT_TEMPLATE_3` |

Templates and the category instructions (`CATEGORY`) are in `prompts/templates.py`. The category comes from `/code/environment/env.txt`, which the modified harness writes.

### Code layout

```
SLM_agent/
├── main.py                    Entry point
├── Dockerfile, build_agent.sh
├── config/settings.py         AgentConfig
├── core/
│   ├── agent.py               Wires the components together
│   └── refinement_loop.py     The generate / test / refine loop
├── llm/
│   ├── api_client.py          OpenAI, Claude and local-server clients
│   └── response_parser.py     Code extraction and module-name correction
├── prompts/
│   ├── templates.py           Prompt templates and category instructions
│   └── prompt_builder.py      Prompt assembly and context budgeting
├── hdl/
│   ├── code_manager.py        Reads the task and context, picks the target file, writes RTL
│   └── port_analyzer.py       Unused-port detection (currently off)
├── testing/
│   ├── lint_runner.py         Verilator / Icarus compile check
│   └── test_runner.py         Standalone testbenches and in-container harness execution
└── utils/logger.py
```


## Configuration

Set at build time through `build_agent.sh` or `--build-arg`:

| Variable | Default | Meaning |
|---|---|---|
| `API_TYPE` | `slm` | `slm`, `openai` or `claude` |
| `SLM_MODEL` | `phi` | Model name sent to the API or server |
| `SLM_PORT` | `8001` | Port of the local model server, `slm` mode only. Second argument of `build_agent.sh` |
| `SLM_MAX_LENGTH` | `32768` | Maximum output tokens. Also sets the context budget. Lowered automatically to the output limit of OpenAI models that have a smaller one |
| `SLM_TIMEOUT` | `1800` | Model request timeout in seconds |
| `SLM_TEMPERATURE` | `0.7` | Sampling temperature |
| `SLM_TOP_P` | `0.95` | Nucleus sampling. Not sent to Claude |

Set in code, which needs a rebuild to change:

| Setting | Value | Where |
|---|---|---|
| `max_iterations` | 5 | `main.py` |
| `test_timeout` | 180 s | `config/settings.py` |
| `lint_timeout` | 30 s | `config/settings.py` |

Set in the root `.env`, read by the harness:

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_USER_KEY` | none | OpenAI key, passed to the agent |
| `CLAUDE_API_KEY` / `ANTHROPIC_API_KEY` | none | Claude key, passed to the agent |
| `CLAUDE_API_URL` | Anthropic API | Claude endpoint, passed to the agent |
| `SLM_API_URL` | none | Overrides the local server URL built into the agent image |
| `DOCKER_TIMEOUT_AGENT` | 1000 | Seconds allowed per agent container |
| `DOCKER_TIMEOUT` | 180 | Seconds allowed per harness container. Upstream default is 600 |
| `DOCKER_MEMORY_THRESHOLD_PERCENT` | 90 | Kill a harness container when host memory use passes this |
| `RESTORE_OVERWRITE_EXISTING` | false | Overwrite existing harness files when re-preparing a run directory |

## Features that are currently switched off

These exist in the code but do not run.

| Feature | State | To re-enable |
|---|---|---|
| **Port-usage validation**: after tests pass, check that every input is read and every output is driven, and ask the model to fix unused ports | `enable_port_validation=False` in `main.py`, and the block that uses it is commented out in `core/refinement_loop.py`. The commented code calls `test_runner.run()` with an outdated signature | Uncomment and update the block, then set the flag |
| **Few-shot examples** in the first prompt | `use_few_shot_examples=False` in `main.py` | Set the flag to `True` |
| **Error categorization** (syntax, logic, etc.) to tailor the refinement prompt | Call commented out in `core/refinement_loop.py`; `TestRunner.categorize_errors` still exists | Uncomment the call and pass the category to the prompt builder |
| **Test-file context** for functional errors | Call to `_get_test_context_if_available` commented out in `prompts/prompt_builder.py` | Uncomment |
| **Returning on lint warnings** before running tests | Commented out in `testing/test_runner.py` | Uncomment |

## Changes to the original benchmark

Compared with upstream `NVlabs/cvdp_benchmark` at commit `8e894cf` (v1.1.0 tooling).

### New command-line options

| Option | File | Effect |
|---|---|---|
| `--start`, `--start-from` | `src/argparse_common.py`, `src/dataset_processor.py` | Resume agent execution from a given problem. Requires `-g` |
| `--evaluate` | `run_benchmark.py` | Re-run only the harness on an existing run directory |
| `--sample <n>` | `run_samples.py` | Re-evaluate one sample and recompute the combined report |
| `-m claude`, `-m claude-sonnet-4-6` | `src/llm_lib/claude_llm.py`, `src/llm_lib/model_factory.py` | Call Claude directly |
| `-m local_server`, `-m localhost8001` | `src/llm_lib/local_server_llm.py`, `src/llm_lib/model_factory.py` | Call a local model server directly |

### Behavior changes

| Change | File | Why |
|---|---|---|
| An existing run directory containing `prompt_response.jsonl` is reused, and preparation is skipped | `src/wrapper.py` | Lets resume and evaluate-only work without wiping agent output |
| Existing harness files are not overwritten during preparation unless `RESTORE_OVERWRITE_EXISTING` is true | `src/repository.py`, `src/config_manager.py` | Same |
| The agent step is called from the wrapper, between preparation and evaluation, instead of from inside `all_prepare` | `src/wrapper.py`, `src/dataset_processor.py` | Control over when the agent runs |
| `OPENAI_USER_KEY`, `CLAUDE_API_KEY`, `ANTHROPIC_API_KEY` and `CLAUDE_API_URL` are passed to the agent container by default when set, in addition to anything named in `CVDP_AGENT_ENV`. `SLM_API_URL` is passed with its host rewritten | `src/dataset_processor.py` | Keys stay in `.env` and out of the image |
| With `--force-agentic-include-harness`, the harness `Dockerfile` is mounted read-only in the agent container, next to `src/` and `docker-compose.yml` | `src/dataset_processor.py` | The agent reads it to see which packages the harness installs |
| `DOCKER_TIMEOUT_AGENT` default raised from 600 to 1000 | `src/config_manager.py` | The agent needs longer than a single harness run |
| The agent container can resolve `host.docker.internal` | `src/dataset_processor.py` | The agent can reach a model server on the host |
| Each problem gets `environment/env.txt` with `PROBLEM_CATEGORY`, `PROBLEM_DIFFICULTY` and `PROBLEM_ID` | `src/repository.py`, `src/dataset_processor.py` | The agent picks its category instruction from this |
| `DOCKER_TIMEOUT` default lowered from 600 to 180 | `src/config_manager.py` | Stops stuck simulations sooner |
| A harness timeout returns exit code 124, and each failed service counts as one error | `src/repository.py` | Timeouts are reported as failures consistently |
| A harness container is killed when host memory use passes `DOCKER_MEMORY_THRESHOLD_PERCENT` | `src/dir_monitor.py` | Protects the machine from runaway simulations |
| JSON in model replies is parsed more leniently: fenced blocks and text around the braces are handled | `src/model_helpers.py` | Local models often wrap JSON in extra text |
| With `-m local_server`, threads are capped to `LOCAL_SERVER_MAX_CONCURRENCY` | `run_benchmark.py` | Avoids overloading a local GPU server |

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/recover_rtl_from_agent_logs.py <run-dir> [--dry-run]` | Rebuilds each problem's `rtl/` from the last "EXTRACTED CODE" block in `reports/<n>_agent.txt`. Replaces existing RTL files |
| `scripts/rename_rtl_from_env_sources.py <run-dir> [--dry-run]` | Renames RTL files to the filename the harness expects, taken from `VERILOG_SOURCES` in each problem's `src/.env` |
| `scripts/metrics_report.py <run-dir> [-o file.html]` | Collects every `rundir/agent_metrics.json` and `raw_result.json` into one HTML page (default `<run-dir>/metrics_report.html`) with tokens, latency, cost and iterations per problem. Cost uses the price table at the top of the script, or `--price-input` / `--price-cached` / `--price-output` in USD per 1M tokens |
| `scripts/separate.py` | Splits a dataset into one `.jsonl` per category. Edit the input and output paths at the top of the file first |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ERROR: OPENAI_API_KEY or OPENAI_USER_KEY environment variable is required` | `OPENAI_USER_KEY` is missing from the root `.env` |
| `ERROR: CLAUDE_API_KEY or ANTHROPIC_API_KEY environment variable is required` | Neither is set in the root `.env` |
| `slm` mode: connection refused or timeout | The model server is not running, is on a different port than the image was built for, or listens only on `127.0.0.1`. Bind it to `0.0.0.0`, or set `SLM_API_URL` |
| The agent uses the wrong model or mode | Both are fixed at build time. Rebuild with `API_TYPE` and `SLM_MODEL` set |
| A fresh run reuses old prepared files | The output directory already exists. Use a new `-p` directory or delete the old one |
| `Unable to find --start marker` | The value given to `--start` does not match any problem in the dataset |
| `--evaluate requires prepared runs file` | The directory has no `prompt_response.jsonl`. Do a normal run first |
| Agent code changes have no effect | The image was not rebuilt |
| Agent container killed before it finishes | Raise `DOCKER_TIMEOUT_AGENT` in the root `.env` |
