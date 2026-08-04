from __future__ import annotations

import json
import os
from pathlib import Path

from telegram_agent.core.gpu_execution.common.registry import WorkloadDefinition
from telegram_agent.core.gpu_execution.workloads import runner


def test_runner_uses_generic_handler_and_atomically_publishes_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.txt"
    input_path.write_text("payload", encoding="utf-8")
    output_path = tmp_path / "result.txt"
    temporary_output_path = tmp_path / ".result.part"
    failure_path = tmp_path / "failure.json"
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text(
        json.dumps(
            {
                "workload_type": "test.copy",
                "input_path": str(input_path),
                "output_path": str(output_path),
                "temporary_output_path": str(temporary_output_path),
                "failure_path": str(failure_path),
                "parent_process_id": os.getppid(),
                "parameters": {"suffix": "-done"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runner,
        "get_workload_definition",
        lambda workload_type: WorkloadDefinition(
            handler_module="tests.gpu_execution.fake_workload"
        )
        if workload_type == "test.copy"
        else None,
    )

    assert runner.main([str(descriptor_path)]) == 0
    assert output_path.read_text(encoding="utf-8") == "payload-done"
    assert not temporary_output_path.exists()
    assert not failure_path.exists()


def test_runner_classifies_invalid_descriptor(tmp_path: Path) -> None:
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text("{}", encoding="utf-8")

    assert runner.main([str(descriptor_path)]) == runner.EXIT_INVALID_DESCRIPTOR
