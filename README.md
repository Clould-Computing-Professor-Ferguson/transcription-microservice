# 🗣️ Transcriptions

### 🎧 Transcription Service Overview
This microservice handles **audio-to-text transcription**.  
Users can upload an audio file (e.g., `.wav`, `.mp3`) and retrieve the transcription text later.  
Currently, it provides a **mock implementation** that returns placeholder text instead of real AI transcription.

---

### ⚙️ Endpoints

| Method | Path | Description |
|:------:|:-----|:------------|
| `GET` | `/transcriptions` | List all transcription jobs |
| `POST` | `/transcriptions` | Upload a new audio file and create a transcription job |
| `GET` | `/transcriptions/{transcriptionId}` | Retrieve a specific transcription result |
| `PUT` | `/transcriptions/{transcriptionId}` | Update a transcription job *(currently returns “Not implemented”)* |
| `DELETE` | `/transcriptions/{transcriptionId}` | Delete a transcription record |

---

### 🧱 Data Model

| Field | Type | Description |
|:------|:-----|:------------|
| `id` | UUID | Unique transcription ID |
| `audio_filename` | string | The name of the uploaded audio file |
| `text` | string *(optional)* | Transcribed text result |
| `status` | string | Current status (`pending`, `completed`, or `failed`) |
| `created_at` | datetime | Timestamp when the job was created |
| `updated_at` | datetime | Timestamp when the job was last updated |

---

### 🧠 Notes
- All routes comply with the assignment requirement to implement **GET, POST, PUT, and DELETE** for each resource.
- Actual speech-to-text functionality (e.g., Whisper, AWS Transcribe) can be added later.
- OpenAPI documentation is automatically generated at:  
  👉 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
