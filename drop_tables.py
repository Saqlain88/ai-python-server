from app import create_app, db
from sqlalchemy import text

app = create_app()

with app.app_context():
    # Drop all tables in the correct order to handle foreign keys
    db.session.execute(text('DROP TABLE IF EXISTS token CASCADE;'))
    db.session.execute(text('DROP TABLE IF EXISTS resumes CASCADE;'))
    db.session.execute(text('DROP TABLE IF EXISTS users CASCADE;'))
    db.session.execute(text('DROP TABLE IF EXISTS alembic_version CASCADE;'))
    db.session.commit()
    print("All tables dropped successfully")