from datetime import datetime
from app import db
from sqlalchemy.dialects.postgresql import JSON

class Resume(db.Model):
    __tablename__ = "resumes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    template_id = db.Column(db.String(100), nullable=True)
    content = db.Column(JSON, nullable=False)  # stores the resume JSON described by you
    ats_score = db.Column(db.Integer, nullable=True)
    ats_report = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "template_id": self.template_id,
            "content": self.content,
            "ats_score": self.ats_score,
            "ats_report": self.ats_report,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
