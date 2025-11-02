from datetime import datetime
from app import db
from sqlalchemy.dialects.postgresql import JSON, UUID
import uuid

class Template(db.Model):
    __tablename__ = "templates"
    
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = db.Column(db.String(30), nullable=False)
    thumbnail = db.Column(db.String(255), nullable=False)
    cloudinary_public_id = db.Column(db.String(255), nullable=True)
    category = db.Column(db.String(20), nullable=False)  # Changed from Enum to String
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": str(self.id),
            "title": self.title,
            "thumbnail": self.thumbnail,
            "cloudinary_public_id": self.cloudinary_public_id,            
            "category": self.category,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
