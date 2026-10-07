from sqlalchemy import create_engine
from ares.adapters.db import Base
engine = create_engine('sqlite:///.data/ares-dev.sqlite3')
Base.metadata.create_all(engine)
print("Tables created.")
