# 🚀 FilmsOverWeb — Deployment & Hosting Guide

This guide breaks down where and how to host **FilmsOverWeb**, comparing **PythonAnywhere (Free Tier)** vs. **Vercel**, explaining the technical constraints of video streaming, and providing step-by-step instructions for each platform.

---

## ⚡ Quick Comparison: Vercel vs. PythonAnywhere vs. Render / VPS

| Feature / Requirement | Vercel (Hobby Free) | PythonAnywhere (Free Tier) | Render.com (Free Tier) | Docker / VPS ($4/mo or Free Oracle) |
|---|:---:|:---:|:---:|:---:|
| **Can it run FilmsOverWeb?** | ❌ **No (Impossible)** | ⚠️ **Severe Limitations** | ✅ **Yes (Recommended Free)** | 🏆 **Best Performance** |
| **Database Architecture** | ❌ Wiped on cold-start | ⚠️ 1-worker JSON/WSGI | ✅ **100% Native JSON (`films_over_web.json`)** | ✅ **100% Native JSON (`films_over_web.json`)** |
| **Execution Timeout** | **10–15 Seconds** (Hard limit) | 300 Seconds per request | Unlimited (Long streaming) | Unlimited |
| **Response Payload Size** | Max **4.5 MB** | Unlimited | Unlimited | Unlimited |
| **FFmpeg Transmuxing Support** | ❌ None | ❌ Not installed / No root | ✅ Yes (via Docker) | ✅ Full Lossless 4K & Dolby 5.1 |
| **Realtime Video Streaming** | ❌ Fails after 10s | ⚠️ 1 worker blocks site | ✅ Native ASGI Streaming | ✅ High throughput |
| **Outbound Internet Access** | ✅ Full access | ❌ Strict Whitelist only | ✅ Full access | ✅ Full access |
| **Ease of Deployment** | Low (Incompatible) | Moderate (Manual WSGI) | **Easiest (1-Click Docker)** | Simple (`docker compose up`) |

> 💡 **Why the JSON Database (`films_over_web.json`) makes Render deployment effortless**:
> FilmsOverWeb now stores all movie metadata, user accounts, and watch history in a lightweight, thread-safe JSON database (`films_over_web.json`). Because the JSON database is committed directly into the Git repository, **deploying to Render requires ZERO database provisioning or external database addons**. When your app starts up, your entire movie catalog, settings, and users are immediately live!

---

## ❓ Can I Deploy on Vercel?
### **Short Answer: No.**

**Vercel is a Serverless Function platform (AWS Lambda), not a continuous server.**

1. **10-Second Hard Timeout**: Movies run for 2 to 3 hours. When streaming video through Vercel, the serverless function terminates abruptly after 10–15 seconds, killing the stream.
2. **4.5 MB Response Size Limit**: A typical 1080p or 4K video stream is several gigabytes. Vercel aborts any response larger than 4.5 MB.
3. **No Background `ffmpeg` Execution**: FilmsOverWeb uses real-time `ffmpeg` subprocesses to remux MKV containers, Dolby 5.1/DTS audio, and fragmented MP4 chunks. Serverless environments cannot run long-lived ffmpeg pipes.
4. **Ephemeral Filesystem**: Serverless instances are spun up and torn down continuously. Any database writes (`films_over_web.db`, watch progress, created users, invited guests) are lost immediately.

---

## 🐍 Deploying on PythonAnywhere (Free Tier)

### ⚠️ Free Tier Limitations to Know Before You Start:
1. **WSGI Only (No Native ASGI / WebSockets)**: PythonAnywhere runs WSGI servers. We have provided a `wsgi.py` adapter using `a2wsgi` to make FastAPI run on PythonAnywhere.
2. **1 Worker Limit**: The free tier provides only 1 web worker. While a user is streaming video, that single worker is occupied and all other requests will wait or time out.
3. **No `ffmpeg` Installed**: MKV files or formats requiring on-the-fly audio transcoding (E-AC3, TrueHD, DTS) will not transmux. Only direct MP4 files (H.264 / AAC) will play.
4. **Outbound Internet Whitelist**: Free accounts can only access websites on PythonAnywhere's approved whitelist. Google Drive media streaming endpoints may require requesting a whitelist addition on the PythonAnywhere forums.
5. **CPU Quota (100s / day)**: CPU-heavy video remuxing will quickly drop your account into the "tarpit" where tasks run slowly.

---

### Step-by-Step Setup on PythonAnywhere

#### Step 1: Create an Account & Open Bash
1. Register a free account at [pythonanywhere.com](https://www.pythonanywhere.com).
2. Go to the **Consoles** tab and open a **Bash Console**.

#### Step 2: Clone or Upload Your Repository
In the Bash console, clone your code (or upload a `.zip` in the Files tab):
```bash
git clone https://github.com/<your-username>/FilmsOverWeb.git
cd FilmsOverWeb
```

#### Step 3: Create a Virtual Environment & Install Dependencies
```bash
# Create Python 3.10 or 3.11 virtual environment
mkvirtualenv --python=/usr/bin/python3.10 filmsoverweb-env

# Upgrade pip and install requirements (including a2wsgi)
pip install --upgrade pip
pip install -r requirements.txt
```

#### Step 4: Configure the Web App Tab
1. Open the **Web** tab in the PythonAnywhere navigation bar.
2. Click **"Add a new web app"**.
3. Choose your domain (`<your-username>.pythonanywhere.com`).
4. Select **Manual configuration** (do **NOT** select Django or Flask).
5. Choose **Python 3.10** (matching your virtualenv).
6. Under **Virtualenv**, enter:
   ```
   /home/<your-username>/.virtualenvs/filmsoverweb-env
   ```
7. Under **Code**, enter:
   - **Source code**: `/home/<your-username>/FilmsOverWeb`
   - **Working directory**: `/home/<your-username>/FilmsOverWeb`

#### Step 5: Configure the WSGI Configuration File
In the **Web** tab, click the link to edit the **WSGI configuration file** (`/var/www/<your-username>_pythonanywhere_com_wsgi.py`).

Delete all default template code and replace it with:
```python
import sys
import os

# Set project directory
project_home = '/home/<your-username>/FilmsOverWeb'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set environment variables if needed
os.environ["SECRET_KEY"] = "your-secure-random-secret-key-here"

# Import WSGI adapter created for FastAPI
from wsgi import application
```
*(Replace `<your-username>` with your actual PythonAnywhere username)*. Save the file.

#### Step 6: Configure Static Files
In the **Web** tab under the **Static files** section:
- **URL**: `/static/`
- **Directory**: `/home/<your-username>/FilmsOverWeb/app/static`

#### Step 7: Reload & Launch
Click the green **"Reload <your-username>.pythonanywhere.com"** button at the top of the Web tab.
Your web application will be accessible at:
```
https://<your-username>.pythonanywhere.com
```

---

## 🏆 Recommended Free Cloud Deployment: Render.com (with Docker & FFmpeg)

**Render.com** supports native ASGI, background streaming, and Docker containers with full `ffmpeg` installation on their **Free Tier**.

### Step-by-Step Setup on Render:

#### Step 1: Push to GitHub
Make sure your repository has the provided `Dockerfile` and `requirements.txt` committed:
```bash
git add .
git commit -m "Add Dockerfile and deployment configurations"
git push origin main
```

#### Step 2: Create a Web Service on Render
1. Log in to [render.com](https://render.com).
2. Click **New +** → **Web Service**.
3. Connect your GitHub repository.
4. Set the following fields:
   - **Name**: `filmsoverweb`
   - **Region**: Choose the closest region (e.g. Frankfurt, Oregon, Singapore).
   - **Environment**: **Docker** (Render will automatically detect the included `Dockerfile`).
   - **Instance Type**: **Free** (0.5 CPU, 512 MB RAM).
5. Under **Advanced → Environment Variables**, add:
   - `SECRET_KEY`: *(Generate a secure random string)*
   - `TMDB_API_KEY`: *(Your TMDB API Key)*
   - `SuperAdminEmail`: *(Optional: Custom SuperAdmin email - if set, password change prompt is bypassed)*
   - `SuperAdminPassword`: *(Optional: Custom SuperAdmin password)*
   - *(Note: If SuperAdminEmail and SuperAdminPassword are omitted, it rolls over to test@gmail.com / 1q2w3e4r5t with a first-time password change prompt)*
6. Click **Create Web Service**.

Render will automatically build the Docker image, install `ffmpeg`, install Python requirements, and launch Uvicorn. Your Cinema OTT will be live with full 4K streaming and audio transmuxing!

---

## 🐳 Self-Hosted VPS Deployment (Oracle Cloud / Ubuntu / Docker)

For the absolute best home cinema experience with 100% dedicated hardware, no request timeouts, and 24/7 uptime:

### 1. Run via Docker Compose:
```bash
# Clone the repository
git clone https://github.com/<your-username>/FilmsOverWeb.git
cd FilmsOverWeb

# Build and start container in the background
docker compose up -d --build
```

### 2. Run Directly on Ubuntu with Systemd & Uvicorn:
```bash
# Install system packages
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg

# Clone & setup venv
git clone https://github.com/<your-username>/FilmsOverWeb.git
cd FilmsOverWeb
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run in production with Uvicorn
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 3. Setup Systemd Service (`/etc/systemd/system/filmsoverweb.service`):
```ini
[Unit]
Description=FilmsOverWeb Cinema OTT Platform
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/FilmsOverWeb
ExecStart=/home/ubuntu/FilmsOverWeb/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
```
Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now filmsoverweb
```

---

## 🔒 Summary Checklist for Production

- [ ] **Generate a Strong `SECRET_KEY`**: Set in environment variables or `.env`.
- [ ] **Configure SuperAdmin**: Change default admin credentials upon first login.
- [ ] **Google Drive Credentials**: Add your Google Service Account JSON or API Key in `/superadmin/settings`.
- [ ] **TMDB API Key**: Enter your free 32-character API key in `/superadmin/settings` to automate poster and backdrop fetching.
- [ ] **Gmail SMTP**: Configure your Gmail address and Google App Password in `/superadmin/settings` to enable automated guest welcome emails and password resets.
