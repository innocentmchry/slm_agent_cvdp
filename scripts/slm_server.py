#!/usr/bin/env python3
"""
Local SLM endpoint for the SLM agent (FastAPI + uvicorn + transformers).

Serves one Hugging Face model per process on:
  POST /generate              the format main_agent/SLM_agent/llm/api_client.py calls
  POST /v1/chat/completions   OpenAI-style, non-streaming
  GET  /health

Usage:
  python slm_server.py --model gemma4-12b
  python slm_server.py --model phi4-reasoning --port 8001
  python slm_server.py --model gpt-oss-20b --reasoning-effort low
  python slm_server.py --model some-org/some-model        # any HF repo id works
  python slm_server.py --list

Every flag also has an environment variable (SLM_MODEL, SLM_PORT, HF_HOME, ...),
so `SLM_MODEL=phi4-reasoning python slm_server.py` is equivalent.

Requires: pip install torch transformers accelerate fastapi uvicorn
          (plus bitsandbytes for --quant 4bit/8bit, and kernels for gpt-oss)
"""

import argparse
import atexit
import getpass
import os
import re
import subprocess
import threading
import time
import uuid

# ---------------------------------------------------------------------------
# Model registry: add a model by adding one entry here.
#   repo             Hugging Face repo id
#   loader           transformers Auto class to load with (default AutoModelForCausalLM)
#   think            (start, end) tokens around the model's reasoning. When set, the
#                    reasoning is returned in a separate `reasoning` field instead of
#                    inside the text. Its tokens are counted either way.
#   format           "harmony" for models that answer in OpenAI's harmony channels
#                    (reasoning in `analysis`, answer in `final`); replaces `think`
#   thinking_switch  chat template argument that turns reasoning on and off, for models
#                    where it is optional (see --thinking)
#   effort_switch    chat template argument that sets how much the model reasons
#                    (see --reasoning-effort)
#   dtype            weight type to load with when --dtype is not given (default bfloat16)
#   system           optional default system prompt
# ---------------------------------------------------------------------------
MODELS = {
    "gemma4-12b": {
        "repo": "google/gemma-4-12B-it",
        "loader": "AutoModelForMultimodalLM",
        "think": ("<|channel>", "<channel|>"),
        "thinking_switch": "enable_thinking",
    },
    "gpt-oss-20b": {
        "repo": "openai/gpt-oss-20b",
        "format": "harmony",
        "effort_switch": "reasoning_effort",
        "dtype": "auto",  # keeps the released MXFP4 weights when the `kernels` package is installed
    },
    "phi4-reasoning": {
        "repo": "microsoft/Phi-4-reasoning",
        "think": ("<think>", "</think>"),
    },
}
DEFAULT_MODEL = "gemma4-12b"


def parse_args():
    env = os.environ.get
    p = argparse.ArgumentParser(description="Serve a Hugging Face model for the SLM agent")
    p.add_argument("--model", default=env("SLM_MODEL", DEFAULT_MODEL),
                   help="registry alias (see --list) or any Hugging Face repo id")
    p.add_argument("--host", default=env("SLM_HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(env("SLM_PORT", "8001")))
    p.add_argument("--hf-home", default=env("HF_HOME", f"/scratch/{getpass.getuser()}/huggingface"),
                   help="where Hugging Face downloads and caches models")
    p.add_argument("--quant", choices=["none", "4bit", "8bit"], default=env("SLM_QUANT", "none"),
                   help="bitsandbytes quantization, for when the model does not fit in VRAM")
    p.add_argument("--dtype", choices=["auto", "bfloat16", "float16", "float32"], default=env("SLM_DTYPE"),
                   help="weight type (default: the registry entry's, else bfloat16)")
    p.add_argument("--max-new-tokens", type=int, default=int(env("SLM_MAX_NEW_TOKENS", "4096")),
                   help="used when a request does not give a limit")
    p.add_argument("--max-time", type=float, default=float(env("SLM_MAX_TIME", "600")),
                   help="seconds allowed per generation; the output is cut off after that (0: no limit)")
    p.add_argument("--context-window", type=int, default=int(env("SLM_CONTEXT_WINDOW", "0")),
                   help="prompt + output token limit (default: read from the model config)")
    p.add_argument("--system", default=env("SLM_SYSTEM_PROMPT"),
                   help="system prompt (overrides the registry entry)")
    p.add_argument("--thinking", choices=["on", "off"], default=env("SLM_THINKING", "off"),
                   help="reasoning mode, for models where it is optional (Gemma). "
                        "Models that always reason (Phi-4-reasoning) ignore this")
    p.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default=env("SLM_REASONING_EFFORT"),
                   help="how much the model reasons, for models with that setting (gpt-oss; "
                        "its own default is medium)")
    p.add_argument("--keep-think", action="store_true",
                   help="leave <think> blocks inside the returned text")
    p.add_argument("--list", action="store_true", help="list registry aliases and exit")
    return p.parse_args()


args = parse_args()

if args.list:
    for alias, cfg in MODELS.items():
        print(f"{alias:20s} {cfg['repo']}")
    raise SystemExit(0)

# HF_HOME must be set before transformers / huggingface_hub are imported.
os.makedirs(args.hf_home, exist_ok=True)
os.environ["HF_HOME"] = args.hf_home

import torch  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402
import transformers  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

model_cfg = MODELS.get(args.model, {"repo": args.model})
REPO = model_cfg["repo"]
SYSTEM_PROMPT = args.system or model_cfg.get("system")
THINK_START, THINK_END = model_cfg.get("think", ("<think>", "</think>"))
HARMONY = model_cfg.get("format") == "harmony"
STRIP_THINK = ("think" in model_cfg or HARMONY) and not args.keep_think
DTYPE = args.dtype or model_cfg.get("dtype", "bfloat16")
# Extra chat template arguments, e.g. {"enable_thinking": True}
TEMPLATE_KWARGS = {}
if "thinking_switch" in model_cfg:
    TEMPLATE_KWARGS[model_cfg["thinking_switch"]] = args.thinking == "on"
if "effort_switch" in model_cfg and args.reasoning_effort:
    TEMPLATE_KWARGS[model_cfg["effort_switch"]] = args.reasoning_effort


def load_model():
    dtype = DTYPE if DTYPE == "auto" else getattr(torch, DTYPE)
    kwargs = {"device_map": "auto", "torch_dtype": dtype}
    if args.quant != "none":
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=args.quant == "4bit",
            load_in_8bit=args.quant == "8bit",
            bnb_4bit_compute_dtype=torch.bfloat16 if DTYPE == "auto" else dtype,
        )

    print(f"Loading {REPO} (transformers {transformers.__version__}, cache: {args.hf_home}, dtype: {DTYPE}, quant: {args.quant})")
    tokenizer = AutoTokenizer.from_pretrained(REPO)
    loader = model_cfg.get("loader", "AutoModelForCausalLM")
    if not hasattr(transformers, loader):
        raise SystemExit(f"transformers {transformers.__version__} has no {loader}: "
                         f"{REPO} needs a newer version (pip install -U transformers)")
    model = getattr(transformers, loader).from_pretrained(REPO, **kwargs)
    model.eval()

    # device_map="auto" silently puts layers on the CPU or disk when the GPU is short of
    # free memory, which makes generation many times slower.
    devices = {str(d) for d in getattr(model, "hf_device_map", {}).values()} or {str(model.device)}
    print(f"Model placed on: {', '.join(sorted(devices))}")
    if devices & {"cpu", "disk"} or not torch.cuda.is_available():
        print("WARNING: part of the model is NOT on a GPU. Generation will be very slow. "
              "Check free GPU memory with nvidia-smi.")
    return tokenizer, model


class GpuMonitor:
    """Samples GPU power and utilization once a second with nvidia-smi, in a background thread.

    Covers the GPUs this process has memory on. The readings are for the whole GPU, so
    they include any other process running on it.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.energy_j = 0.0   # joules since start, summed over the GPUs
        self.util_s = 0.0     # utilization percent x seconds, summed over the GPUs
        self.last_seen = {}   # GPU uuid -> time of its previous sample
        self.started = time.time()
        self.uuids = self._own_gpus()
        threading.Thread(target=self._run, daemon=True).start()

    @staticmethod
    def _own_gpus():
        """UUIDs of the GPUs this process uses. Empty set: unknown, so all GPUs are counted."""
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return set()
        rows = [line.split(",") for line in out.splitlines() if "," in line]
        return {uuid.strip() for pid, uuid in rows if pid.strip() == str(os.getpid())}

    def _run(self):
        try:
            proc = subprocess.Popen(
                ["nvidia-smi", "--query-gpu=uuid,power.draw,utilization.gpu",
                 "--format=csv,noheader,nounits", "-l", "1"],
                stdout=subprocess.PIPE, text=True)
        except OSError as e:
            print(f"GPU monitoring is off: could not start nvidia-smi ({e})")
            return
        atexit.register(proc.terminate)  # do not leave nvidia-smi running after the server exits
        for line in proc.stdout:
            try:
                gpu, power, util = (field.strip() for field in line.split(","))
                power, util = float(power), float(util)
            except ValueError:
                continue  # e.g. "[N/A]" on GPUs that do not report power
            if self.uuids and gpu not in self.uuids:
                continue
            now = time.time()
            with self.lock:
                previous = self.last_seen.get(gpu)
                if previous is not None and now - previous < 30:
                    self.energy_j += power * (now - previous)
                    self.util_s += util * (now - previous)
                self.last_seen[gpu] = now

    def snapshot(self):
        with self.lock:
            return self.energy_j, self.util_s, len(self.last_seen)


tokenizer, model = load_model()
gpu_monitor = GpuMonitor()  # after loading, so it can see which GPUs the model is on
gpu_lock = threading.Lock()  # one generation at a time
# Prompt and output must fit in this many tokens together. None: unknown, no limit applied.
# Multimodal models keep the limit in the config of their text part.
CONTEXT_WINDOW = (args.context_window
                  or getattr(model.config, "max_position_embeddings", None)
                  or getattr(getattr(model.config, "text_config", None), "max_position_embeddings", None))
print(f"Context window: {CONTEXT_WINDOW or 'unknown'} tokens")


def token_id(token):
    """Id of a token that is in the vocabulary as a single token, else -1."""
    tid = tokenizer.convert_tokens_to_ids(token)
    return -1 if tid is None or tid == tokenizer.unk_token_id else tid


THINK_START_ID = token_id(THINK_START)
THINK_END_ID = token_id(THINK_END)
eos = model.generation_config.eos_token_id
EOS_IDS = set(eos if isinstance(eos, list) else [eos])


def clean_reasoning(text):
    text = text.replace(THINK_START, "").replace(THINK_END, "").strip()
    return text.removeprefix("thought").strip()  # Gemma labels its reasoning channel "thought"


def split_reasoning(new_tokens):
    """Split generated tokens at the end of the reasoning. Returns (reasoning, answer, reasoning_tokens)."""
    if THINK_END_ID in new_tokens:
        cut = len(new_tokens) - new_tokens[::-1].index(THINK_END_ID)
        reasoning = tokenizer.decode(new_tokens[:cut], skip_special_tokens=True)
        answer = tokenizer.decode(new_tokens[cut:], skip_special_tokens=True)
        return clean_reasoning(reasoning), answer.strip(), cut

    text = tokenizer.decode(new_tokens, skip_special_tokens=True)
    if THINK_END in text:
        # The end marker is not a single token for this model: split the text instead
        reasoning, answer = text.rsplit(THINK_END, 1)
        cut = len(tokenizer(reasoning, add_special_tokens=False)["input_ids"])
        return clean_reasoning(reasoning), answer.strip(), cut
    if THINK_START_ID in new_tokens or THINK_START in text:
        # Cut off while still reasoning: there is no answer
        return clean_reasoning(text), "", len(new_tokens)
    return "", text.strip(), 0


def split_harmony(new_tokens):
    """Same as split_reasoning, for the harmony format:
    <|channel|>analysis<|message|>REASONING<|end|><|start|>assistant<|channel|>final<|message|>ANSWER<|return|>
    """
    raw = tokenizer.decode(new_tokens, skip_special_tokens=False)
    reasoning = "\n".join(
        re.findall(r"<\|channel\|>analysis<\|message\|>(.*?)(?:<\|end\|>|$)", raw, re.DOTALL)).strip()
    final = re.search(r"<\|channel\|>final<\|message\|>(.*?)(?:<\|return\|>|<\|end\|>|$)", raw, re.DOTALL)
    if not final:
        if "<|channel|>" not in raw:
            # No channels at all: treat the whole output as the answer
            return "", tokenizer.decode(new_tokens, skip_special_tokens=True).strip(), 0
        # Cut off while still reasoning: there is no answer
        return reasoning, "", len(new_tokens)
    cut = len(new_tokens) - new_tokens[::-1].index(token_id("<|message|>"))
    return reasoning, final.group(1).strip(), cut


def generate(messages, max_new_tokens=None, temperature=None, top_p=None):
    """Run one chat completion. Returns a dict with the text, reasoning and token counts."""
    if SYSTEM_PROMPT and not any(m["role"] == "system" for m in messages):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True, **TEMPLATE_KWARGS
    ).to(model.device)
    prompt_tokens = inputs["input_ids"].shape[1]

    max_new_tokens = max_new_tokens or args.max_new_tokens
    if CONTEXT_WINDOW:
        room = CONTEXT_WINDOW - prompt_tokens
        if room <= 0:
            raise HTTPException(status_code=400, detail=(
                f"Prompt is {prompt_tokens} tokens, which fills the {CONTEXT_WINDOW}-token context window"))
        if max_new_tokens > room:
            print(f"Output limited to {room} tokens (asked for {max_new_tokens}): "
                  f"prompt is {prompt_tokens} of {CONTEXT_WINDOW} context tokens")
            max_new_tokens = room
    gen_kwargs = {"max_new_tokens": max_new_tokens}
    if args.max_time:
        gen_kwargs["max_time"] = args.max_time
    if temperature is not None and temperature <= 0:
        gen_kwargs["do_sample"] = False
    else:
        gen_kwargs["do_sample"] = True
        if temperature is not None:
            gen_kwargs["temperature"] = temperature
        if top_p is not None:
            gen_kwargs["top_p"] = top_p

    with gpu_lock, torch.inference_mode():
        gpu_count = torch.cuda.device_count()
        for i in range(gpu_count):
            torch.cuda.reset_peak_memory_stats(i)
        energy_before, util_before, _ = gpu_monitor.snapshot()
        start = time.time()
        output = model.generate(**inputs, **gen_kwargs)
        elapsed = max(time.time() - start, 1e-9)
        energy_after, util_after, monitored_gpus = gpu_monitor.snapshot()
        peak_memory_mb = sum(torch.cuda.max_memory_allocated(i) for i in range(gpu_count)) / 2**20

    new_tokens = output[0][prompt_tokens:].tolist()
    # GPU readings are sampled once a second, so they are coarse for calls of a few seconds.
    gpu = {"gpu_energy_j": None, "gpu_avg_power_w": None, "gpu_avg_util_pct": None,
           "gpu_peak_memory_mb": round(peak_memory_mb) if gpu_count else None}
    if monitored_gpus:
        energy_j = energy_after - energy_before
        gpu.update({
            "gpu_energy_j": round(energy_j, 1),
            "gpu_avg_power_w": round(energy_j / elapsed, 1),
            "gpu_avg_util_pct": round((util_after - util_before) / elapsed / monitored_gpus, 1),
        })
    print(f"Generated {len(new_tokens)} tokens in {elapsed:.1f}s ({len(new_tokens) / elapsed:.1f} tokens/s), "
          f"prompt {prompt_tokens} tokens, GPU {gpu['gpu_avg_power_w']} W avg, {gpu['gpu_peak_memory_mb']} MB peak")
    reasoning, answer, reasoning_tokens = (split_harmony if HARMONY else split_reasoning)(new_tokens)
    return {
        "text": answer if STRIP_THINK else tokenizer.decode(new_tokens, skip_special_tokens=True).strip(),
        "reasoning": reasoning,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": len(new_tokens),  # includes the reasoning tokens
        "reasoning_tokens": reasoning_tokens,
        # Stopped by the token or time limit unless the model ended the turn itself
        "finish_reason": "stop" if new_tokens and new_tokens[-1] in EOS_IDS else "length",
        **gpu,
    }


app = FastAPI(title=f"SLM server ({REPO})")


class GenerateRequest(BaseModel):
    prompt: str
    max_length: int | None = None  # treated as max new tokens
    model: str | None = None       # ignored: this process serves one model
    temperature: float | None = None
    top_p: float | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None


def run(messages, max_new_tokens, temperature, top_p):
    try:
        return generate(messages, max_new_tokens, temperature, top_p)
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        raise HTTPException(status_code=507, detail=f"CUDA out of memory: {e}")


@app.get("/health")
def health():
    energy_j, _, monitored_gpus = gpu_monitor.snapshot()
    return {
        "status": "ok", "model": REPO, "context_window": CONTEXT_WINDOW, **TEMPLATE_KWARGS,
        # Everything the monitored GPUs drew since the server started, idle time included
        "uptime_s": round(time.time() - gpu_monitor.started),
        "gpu_energy_wh": round(energy_j / 3600, 2) if monitored_gpus else None,
        "monitored_gpus": monitored_gpus,
    }


# Plain `def` endpoints run in FastAPI's threadpool, so /health stays responsive
# while a generation is in progress.
@app.post("/generate")
def generate_endpoint(req: GenerateRequest):
    start = time.time()
    out = run(
        [{"role": "user", "content": req.prompt}], req.max_length, req.temperature, req.top_p
    )
    return {
        "generated_text": out.pop("text"),
        "model": REPO,
        **out,
        "elapsed_s": round(time.time() - start, 2),
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest):
    out = run(
        [m.model_dump() for m in req.messages], req.max_tokens, req.temperature, req.top_p
    )
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": REPO,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": out["text"], "reasoning_content": out["reasoning"]},
            "finish_reason": out["finish_reason"],
        }],
        "usage": {
            "prompt_tokens": out["prompt_tokens"],
            "completion_tokens": out["completion_tokens"],
            "total_tokens": out["prompt_tokens"] + out["completion_tokens"],
            "completion_tokens_details": {"reasoning_tokens": out["reasoning_tokens"]},
        },
    }


if __name__ == "__main__":
    uvicorn.run(app, host=args.host, port=args.port)
