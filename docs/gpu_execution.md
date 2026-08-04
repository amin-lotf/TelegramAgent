# Central GPU execution

## Purpose

`gpu_execution` is the only runtime component allowed to schedule GPU-bound
work in the composed deployment. It is an independently owned service with its
own PostgreSQL database, API, Celery application, outbox, and migration chain.
CPU services submit durable jobs and observe their status; they do not select a
GPU, start model servers, or coordinate with other GPU consumers.

The deployed GPU worker is intentionally a model-free parent process. It listens
to one Redis/Celery queue with `--pool=solo --concurrency=1` and starts one child
process for each logical job. The child imports one registered workload module,
loads that workload's model, processes all internal chunks or segments, writes
its output atomically, and exits. CUDA allocations and model-owned system memory
therefore disappear at the process boundary before the queue advances.

The worker image contains the dependencies for the currently registered
workloads, but no process imports all models together. If dependency conflicts
eventually make one image impractical, a registry entry may point at a different
executable or container launcher without changing the job/API/persistence
contracts; global serialization must remain at the single `gpu_execution` queue.

## Durable lifecycle

`gpu_jobs` is authoritative. Its externally visible states are:

- `pending`: accepted transactionally with an outbox delivery record.
- `running`: atomically claimed with worker identity, child PID, heartbeat, and
  an expiring lease.
- `succeeded`: the final output exists outside the child and passed generic
  output validation.
- `retrying`: a retryable crash, CUDA OOM, timeout, or lost lease persisted a
  future delivery in the same transaction.
- `failed`: invalid input, a permanent workload error, or exhausted attempts.
- `canceled`: canceled before start, or after a running child process was
  terminated and reaped.

API submission is idempotent through `Idempotency-Key`. Reusing a key for
different paths, workload parameters, timeout, or retry policy is rejected.
Each retry uses the same stable final output path and a unique `.part` file. A
child atomically renames the part file only after successful completion. A
worker crash can therefore leave only a disposable part file; it cannot expose
a partially written final result. If a child completed the rename immediately
before its parent crashed, the next claim validates and adopts that final file
without repeating inference.

Celery delivers only the GPU job UUID. Audio, manifests, model tensors, and
results never pass through Redis. Input manifests, clips, control descriptors,
logs, part files, and final outputs live below `GPU_SHARED_STORAGE_ROOT`, mounted
into both the caller and GPU execution containers.

## Failure and cancellation behavior

The parent heartbeats while polling the child. It terminates the entire child
process group on cancellation or timeout, waits `GPU_JOB_CANCEL_GRACE_SECONDS`,
then sends `SIGKILL` if necessary. Linux `PR_SET_PDEATHSIG` also asks the kernel
to terminate the child if the Celery parent dies unexpectedly. Container
termination kills both processes as an additional isolation boundary.

The recovery beat scans expired `running` leases. It transitions them to
`retrying` with a new transactional outbox delivery, or to `failed` after the
attempt limit. Child exit metadata distinguishes permanent input/workload
failures, retryable crashes, timeouts, and CUDA out-of-memory failures. Logs and
the small structured failure sidecar remain in
`<shared-root>/.gpu-control/<job-id>/attempt-<n>/` for diagnosis.

Cancel a job through:

```http
POST /api/v1/jobs/{gpu_job_id}/cancel
Authorization: Bearer <GPU_EXECUTION_SERVICE_TOKEN>
```

Pending/retrying jobs become canceled immediately. A running job records the
request first; its owning worker then terminates and reaps the process before it
records the terminal canceled state.

## Current integrations

`whisperx.transcription` accepts one media path and writes the verbose transcript
JSON consumed by content processing. One child owns transcription, alignment,
and diarization for the complete media job.

`sensevoice.emotion_batch` accepts a JSON manifest of persistent segment clip
paths. It constructs SenseVoice once, processes every segment in the logical
content job, writes one result JSON, and exits. This integration is included
because the existing repository configured SenseVoice for CUDA; leaving its old
long-lived container enabled would violate global single-GPU execution.

The old WhisperX and SenseVoice FastAPI source remains reusable for local API
compatibility, but their compose files are no longer included by the root
deployment.

## Adding a workload type

1. Define a stable integration identifier in
   `telegram_agent.core.common.gpu_workloads`. Callers use only this identifier,
   paths, and small JSON parameters.
2. Add a lazy `WorkloadDefinition` entry to
   `gpu_execution.common.registry`. Do not import the handler or its framework
   from the registry.
3. Implement a module under `gpu_execution.workloads` with `create_handler()`.
   Its handler implements `execute(input_path, output_path, parameters)`. The
   supplied output path is an attempt-specific part file on shared storage.
4. Load the model once inside `execute`, process every internal item for that
   logical job, close any external resources, and return only after the complete
   output has been flushed. Raise `GpuWorkloadPermanentError` for invalid input
   and `GpuWorkloadRetryableError` for a cleanly classified transient failure.
   Unhandled CUDA OOM errors are classified by the generic runner.
5. Add the workload dependencies to the `gpu-execution-worker` image. Do not add
   model imports to the API, Celery task, dispatcher, repository, or parent
   execution service.
6. Add a caller-side client adapter in the owning CPU service. That adapter owns
   workload-specific parameters and result decoding. Submit a stable
   idempotency key and paths below the same shared-storage root, then observe the
   durable job to a terminal state.
7. Add runner/adapter tests and a Docker smoke test. Keep the GPU execution
   worker count and concurrency at one unless the architecture is explicitly
   extended to model multiple independently locked GPU devices.

## Deployment

Run `make migrate-gpu-execution` (or start the composed migration service), then
start `gpu-execution`, `gpu-execution-control-worker`, `gpu-execution-beat`, and
exactly one `gpu-execution-worker`. Configure the same
`GPU_EXECUTION_SERVICE_TOKEN` for content processing and GPU execution. The
root compose file supplies development defaults; production must override the
token and database credentials.
