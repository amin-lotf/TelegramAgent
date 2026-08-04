from enum import StrEnum


class GpuJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELED = "canceled"


class GpuOutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"


class GpuFailureKind(StrEnum):
    CRASH = "crash"
    CUDA_OUT_OF_MEMORY = "cuda_out_of_memory"
    INVALID_INPUT = "invalid_input"
    TIMEOUT = "timeout"
    WORKER_LOST = "worker_lost"
    WORKLOAD_ERROR = "workload_error"
