"""Authenticated metadata for operator-provisioned offline dictionaries."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from dq_scoring.adapters.compute.spelling_dictionary import SpellingDictionaryManager
from dq_scoring.presentation.api.auth import AuthenticatedUser
from dq_scoring.presentation.api.dependencies import get_current_user

router = APIRouter(prefix="/api/v1", tags=["Text Quality"])


class TextDictionaryResponse(BaseModel):
    status: str
    revision: str | None
    languages: list[str]
    error_code: str | None


@router.get("/text-dictionaries", response_model=TextDictionaryResponse)
def text_dictionaries(current_user: AuthenticatedUser = Depends(get_current_user)):
    return SpellingDictionaryManager().get_status()
