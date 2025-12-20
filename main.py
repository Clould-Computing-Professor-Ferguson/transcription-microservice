from __future__ import annotations

import os
import socket
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

import pymysql
from fastapi import FastAPI, Form, HTTPException
from fastapi import Query, Path
from fastapi import UploadFile, File
from dotenv import load_dotenv

from models.person import PersonCreate, PersonRead, PersonUpdate
from models.address import AddressCreate, AddressRead, AddressUpdate
from models.health import Health
from models.transcription import TranscriptionCreate, TranscriptionRead, TranscriptionUpdate

from google.cloud import pubsub_v1

load_dotenv()
port = int(os.environ.get("FASTAPIPORT", 8000))

INSTANCE_CONNECTION_NAME = os.getenv(
    "INSTANCE_CONNECTION_NAME",
    "cloudcomputing-473814:us-central1:transcription-microservice",
)

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME")
DB_HOST = os.getenv("DB_HOST") # Used only for local dev (with proxy)
DB_PORT = int(os.getenv("DB_PORT", "3306"))

if not all([INSTANCE_CONNECTION_NAME, DB_USER, DB_NAME]):
    raise RuntimeError(
        "Missing required DB configuration. Check your .env or Cloud Run env vars."
    )

publisher = pubsub_v1.PublisherClient()
topic_path = publisher.topic_path(os.getenv("PROJECT_ID", "cloudcomputing-473814"),
                                   os.getenv("PUBSUB_TOPIC", "transcriptions-events"))

def publish_transcription_event(transcription: TranscriptionRead, event_type: str = "transcription.created"):
    """
    Publish a Pub/Sub event when something happens to a transcription.
    event_type can be 'transcription.created', 'transcription.updated', etc.
    """
    payload = {
        "event_type": event_type,
        "id": str(transcription.id),
        "audio_filename": transcription.audio_filename,
        "status": transcription.status,
        "created_at": transcription.created_at.isoformat(),
        "updated_at": transcription.updated_at.isoformat(),
    }

    data = json.dumps(payload).encode("utf-8")
    future = publisher.publish(topic_path, data=data)

def get_conn():
    """
    Connect to MySQL in two modes:

    - LOCAL DEVELOPMENT:
        - load_dotenv() loads .env
        - DB_HOST defaults to 127.0.0.1
        - Use Cloud SQL Proxy locally: ./cloud-sql-proxy --port=3306 <instance>

    - CLOUD RUN:
        - Detect via K_SERVICE or CLOUD_RUN_JOB
        - Use Cloud SQL UNIX socket: /cloudsql/<INSTANCE_CONNECTION_NAME>
    """

    running_in_cloud_run = bool(os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_JOB"))

    if running_in_cloud_run:
        # Cloud Run → Use Cloud SQL Unix Socket
        socket_path = f"/cloudsql/{INSTANCE_CONNECTION_NAME}"
        conn = pymysql.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            unix_socket=socket_path,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
    else:
        # Local dev → Connect over TCP through Cloud SQL Proxy
        conn = pymysql.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME,
            host=DB_HOST or "127.0.0.1",
            port=DB_PORT,
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )

    return conn


# -------------------------------------------------------------------------
# Fake in-memory "databases"
# -------------------------------------------------------------------------
persons: Dict[UUID, PersonRead] = {}
addresses: Dict[UUID, AddressRead] = {}

app = FastAPI(
    title="Transcription API",
    description="Demo FastAPI app using Pydantic v2 models Transcription API",
    version="0.1.0",
)

@app.get("/transcriptions", response_model=List[TranscriptionRead])
def list_transcriptions():
    """List all transcription jobs from Cloud SQL."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, audio_filename, text, status, created_at, updated_at
                FROM transcriptions
                ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()

    return [
        TranscriptionRead(
            id=UUID(row["id"]),
            audio_filename=row["audio_filename"],
            text=row["text"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


@app.get("/transcriptions/{trans_id}", response_model=TranscriptionRead)
def get_transcription(trans_id: UUID):
    """Fetch a single transcription from Cloud SQL."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, audio_filename, text, status, created_at, updated_at
                FROM transcriptions
                WHERE id = %s
            """, (str(trans_id),))
            row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Transcription not found")

    return TranscriptionRead(
        id=UUID(row["id"]),
        audio_filename=row["audio_filename"],
        text=row["text"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@app.post("/transcriptions/{trans_id}", response_model=TranscriptionRead, status_code=201)
async def create_transcription(
    trans_id: UUID,
    file: UploadFile = File(...),
    ):
    """Upload an audio file + store transcription job in Cloud SQL."""
    file_name = file.filename
    status = "completed"
    text_result = f"(Mock transcription of {file_name})"
    now = datetime.utcnow()

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO transcriptions (
                    id, audio_filename, text, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (str(trans_id), file_name, text_result, status, now, now))

    transcription_obj = TranscriptionRead(
    id=trans_id,
    audio_filename=file_name,
    text=text_result,
    status=status,
    created_at=now,
    updated_at=now,
)

    # Publish event to Pub/Sub
    publish_transcription_event(transcription_obj, event_type="transcription.created")

    return transcription_obj

@app.put("/transcriptions/{trans_id}", response_model=TranscriptionRead)
def update_transcription(trans_id: UUID, payload: TranscriptionUpdate):

    # Only keep fields that were actually sent in the request
    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        # Nothing to update; you could also choose to 400 here
        raise HTTPException(status_code=400, detail="No fields provided to update")

    with get_conn() as conn:
        with conn.cursor() as cursor:
            # 1) Make sure the transcription exists
            cursor.execute(
                "SELECT id FROM transcriptions WHERE id = %s",
                (str(trans_id),),
            )
            existing = cursor.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Transcription not found")

            # 2) Build dynamic SET clause from the provided fields
            set_clauses = []
            values = []

            # Only allow updating specific columns
            for field in ("audio_filename", "text", "status"):
                if field in update_data:
                    set_clauses.append(f"{field} = %s")
                    values.append(update_data[field])

            # Always bump updated_at
            now = datetime.utcnow()
            set_clauses.append("updated_at = %s")
            values.append(now)

            # WHERE id = ...
            values.append(str(trans_id))

            sql = f"UPDATE transcriptions SET {', '.join(set_clauses)} WHERE id = %s"
            cursor.execute(sql, tuple(values))

            # 3) Re-fetch updated row to return it
            cursor.execute(
                """
                SELECT id, audio_filename, text, status, created_at, updated_at
                FROM transcriptions
                WHERE id = %s
                """,
                (str(trans_id),),
            )
            row = cursor.fetchone()

    # Safety check
    if not row:
        raise HTTPException(status_code=404, detail="Transcription not found after update")

    return TranscriptionRead(
        id=UUID(row["id"]),
        audio_filename=row["audio_filename"],
        text=row["text"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )



@app.delete("/transcriptions/{trans_id}", status_code=204)
def delete_transcription(trans_id: UUID):
    """Delete a transcription from Cloud SQL."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM transcriptions WHERE id = %s", (str(trans_id),))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Transcription not found")

    return

# -----------------------------------------------------------------------------
# Address endpoints
# -----------------------------------------------------------------------------

# def make_health(echo: Optional[str], path_echo: Optional[str]=None) -> Health:
#     return Health(
#         status=200,
#         status_message="OK",
#         timestamp=datetime.utcnow().isoformat() + "Z",
#         ip_address=socket.gethostbyname(socket.gethostname()),
#         echo=echo,
#         path_echo=path_echo
#     )
#
# @app.get("/health", response_model=Health)
# def get_health_no_path(echo: str | None = Query(None, description="Optional echo string")):
#     # Works because path_echo is optional in the model
#     return make_health(echo=echo, path_echo=None)
#
# @app.get("/health/{path_echo}", response_model=Health)
# def get_health_with_path(
#     path_echo: str = Path(..., description="Required echo in the URL path"),
#     echo: str | None = Query(None, description="Optional echo string"),
# ):
#     return make_health(echo=echo, path_echo=path_echo)
#
# @app.post("/addresses", response_model=AddressRead, status_code=201)
# def create_address(address: AddressCreate):
#     if address.id in addresses:
#         raise HTTPException(status_code=400, detail="Address with this ID already exists")
#     addresses[address.id] = AddressRead(**address.model_dump())
#     return addresses[address.id]
#
# @app.get("/addresses", response_model=List[AddressRead])
# def list_addresses(
#     street: Optional[str] = Query(None, description="Filter by street"),
#     city: Optional[str] = Query(None, description="Filter by city"),
#     state: Optional[str] = Query(None, description="Filter by state/region"),
#     postal_code: Optional[str] = Query(None, description="Filter by postal code"),
#     country: Optional[str] = Query(None, description="Filter by country"),
# ):
#     results = list(addresses.values())
#
#     if street is not None:
#         results = [a for a in results if a.street == street]
#     if city is not None:
#         results = [a for a in results if a.city == city]
#     if state is not None:
#         results = [a for a in results if a.state == state]
#     if postal_code is not None:
#         results = [a for a in results if a.postal_code == postal_code]
#     if country is not None:
#         results = [a for a in results if a.country == country]
#
#     return results
#
# @app.get("/addresses/{address_id}", response_model=AddressRead)
# def get_address(address_id: UUID):
#     if address_id not in addresses:
#         raise HTTPException(status_code=404, detail="Address not found")
#     return addresses[address_id]
#
# @app.patch("/addresses/{address_id}", response_model=AddressRead)
# def update_address(address_id: UUID, update: AddressUpdate):
#     if address_id not in addresses:
#         raise HTTPException(status_code=404, detail="Address not found")
#     stored = addresses[address_id].model_dump()
#     stored.update(update.model_dump(exclude_unset=True))
#     addresses[address_id] = AddressRead(**stored)
#     return addresses[address_id]
#
# # -----------------------------------------------------------------------------
# # Person endpoints
# # -----------------------------------------------------------------------------
# @app.post("/persons", response_model=PersonRead, status_code=201)
# def create_person(person: PersonCreate):
#     # Each person gets its own UUID; stored as PersonRead
#     person_read = PersonRead(**person.model_dump())
#     persons[person_read.id] = person_read
#     return person_read
#
# @app.get("/persons", response_model=List[PersonRead])
# def list_persons(
#     uni: Optional[str] = Query(None, description="Filter by Columbia UNI"),
#     first_name: Optional[str] = Query(None, description="Filter by first name"),
#     last_name: Optional[str] = Query(None, description="Filter by last name"),
#     email: Optional[str] = Query(None, description="Filter by email"),
#     phone: Optional[str] = Query(None, description="Filter by phone number"),
#     birth_date: Optional[str] = Query(None, description="Filter by date of birth (YYYY-MM-DD)"),
#     city: Optional[str] = Query(None, description="Filter by city of at least one address"),
#     country: Optional[str] = Query(None, description="Filter by country of at least one address"),
# ):
#     results = list(persons.values())
#
#     if uni is not None:
#         results = [p for p in results if p.uni == uni]
#     if first_name is not None:
#         results = [p for p in results if p.first_name == first_name]
#     if last_name is not None:
#         results = [p for p in results if p.last_name == last_name]
#     if email is not None:
#         results = [p for p in results if p.email == email]
#     if phone is not None:
#         results = [p for p in results if p.phone == phone]
#     if birth_date is not None:
#         results = [p for p in results if str(p.birth_date) == birth_date]
#
#     # nested address filtering
#     if city is not None:
#         results = [p for p in results if any(addr.city == city for addr in p.addresses)]
#     if country is not None:
#         results = [p for p in results if any(addr.country == country for addr in p.addresses)]
#
#     return results
#
# @app.get("/persons/{person_id}", response_model=PersonRead)
# def get_person(person_id: UUID):
#     if person_id not in persons:
#         raise HTTPException(status_code=404, detail="Person not found")
#     return persons[person_id]
#
# @app.patch("/persons/{person_id}", response_model=PersonRead)
# def update_person(person_id: UUID, update: PersonUpdate):
#     if person_id not in persons:
#         raise HTTPException(status_code=404, detail="Person not found")
#     stored = persons[person_id].model_dump()
#     stored.update(update.model_dump(exclude_unset=True))
#     persons[person_id] = PersonRead(**stored)
#     return persons[person_id]

# -----------------------------------------------------------------------------
# Root
# -----------------------------------------------------------------------------
@app.get("/")
def root():
    return {"message": "Welcome to the Person/Address API. See /docs for OpenAPI UI."}

# -----------------------------------------------------------------------------
# Entrypoint for `python main.py`
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
