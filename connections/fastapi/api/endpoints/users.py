import bcrypt
from fastapi import APIRouter, HTTPException, status

from connections.database.users import Users
from connections.models.db.requests import UserCreateRequest, UserVerifyRequest
from connections.models.db.responses import UserItem

router = APIRouter()


@router.get("/users", response_model=list[UserItem])
async def list_users():
    """Return all users (email + name only, no password hash)."""
    return [UserItem(email=u.email, name=u.name) for u in Users.get_all()]


@router.post("/users", status_code=status.HTTP_201_CREATED, response_model=UserItem)
async def create_user(body: UserCreateRequest):
    """Register a new user. Returns 409 if email already exists."""
    if Users.get_by_email(body.email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email already registered: {body.email}",
        )
    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = Users.add_user(
        email=body.email,
        password_hash=password_hash,
        name=body.name,
        role=body.role,
    )
    return UserItem(email=user.email, name=user.name)


@router.post("/users/verify", response_model=UserItem)
async def verify_user(body: UserVerifyRequest):
    """Verify email + plaintext password. Returns 401 if invalid."""
    user = Users.get_by_email(body.email)
    if user is None or not bcrypt.checkpw(
        body.password.encode(), user.password_hash.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return UserItem(email=user.email, name=user.name)
