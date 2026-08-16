from __future__ import annotations

import os

from huggingface_hub import snapshot_download


def main() -> None:
    token = os.getenv("HF_TOKEN", "").strip()
    if not token:
        raise RuntimeError("HF_TOKEN is required to download the gated SAM Audio model")
    snapshot_download(
        repo_id=os.getenv("SAM_AUDIO_MODEL", "facebook/sam-audio-small"),
        token=token,
    )


if __name__ == "__main__":
    main()
