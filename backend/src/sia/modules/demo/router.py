"""HTTP route for sample data."""

from fastapi import APIRouter, status

from sia.core.db import DbSession
from sia.modules.demo import service
from sia.modules.demo.service import SampleDataOut
from sia.modules.identity.dependencies import AdminTenant

router = APIRouter(tags=["demo"])


@router.post("/sample-data", status_code=status.HTTP_201_CREATED)
async def load_sample_data(tenant: AdminTenant, db: DbSession) -> SampleDataOut:
    """Fill an EMPTY workspace with fictional sample companies (admins). No AI calls are made:
    AI content, when available, was generated once in advance."""
    return await service.load_sample_data(db, tenant)
