from functools import lru_cache

from app.config import get_settings
from app.services.pipeline import ScoringPipeline
from app.services.scoring import build_scorer
from app.services.transcription import build_transcriber


@lru_cache
def get_pipeline() -> ScoringPipeline:
    settings = get_settings()
    return ScoringPipeline(settings, build_scorer(settings), build_transcriber(settings))
