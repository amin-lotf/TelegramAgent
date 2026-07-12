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


class WhisperXServiceError(RetryableContentProcessingError):
    pass


class WhisperXResponseError(PermanentContentProcessingError):
    pass
