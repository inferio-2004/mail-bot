#!/usr/bin/env python3
"""
Database initialization script for production deployment.
This script creates all necessary tables when deploying to Render.
"""

import os
from dotenv import load_dotenv
from models import engine, Base
from sqlalchemy import text

# Load environment variables
load_dotenv()

def init_database():
    """Initialize database tables"""
    print("Initializing database...")
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully")
    
    # Test database connection
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            print("✅ Database connection test successful")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    
    return True

if __name__ == "__main__":
    if init_database():
        print("🎉 Database initialization completed successfully!")
    else:
        print("💥 Database initialization failed!")
        exit(1)