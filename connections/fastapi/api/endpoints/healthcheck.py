from fastapi import APIRouter, Response

router = APIRouter()


@router.get("/healthz/live")
def liveness():
    return Response()


@router.get("/healthz/ready")
def readiness():
    return Response()
