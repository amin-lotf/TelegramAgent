from fastapi import APIRouter

from telegram_agent.core.gpu_execution.api.v1.jobs.router import router as jobs_router


api_router = APIRouter()
api_router.include_router(jobs_router)
