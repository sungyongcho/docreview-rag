"""Process-wide async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings

engine = create_async_engine(get_settings().database_url, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)
