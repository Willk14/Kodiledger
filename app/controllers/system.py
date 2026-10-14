from fastapi import APIRouter


router = APIRouter(tags=["System"])


@router.get("/")
async def root() -> dict[str, str]:
    return {
        "status": "online",
        "system": "KodiFlow Backend Engine",
    }
