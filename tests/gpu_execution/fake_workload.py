from pathlib import Path


class FakeWorkload:
    def execute(self, *, input_path: Path, output_path: Path, parameters):
        output_path.write_text(
            input_path.read_text(encoding="utf-8") + str(parameters.get("suffix", "")),
            encoding="utf-8",
        )


def create_handler() -> FakeWorkload:
    return FakeWorkload()
