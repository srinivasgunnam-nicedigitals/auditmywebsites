# database.py
from sqlalchemy import create_engine, MetaData
from databases import Database
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

# Create database directory if it doesn't exist
os.makedirs("database", exist_ok=True)

# Database Configuration from environment or settings
DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./sitetoolpro.db"

# Connection arguments
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Connection pooling configuration
engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_size=10 if not DATABASE_URL.startswith("sqlite") else None,
    max_overflow=20 if not DATABASE_URL.startswith("sqlite") else None,
    pool_recycle=3600,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
metadata = MetaData()

# Async database instance (currently unused but kept for future async operations)
database = Database(DATABASE_URL)