class TelegramAuthUnavailableError(Exception):
    pass


class TelegramAuthBadResponseError(Exception):
    pass


class TelegramUserUnauthorizedError(Exception):
    pass


class ContentProcessingUnavailableError(Exception):
    pass


class ContentProcessingBadResponseError(Exception):
    pass

class TelegramIngressUnavailableError(Exception):
    pass


class TelegramIngressBadResponseError(Exception):
    pass


class AgentRuntimeUnavailableError(Exception):
    pass


class AgentRuntimeBadResponseError(Exception):
    pass


class AgentRuntimeBatchConflictError(Exception):
    """Raised when a batch idempotency key conflicts with an existing batch."""


class AgentRuntimeCoordinationError(RuntimeError):
    """Base class for agent-runtime coordination failures."""


class RetryableAgentRuntimeCoordinationError(AgentRuntimeCoordinationError):
    """A coordination failure that can safely be retried."""


class PermanentAgentRuntimeCoordinationError(AgentRuntimeCoordinationError):
    """A coordination failure that must not be retried for the same message."""


class JobCreationError(RuntimeError):
    """Raised when a content-processing job cannot be persisted."""
    pass


class WhisperXBackendUnavailableError(Exception):
    pass


class WhisperXBackendBusyError(RuntimeError):
    def __init__(
        self,
        message: str = "WhisperX backend is busy",
    ) -> None:
        super().__init__(message)

class ContentProcessingError(RuntimeError):
    """Base class for worker-side content processing failures."""


class RetryableContentProcessingError(ContentProcessingError):
    """A failure for which the persisted job can safely be retried."""


class PermanentContentProcessingError(ContentProcessingError):
    """A failure that must end the current processing job."""


class SourceResolutionError(PermanentContentProcessingError):
    pass


class UnsupportedSourceError(SourceResolutionError):
    pass


class TelegramDownloadError(RetryableContentProcessingError):
    pass


class TelegramDownloadPermanentError(PermanentContentProcessingError):
    pass


class StorageError(RetryableContentProcessingError):
    pass


class InvalidDownloadedMediaError(PermanentContentProcessingError):
    pass


class MediaDemuxError(RetryableContentProcessingError):
    """A transient failure while demuxing media with ffmpeg."""


class MediaDemuxPermanentError(PermanentContentProcessingError):
    """A permanent demux failure (missing binary, no audio stream, invalid media)."""


class WhisperXServiceError(RetryableContentProcessingError):
    pass


class WhisperXResponseError(PermanentContentProcessingError):
    pass


class ChunkingServiceError(RetryableContentProcessingError):
    pass


class ChunkingResponseError(PermanentContentProcessingError):
    pass
