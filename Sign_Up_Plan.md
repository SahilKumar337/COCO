# Multi-User Architecture & Settings Implementation

Adding multi-user support with customizable AI voices, personas, and Google OAuth integration is a significant architectural upgrade. This transforms SIFRA from a single-user local assistant into a scalable, production-ready SaaS-like platform.

## Proposed Changes

### Admin Identification & Legacy Migration
To answer your question: **How do we know who is the admin?**
The industry-standard way is to specify an `ADMIN_EMAIL` in the `.env` file. When you sign up (either via Gmail or traditional signup) using that specific email address, the system will automatically flag your account as `is_admin = True`. 
Once the admin account is created, all legacy "COCO" conversation data will be seamlessly mapped to your account during the database migration.

### 1. Database Restructuring (`database.py`)
We will create a strict multi-tenant architecture.
- **`users` Table:** Create a new table to store `id`, `email`, `password_hash`, `name`, `google_id`, `is_admin`, `ai_voice` (default: 'Aoede'), and `ai_persona`.
- **Data Isolation:** Modify the `conversations` table to include a `user_id` foreign key. All queries will be strictly scoped.

### 2. Authentication (`auth.py` & `server.py`)
- **Google OAuth:** Add `/auth/google/login` and `/auth/google/callback` endpoints.
- **Traditional Auth:** Add `/signup` and `/login` endpoints using secure password hashing (`bcrypt`).
- **Security:** Implement secure HTTP-only cookies with JWT (JSON Web Tokens) to manage sessions.

### 3. Frontend UI (`static/login.html` & `static/index.html`)
- **[NEW] `login.html` & `signup.html`:** Create a stunning, industry-grade login/signup flow with glassmorphism, dynamic background particles, and a prominent "Sign in with Google" button.
- **Auth Guarding:** Modify `app.js` to automatically redirect unauthenticated users to the login page.
- **Settings Panel:** Expand the settings drawer in `index.html` to include:
  - **Voice Selector:** Dropdown to choose between Gemini's voices.
  - **Persona Editor:** A text area where users can define how SIFRA should act toward them.

### 4. SIFRA Core (`sifra_session.py`)
- When a WebSocket connects, authenticate the session using the user's cookie.
- Fetch the user's saved `ai_voice` and `ai_persona` from the database and dynamically inject them into Gemini.
