# TelegramAgent MADLAD Translation

Production translation uses the central GPU worker workload
`madlad.translation.v1`. The worker subprocess loads
`google/madlad400-3b-mt` (4-bit, with optional per-language LoRA) for the job,
then exits so VRAM is released. Copy a language adapter with
`make sync-madlad-weights` if you have one; translation still runs on the base
model when the adapter is missing.

This directory still contains an optional always-on HTTP service for debugging.
It is **not** started by `make up`. Starting it pins ~4.5 GB of VRAM for as
long as the container runs.

## Configure and copy optional LoRA adapters

Copy `.env.madlad.docker.example` to `.env.madlad.docker`, then set
`MADLAD_WEIGHTS_SOURCE_PATH` to the exported adapter directory. The source is
read only when copying; the runtime looks under
`pretrained_models/madlad/<lang>` (for example `pretrained_models/madlad/fa`).

`MADLAD_LOAD_LORA_FOR` is a comma-separated list of target languages that may
use LoRA. The default is `fa`. An adapter is attached only when that language
is listed **and** `adapter_config.json` plus `adapter_model.safetensors` exist.
Missing adapters log a warning and fall back to base MADLAD.

```bash
make sync-madlad-weights
```

`make sync-madlad-weights` copies into `pretrained_models/madlad/fa` by default
(`scripts/sync_madlad_adapter.py --lang es` for another language). Only
`adapter_config.json`, `adapter_model.safetensors`, and optional tokenizer
files are copied. `adapter_meta.json` records the source, timestamp, and SHA-256.

## Optional HTTP service

```bash
make up-madlad
make logs-madlad
```

`make up-madlad` enables the `madlad` Compose profile. The API is available
inside Compose at `http://madlad:8000` and from the host at
`http://127.0.0.1:8003`.

Endpoints: `/health`, `/ready`, `/languages`, `/v1/translate`, and
`/v1/reload-adapter`.

Stop it with `make stop-madlad` before running other GPU jobs on a single GPU.
