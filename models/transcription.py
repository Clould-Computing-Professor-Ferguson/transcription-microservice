from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional

class TranscriptionBase(BaseModel):
    id: UUID = Field(default_factory=uuid4, description="Unique transcription ID")
    audio_filename: str = Field(..., description="Uploaded audio filename")
    text: Optional[str] = Field(None, description="Transcribed text result")
    status: str = Field(default="pending", description="Status: pending / processing / completed / failed")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "11111111-2222-4333-8444-555555555555",
                    "audio_filename": "session1.wav",
                    "text": "Hello, how are you feeling today?",
                    "status": "completed",
                    "created_at": "2025-10-18T12:00:00Z",
                    "updated_at": "2025-10-18T12:01:00Z",
                }
            ]
        }
    }

class TranscriptionCreate(BaseModel):
    audio_filename: str = Field(..., description="Uploaded file name")

class TranscriptionRead(TranscriptionBase):
    pass

class TranscriptionUpdate(BaseModel):
    audio_filename: Optional[str] = Field(
        None, description="Updated audio filename"
    )
    text: Optional[str] = Field(
        None, description="Updated transcribed text"
    )
    status: Optional[str] = Field(
        None,
        description="Updated status: pending / processing / completed / failed"
    )