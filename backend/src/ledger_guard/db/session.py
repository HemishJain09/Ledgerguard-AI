import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# We will connect to the locally running dockerized postgres
# Example connection string: postgresql://postgres:postgres@localhost:5432/ledgerguard
# Defaulting to the credentials defined in backend/docker-compose.yml
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://ledgerguard:securepassword@localhost:5432/ledgerguard")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
