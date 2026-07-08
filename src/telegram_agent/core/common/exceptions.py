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