from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from database import get_db
from models import Destination

router = APIRouter()


class DestinationResponse(BaseModel):
    id: int
    platform: str
    enabled: bool
    
    class Config:
        from_attributes = True


class ToggleDestinationRequest(BaseModel):
    enabled: bool


@router.get("/user/{user_id}")
async def get_user_destinations(user_id: int, db: AsyncSession = Depends(get_db)):
    """Get all destinations for a user"""
    result = await db.execute(
        select(Destination).where(Destination.user_id == user_id)
    )
    destinations = result.scalars().all()
    
    return [
        DestinationResponse(id=d.id, platform=d.platform, enabled=d.enabled)
        for d in destinations
    ]


@router.patch("/{destination_id}")
async def toggle_destination(
    destination_id: int,
    request: ToggleDestinationRequest,
    db: AsyncSession = Depends(get_db)
):
    """Toggle a destination on/off"""
    result = await db.execute(
        select(Destination).where(Destination.id == destination_id)
    )
    destination = result.scalar_one_or_none()
    
    if not destination:
        raise HTTPException(status_code=404, detail="Destination not found")
    
    destination.enabled = request.enabled
    await db.commit()
    
    return {"status": "success"}


@router.delete("/{destination_id}")
async def remove_destination(destination_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a destination"""
    result = await db.execute(
        select(Destination).where(Destination.id == destination_id)
    )
    destination = result.scalar_one_or_none()
    
    if not destination:
        raise HTTPException(status_code=404, detail="Destination not found")
    
    await db.delete(destination)
    await db.commit()
    
    return {"status": "success"}

