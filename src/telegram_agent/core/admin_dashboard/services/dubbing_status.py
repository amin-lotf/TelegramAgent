"""Human-readable dubbing workflow labels for the admin dashboard."""
from __future__ import annotations

_DUBBING_STATUS_LABELS = {
    "source_ready": "Source ready",
    "preparing_inputs": "Preparing inputs / translating",
    "tts_ready": "Ready for speech synthesis",
    "tts_running": "Synthesizing speech (CosyVoice)",
    "sam_ready": "Ready for background separation",
    "sam_running": "Separating original audio (SAM Audio)",
    "assembly_ready": "Ready to mix dubbed audio",
    "assembling": "Mixing dubbed audio into video",
    "ready_for_delivery": "Ready for delivery",
    "cancelling": "Cancelling",
    "cancelled": "Cancelled",
    "failed": "Failed",
}

_ACTIVE_DUBBING = frozenset(
    {
        "source_ready",
        "preparing_inputs",
        "tts_ready",
        "tts_running",
        "sam_ready",
        "sam_running",
        "assembly_ready",
        "assembling",
        "cancelling",
    }
)

_FAILED_DUBBING = frozenset({"failed", "cancelled"})
_COMPLETED_DUBBING = frozenset({"ready_for_delivery"})
_ACTIVE_DELIVERY = frozenset({"pending", "sending"})


def dubbing_status_label(status: str) -> str:
    return _DUBBING_STATUS_LABELS.get(status, status.replace("_", " "))


def dubbing_is_active(status: str) -> bool:
    return status in _ACTIVE_DUBBING


def dubbing_is_failed(status: str) -> bool:
    return status in _FAILED_DUBBING


def dubbing_is_completed(status: str) -> bool:
    return status in _COMPLETED_DUBBING


def delivery_is_active(status: str) -> bool:
    return status in _ACTIVE_DELIVERY
