# COCO AI — Professional Voice Assistant 🥥

COCO AI is a professional, commercial-ready voice-controlled AI assistant featuring a stunning Gemini-inspired web interface. It provides a real-time, low-latency conversational experience using Google's Gemini Live API.

## 🚀 Key Features

- **Gemini-Inspired UI**: Premium dark-themed interface with a dynamic, animated voice orb.
- **Voice-First Experience**: Full voice control with Push-to-Talk and Always-Listening modes.
- **Real-Time Streaming**: Bidirectional audio streaming via WebSockets for near-instant responses.
- **Intelligent Memory**: Persistent SQLite-based memory system that remembers users and past conversations.
- **Professional Personality**: Warm, intelligent, and articulate persona that adapts to user language (English/Hindi/Hinglish).

## 🛠️ Architecture

COCO AI bridges the gap between the browser and advanced AI models:

1. **Frontend**: Vanilla HTML/CSS/JS with Web Audio API for low-latency mic capture and playback.
2. **Backend**: FastAPI server handling WebSocket connections and orchestrating audio flow.
3. **Brain**: Integration with Gemini Live API for real-time natural language processing and voice synthesis.
4. **Memory**: SQLite database for persistent user profiles and conversation history.

## 📦 Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd COCO
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set your Gemini API Key**:
   ```powershell
   # Windows PowerShell
   $env:GEMINI_API_KEY = "your_api_key_here"
   ```

4. **Launch COCO AI**:
   ```bash
   python server.py
   ```

5. **Access the UI**: Open [http://localhost:8000](http://localhost:8000) in your browser.

## 📂 Project Structure

- `server.py`: FastAPI application server.
- `coco_session.py`: The COCO brain for WebSocket-based web interface.
- `coco_live.py`: The COCO brain for local hardware/robot integration.
- `database.py`: Persistent storage management.
- `static/`: Web UI assets (HTML, CSS, JS).
- `audio_engine.py`, `face_engine.py`, etc.: Legacy hardware integration modules (optional).

## 🛡️ Identity & Memory

COCO uses a **Lean Memory Context** system to provide fast, relevant responses while staying within token limits. It identifies users via voice and text, allowing it to address you by name and remember your preferences across sessions.

---

Built with ❤️ by the COCO AI Team.
