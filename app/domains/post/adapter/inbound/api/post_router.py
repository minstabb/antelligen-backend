from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.post.adapter.outbound.persistence.post_repository_impl import PostRepositoryImpl
from app.domains.post.application.request.create_post_request import CreatePostRequest
from app.domains.post.application.response.create_post_response import CreatePostResponse
from app.domains.post.application.usecase.create_post_usecase import CreatePostUseCase
from app.infrastructure.database.database import get_db

router = APIRouter(prefix="/post", tags=["Post"])


@router.post("", response_model=CreatePostResponse, status_code=201)
async def create_post(
    request: CreatePostRequest,
    db: AsyncSession = Depends(get_db),
):
    repository = PostRepositoryImpl(db)
    usecase = CreatePostUseCase(repository)
    return await usecase.execute(request)
