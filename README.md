# 🎬 FilmsOverWeb — Cloud Cinema OTT WebApp

**FilmsOverWeb** is a high-performance, private OTT streaming platform built with **FastAPI** that aggregates movies from your Google Drive folders and displays them in a sleek, modern **Netflix / Prime Video** style interface.

It features **lossless direct video playback** with native in-browser **HEVC (H.265)** and **AV1** hardware decoding, automatic **TMDB metadata enrichment**, and **Google Mail automation** (`drmnbot@gmail.com`) for guest onboarding.

---

## ✨ Key Features

- **📺 Netflix / Amazon Prime Style OTT UI**:
  - Immersive cinema dark aesthetic (`TailwindCSS` + custom glassmorphism).
  - Dynamic **Hero Billboard** featuring top-rated movies with backdrop artwork, rating badges, overview, and quick play buttons.
  - Smooth **horizontal carousels** for *Continue Watching*, *Recently Added from Google Drive*, *Trending & Top Rated*, and *Genre Rails*.
  - Movie cards with hover zoom dynamics, codec badges (`HEVC`, `AV1`, `H.264`), and resolution indicators (`4K UHD`, `1080p`).

- **⚡ Lossless Direct Google Drive Streaming**:
  - Streams original, uncompressed files directly using **HTTP 206 Partial Content (Range requests)**.
  - Bypasses Google Drive's lossy 360p/720p transcoding—you get the exact file bitrate and master quality.
  - Zero-latency seeking and chunked buffering.

- **🚀 Native In-Browser HEVC (H.265) & AV1 Support**:
  - Plays HEVC and AV1 videos directly in modern browsers (Chrome 107+, Microsoft Edge 107+, Safari 13+, Firefox).
  - In-player **Hardware Decoder & Codec Diagnostic Panel** checks browser GPU capabilities and advises on hardware acceleration.
  - Cinema video player with keyboard shortcuts, resume playback timestamp memory, volume normalization, and playback speed controls.

- **🍿 TMDB (The Movie Database) Metadata Auto-Enrichment**:
  - Intelligent regex filename parser cleans complex scene releases (e.g. `Oppenheimer.2023.IMAX.2160p.UHD.HDR.HEVC.mkv` → `Oppenheimer (2023)`).
  - Automatically queries TMDB to pull official high-resolution posters, backdrops, plot overviews, director, top cast, ratings, and YouTube trailer links.
  - Graceful fallback: If TMDB is unavailable, auto-generates sleek fallback artwork.

- **🛡️ 3-Tier Role-Based Access Control (RBAC)**:
  - **SuperAdmin**: Full control. Configures TMDB API Key, Google Drive credentials, and Gmail SMTP settings; creates Admins and Guests.
  - **Admin**: Adds Google Drive folder links, triggers sync/scan, and creates Guest accounts.
  - **Guest**: Access only to browse the library and stream movies. Cannot access admin panels or folder links.

- **✉️ Automated Guest Onboarding via Google Mail**:
  - Creating a guest generates a secure, randomized 12-character password.
  - Automatically sends a branded HTML welcome email with credentials and direct login URL from `drmnbot@gmail.com`.
  - Fallback "Copy Credentials" button ensures onboarding is never blocked if SMTP credentials are still being configured.

---

## 🏗️ Project Architecture

```
FilmsOverWeb/
├── app/
│   ├── config.py                 # App settings & environment resolution
│   ├── database.py               # Pure-Python thread-safe JSON database engine
│   ├── models.py                 # Data models (User, Movie, DriveFolder, etc.)
│   ├── auth.py                   # JWT cookies, bcrypt hashing, and RBAC guards
│   ├── parser.py                 # Filename parser for titles, years, codecs & resolution
│   ├── gdrive.py                 # Google Drive API & Range-based stream generator
│   ├── tmdb.py                   # TMDB API client with search & details enrichment
│   ├── mailer.py                 # Gmail automation using drmnbot@gmail.com
│   ├── routes/
│   │   ├── auth_routes.py        # Login, logout, session management
│   │   ├── movie_routes.py       # OTT homepage, catalog, movie details, watch view
│   │   ├── stream_routes.py      # HTTP 206 Range-based video streaming proxy
│   │   ├── admin_routes.py       # Google Drive folder links & Guest management
│   │   └── superadmin_routes.py  # System settings (TMDB, GDrive, Gmail) & Admin management
│   ├── static/                   # CSS, SVG artwork, and icons
│   └── templates/                # Jinja2 templates (Netflix/Prime design)
├── films_over_web.json           # Native JSON database (Users, Movies, Watch Progress)
├── Dockerfile                    # Production container with Python 3.11 & FFmpeg
├── docker-compose.yml            # 1-click Docker deployment
├── wsgi.py                       # WSGI adapter for PythonAnywhere
├── run.py                        # Application entry runner
└── requirements.txt
```

---

## 🚀 Quick Start Guide

### 1. Activate Environment & Run Application
```powershell
# Using the pre-configured virtual environment
.\venv\Scripts\python run.py
```

The application will start on: **`http://127.0.0.1:8000`**

### 2. Default Login Credentials
- **Role**: SuperAdmin
- **Email**: `drmnbot@gmail.com`
- **Password**: `SuperAdmin@2026`

*(You can change the password or create new admins in the SuperAdmin panel)*

---

## ⚙️ Configuration (SuperAdmin Panel)

Log in as SuperAdmin and navigate to **Settings** (`/superadmin/settings`):

### 1. TMDB API Key
- Get a free API key at [The Movie Database](https://www.themoviedb.org/settings/api).
- Paste your 32-character API key in the SuperAdmin Settings.
- When new folders are scanned, posters, cast, and backdrops are fetched automatically.

### 2. Google Drive Access
- **Public Shared Folders**: Set folder sharing to *"Anyone with the link can view"* and enter your Google API Key.
- **Private / Team Folders**: Paste your Google Cloud Service Account JSON key into the Service Account box, and share the Google Drive folder with the Service Account email (`xxx@xxx.iam.gserviceaccount.com`).

### 3. Google Mail Automation (drmnbot@gmail.com)
- **Sender**: `drmnbot@gmail.com`
- **SMTP Host**: `smtp.gmail.com`
- **SMTP Port**: `465` (SSL)
- **Google App Password**: 
  1. Visit [Google App Passwords](https://myaccount.google.com/apppasswords).
  2. Create a new App Password named `FilmsOverWeb`.
  3. Copy the 16-character code and paste it in SuperAdmin Settings.
  4. Use the **"Dispatch Test Email"** tool to verify instant delivery!

---

## 🎥 HEVC & AV1 Browser Compatibility Guide

| Codec | Chrome | Microsoft Edge | Apple Safari | Mozilla Firefox |
|---|---|---|---|---|
| **HEVC (H.265)** | ✅ Chrome 107+ *(Hardware Accelerated)* | ✅ Edge 107+ *(Hardware Accelerated)* | ✅ Safari 13+ *(Native)* | ⚠️ Depends on OS decoder |
| **AV1** | ✅ Chrome 70+ *(Native)* | ✅ Edge 75+ *(Native)* | ✅ Safari 17+ *(macOS Sonoma / iOS 17)* | ✅ Firefox 67+ *(Native)* |
| **H.264 (AVC)** | ✅ Universal | ✅ Universal | ✅ Universal | ✅ Universal |

> 💡 **Windows Tip for HEVC**: Ensure your browser has hardware acceleration enabled under *Settings → System → Use hardware acceleration when available*. On Windows 10/11, install the free *HEVC Video Extensions from Device Manufacturer* or the standard Microsoft Store extension for GPU HEVC playback.

---

## 👥 User Roles & Permissions Matrix

| Feature | SuperAdmin | Admin | Guest |
|---|:---:|:---:|:---:|
| Browse OTT Catalog & Search | ✅ | ✅ | ✅ |
| Stream Movies in Full Quality | ✅ | ✅ | ✅ |
| Add / Delete Google Drive Folders | ✅ | ✅ | ❌ |
| Trigger Google Drive Sync | ✅ | ✅ | ❌ |
| Invite Guests & Send Automated Mail | ✅ | ✅ | ❌ |
| Manage System API Keys (TMDB, GDrive) | ✅ | ❌ | ❌ |
| Manage Gmail Automation SMTP Settings | ✅ | ❌ | ❌ |
| Create & Delete Admin Accounts | ✅ | ❌ | ❌ |

---

## 🌐 Deployment & Hosting

For complete step-by-step guides on deploying FilmsOverWeb to cloud platforms, read the [Deployment Guide](DEPLOYMENT.md).

- **Render.com (Recommended Free Cloud Deployment)**: Native ASGI, includes `ffmpeg` via Docker, supports long video streaming sessions and 100% free tier.
- **PythonAnywhere (Free Tier)**: Supported via the included WSGI adapter ([`wsgi.py`](wsgi.py)), but has free tier limitations (1 worker, no ffmpeg, outbound whitelist).
- **Vercel**: ❌ **Not recommended / Incompatible** due to serverless 10-second request timeouts and 4.5 MB payload caps.
- **Self-Hosted VPS / Docker**: 🏆 Best performance with dedicated CPU for unlimited 4K lossless streaming via `docker compose up -d`.

---

## 🧪 Testing

Run the included automated test suite anytime:
```powershell
.\venv\Scripts\python -m unittest test_app.py
```
