from __future__ import annotations

import ctypes
import importlib
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from telegram_agent.core.gpu_execution.common.registry import get_workload_definition
from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadPermanentError,
    GpuWorkloadRetryableError,
)


EXIT_PERMANENT_FAILURE = 20
EXIT_RETRYABLE_FAILURE = 21
EXIT_CUDA_OUT_OF_MEMORY = 22
EXIT_INVALID_DESCRIPTOR = 23

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _write_failure(path: Path | None, *, kind: str, message: str) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
        temporary.write_text(
            json.dumps({"kind": kind, "message": message[:4000]}),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    except OSError:
        return


def _is_cuda_out_of_memory(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return (
        "outofmemory" in name
        or "cuda out of memory" in message
        or ("cuda" in message and "out of memory" in message)
    )


def _load_descriptor(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GPU workload descriptor must contain a JSON object")
    return payload


def _set_parent_death_signal(expected_parent_process_id: int) -> None:
    """Ensure a lost executor parent cannot leave a model process orphaned."""
    try:
        libc = ctypes.CDLL(None)
        libc.prctl(1, signal.SIGTERM)
    except (AttributeError, OSError):
        return
    if os.getppid() != expected_parent_process_id:
        raise GpuWorkloadRetryableError(
            "GPU executor parent exited before the workload child initialized"
        )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        print("usage: python -m ...workloads.runner DESCRIPTOR_PATH", file=sys.stderr)
        return EXIT_INVALID_DESCRIPTOR

    failure_path: Path | None = None
    try:
        descriptor = _load_descriptor(Path(arguments[0]))
        workload_type = str(descriptor["workload_type"])
        input_path = Path(str(descriptor["input_path"]))
        output_path = Path(str(descriptor["output_path"]))
        temporary_output_path = Path(str(descriptor["temporary_output_path"]))
        failure_path = Path(str(descriptor["failure_path"]))
        parent_process_id = int(descriptor["parent_process_id"])
        raw_parameters = descriptor.get("parameters", {})
        if not isinstance(raw_parameters, dict):
            raise ValueError("GPU workload parameters must be a JSON object")
        definition = get_workload_definition(workload_type)
        if definition is None:
            raise ValueError(f"Unsupported GPU workload type: {workload_type}")
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _write_failure(failure_path, kind="invalid_input", message=str(exc))
        return EXIT_INVALID_DESCRIPTOR

    try:
        _set_parent_death_signal(parent_process_id)
        logger.info(
            "gpu_workload_start job_id=%s workload_type=%s",
            descriptor.get("job_id", "-"),
            workload_type,
        )
        module = importlib.import_module(definition.handler_module)
        handler = module.create_handler()
        temporary_output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_output_path.unlink(missing_ok=True)
        handler.execute(
            input_path=input_path,
            output_path=temporary_output_path,
            parameters=raw_parameters,
        )
        if (
            temporary_output_path.is_symlink()
            or not temporary_output_path.is_file()
            or temporary_output_path.stat().st_size <= 0
        ):
            raise GpuWorkloadRetryableError(
                "GPU workload did not produce a valid output file"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary_output_path, output_path)
        logger.info(
            "gpu_workload_succeeded job_id=%s workload_type=%s",
            descriptor.get("job_id", "-"),
            workload_type,
        )
        return 0
    except GpuWorkloadPermanentError as exc:
        logger.error("gpu_workload_permanent_failure: %s", exc)
        _write_failure(failure_path, kind="workload_error", message=str(exc))
        return EXIT_PERMANENT_FAILURE
    except GpuWorkloadRetryableError as exc:
        logger.error("gpu_workload_retryable_failure: %s", exc)
        _write_failure(failure_path, kind="workload_error", message=str(exc))
        return EXIT_RETRYABLE_FAILURE
    except BaseException as exc:
        logger.exception("gpu_workload_crashed")
        if _is_cuda_out_of_memory(exc):
            _write_failure(
                failure_path,
                kind="cuda_out_of_memory",
                message=f"{type(exc).__name__}: {exc}",
            )
            return EXIT_CUDA_OUT_OF_MEMORY
        _write_failure(
            failure_path,
            kind="crash",
            message=f"{type(exc).__name__}: {exc}",
        )
        return EXIT_RETRYABLE_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
