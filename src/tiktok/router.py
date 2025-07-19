from fastapi import APIRouter
from src.tiktok.orders.router import router as orders_router
from src.tiktok.returns.router import router as returns_router
from src.tiktok.shifts.router import router as shifts_router
from src.tiktok.reports.router import router as reports_router

router = APIRouter(tags=["Shifts"])

router.include_router(
    router=orders_router,
    prefix="/orders",
    tags=["Orders"],
)

router.include_router(
    router=returns_router,
    prefix="/returns",
    tags=["Returns"],
)

router.include_router(
    router=shifts_router,
    prefix="/shifts",
    tags=["Shifts"],
)

router.include_router(
    router=reports_router, 
    prefix="/reports", 
    tags=["Reports"],
    # dependencies=[Depends(get_admin_user)]
)