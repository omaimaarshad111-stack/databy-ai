from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas.auth import TokenResponse, UserLogin, UserRegister


class DuplicateUserError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def register_user(db: Session, registration: UserRegister) -> User:
    user = User(
        username=registration.username,
        email=str(registration.email),
        hashed_password=hash_password(registration.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(User.id).where(
                (User.username == registration.username)
                | (User.email == str(registration.email))
            )
        )
        if duplicate is not None:
            raise DuplicateUserError from exc
        raise
    db.refresh(user)
    return user


def authenticate_user(db: Session, credentials: UserLogin) -> TokenResponse:
    user = db.scalar(
        select(User).where(User.email == str(credentials.email))
    )
    if (
        user is None
        or not user.is_active
        or not verify_password(credentials.password, user.hashed_password)
    ):
        raise InvalidCredentialsError
    return TokenResponse(access_token=create_access_token(user.id))
