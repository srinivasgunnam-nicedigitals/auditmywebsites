# database.py
from sqlalchemy import create_engine, MetaData
from databases import Database
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
import os
from dotenv import load_dotenv

load_dotenv()

# Create database directory if it doesn't exist
os.makedirs("database", exist_ok=True)

# Database Configuration from environment or settings
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./database/sitetoolpro.db"

# Connection arguments
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False, "timeout": 30}

# Connection pooling configuration
engine_kwargs = {
    "connect_args": connect_args,
    "pool_recycle": 3600,
    "echo": False
}

# SQLite: Use NullPool to avoid connection pool exhaustion with many concurrent workers
# PostgreSQL: Use QueuePool with generous limits
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_engine(DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
metadata = MetaData()

# Async database instance (currently unused but kept for future async operations)
database = Database(DATABASE_URL)

# Dependency for FastAPI routes
def get_db():
    """Database session dependency for FastAPI routes"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()