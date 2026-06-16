"""
face_engine.py — Pi-optimized face recognition engine
Uses HOG model (fast on CPU), downscaled frames, background thread.
Camera is used ONLY for identifying who's in front — no images are sent to Gemini.
"""

import threading
import time
import cv2
import numpy as np

# Try to import face_recognition; graceful fallback if not installed
try:
    import face_recognition
    FACE_AVAILABLE = True
except ImportError:
    FACE_AVAILABLE = False
    print("[Face] face_recognition not installed. Face ID disabled.")
    print("[Face] Install with: pip install face_recognition")

from database import load_all_faces, save_face_encoding


class FaceEngine:
    """
    Background face recognition engine.
    Runs in a separate thread, periodically checks who's in frame.
    """

    def __init__(self):
        self._known_names = []
        self._known_encodings = []
        self._current_name = "Unknown"
        self._current_confidence = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._camera = None

        # Load Pi-aware settings (falls back gracefully if core not available)
        try:
            from core.config import settings as _cfg
            self._detect_interval = _cfg.pi_face_detect_interval
            self._cam_width       = _cfg.pi_camera_width
            self._cam_height      = _cfg.pi_camera_height
        except Exception:
            self._detect_interval = 2.0
            self._cam_width       = 640
            self._cam_height      = 480

        if FACE_AVAILABLE:
            self._load_known_faces()

    def _load_known_faces(self):
        """Load all known face encodings from database."""
        faces = load_all_faces()
        with self._lock:
            self._known_names = list(faces.keys())
            self._known_encodings = list(faces.values())
        print(f"[Face] Loaded {len(faces)} known face(s): {list(faces.keys())}")

    def refresh(self):
        """Reload known faces from DB (call after enrollment)."""
        if FACE_AVAILABLE:
            self._load_known_faces()

    def start(self, camera_index=0):
        """Start background face detection thread."""
        if not FACE_AVAILABLE:
            print("[Face] Cannot start — face_recognition not installed.")
            return

        if self._running:
            return

        self._camera = cv2.VideoCapture(camera_index)
        if not self._camera.isOpened():
            print("[Face] Cannot open camera. Face ID disabled.")
            self._camera = None
            return

        self._camera.set(cv2.CAP_PROP_FRAME_WIDTH,  self._cam_width)
        self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self._cam_height)

        self._running = True
        self._thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._thread.start()
        print("[Face] Background face detection started.")

    def stop(self):
        """Stop the detection thread and release camera."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._camera:
            self._camera.release()
            self._camera = None
        print("[Face] Face detection stopped.")

    def get_current_identity(self) -> tuple[str, float]:
        """Returns (name, confidence) of whoever is currently detected."""
        with self._lock:
            return self._current_name, self._current_confidence

    def _detection_loop(self):
        """Background loop: capture frame → detect → identify → sleep."""
        while self._running:
            try:
                ret, frame = self._camera.read()
                if not ret:
                    time.sleep(self._detect_interval)
                    continue

                name, confidence = self._identify_frame(frame)

                with self._lock:
                    self._current_name = name
                    self._current_confidence = confidence

            except Exception as e:
                print(f"[Face] Detection error: {e}")

            time.sleep(self._detect_interval)

    def _identify_frame(self, frame) -> tuple[str, float]:
        """
        Identify a face in a single frame.
        Returns (name, confidence) or ("Unknown", 0.0).
        """
        # Downscale for speed: 640→320 (or whatever the input is, halve it)
        small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)

        # Convert BGR (OpenCV) to RGB (face_recognition)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

        # Detect faces using HOG model (fast on CPU, good for Pi)
        face_locations = face_recognition.face_locations(rgb, model="hog")

        if not face_locations:
            return "Unknown", 0.0

        # Get encodings for detected faces
        face_encodings = face_recognition.face_encodings(rgb, face_locations)

        if not face_encodings or not self._known_encodings:
            return "Unknown", 0.0

        # Compare the first (closest/largest) face against known faces
        encoding = face_encodings[0]

        # Calculate distances to all known faces
        distances = face_recognition.face_distance(self._known_encodings, encoding)

        if len(distances) == 0:
            return "Unknown", 0.0

        best_idx = np.argmin(distances)
        best_distance = distances[best_idx]

        # Lower distance = better match. Threshold: 0.6 is standard
        if best_distance < 0.6:
            confidence = 1.0 - best_distance  # convert distance to confidence
            return self._known_names[best_idx], confidence

        return "Unknown", 0.0

    def enroll(self, name: str, frame=None) -> bool:
        """
        Enroll a new face. Uses provided frame or captures from camera.
        Returns True on success.
        """
        if not FACE_AVAILABLE:
            print("[Face] Cannot enroll — face_recognition not installed.")
            return False

        # Capture frame if not provided
        if frame is None:
            if not self._camera or not self._camera.isOpened():
                print("[Face] No camera available for enrollment.")
                return False
            ret, frame = self._camera.read()
            if not ret:
                print("[Face] Failed to capture frame for enrollment.")
                return False

        # Convert to RGB
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Detect and encode
        face_locations = face_recognition.face_locations(rgb, model="hog")
        if not face_locations:
            print(f"[Face] No face detected in frame for '{name}'.")
            return False

        encodings = face_recognition.face_encodings(rgb, face_locations)
        if not encodings:
            print(f"[Face] Could not encode face for '{name}'.")
            return False

        # Save the first face encoding to database
        save_face_encoding(name, encodings[0])
        print(f"[Face] ✅ Enrolled face for '{name}'.")

        # Reload known faces
        self.refresh()
        return True

    def enroll_from_file(self, name: str, image_path: str) -> bool:
        """Enroll a face from an image file (for initial Irfan setup)."""
        if not FACE_AVAILABLE:
            print("[Face] Cannot enroll — face_recognition not installed.")
            return False

        image = face_recognition.load_image_file(image_path)
        face_locations = face_recognition.face_locations(image, model="hog")

        if not face_locations:
            print(f"[Face] No face found in '{image_path}'.")
            return False

        encodings = face_recognition.face_encodings(image, face_locations)
        if not encodings:
            print(f"[Face] Could not encode face from '{image_path}'.")
            return False

        save_face_encoding(name, encodings[0])
        print(f"[Face] ✅ Enrolled face for '{name}' from file.")
        self.refresh()
        return True
