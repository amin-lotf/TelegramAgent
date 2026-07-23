from telegram_agent.core.chunking.services.transcript_chunking import TranscriptChunkingService


def get_transcript_chunking_service() -> TranscriptChunkingService:
    return TranscriptChunkingService()
