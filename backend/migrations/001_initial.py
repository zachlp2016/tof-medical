"""Initial schema. Run once before scaling; no destructive automatic migrations.

Usage: python -m migrations.001_initial
Future schema changes must add reviewed, ordered migrations rather than modifying 001.
"""
from app.config import Settings
from app.db import Base, Database
from app.models import SchemaVersion


def main():
    database = Database(Settings.from_env().database_url)
    Base.metadata.create_all(database.engine)
    with database.session() as session:
        if session.get(SchemaVersion, 1) is None:
            session.add(SchemaVersion(version=1))
    database.engine.dispose()


if __name__ == "__main__":
    main()
