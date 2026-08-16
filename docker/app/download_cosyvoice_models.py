from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    model_id = os.getenv(
        "COSYVOICE_MODEL_ID", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
    )
    model_dir = Path(
        os.getenv(
            "COSYVOICE_MODEL_DIR",
            "/opt/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B",
        )
    )
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=model_id, local_dir=model_dir)
    if not (model_dir / "cosyvoice3.yaml").is_file():
        raise RuntimeError(f"CosyVoice model is incomplete: {model_dir}")


if __name__ == "__main__":
    main()
