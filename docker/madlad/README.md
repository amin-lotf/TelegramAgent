# TelegramAgent MADLAD Translation

Production translation uses the central GPU worker workload
`madlad.translation.v1`. The worker subprocess loads
`google/madlad400-3b-mt` (4-bit + LoRA) for the job, then exits so VRAM is
released. Copy the adapter with `make sync-madlad-weights` before the first
translation job.

This directory still contains an optional always-on HTTP service for debugging.
It is **not** started by `make up`. Starting it pins ~4.5 GB of VRAM for as
long as the container runs.

## Configure and copy the adapter

Copy `.env.madlad.docker.example` to `.env.madlad.docker`, then set
`MADLAD_WEIGHTS_SOURCE_PATH` to the exported adapter directory. The source is
read only when copying; the runtime uses the copy under
`pretrained_models/madlad/adapter`.

```bash
make sync-madlad-weights
```

Only `adapter_config.json`, `adapter_model.safetensors`, and optional tokenizer
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
