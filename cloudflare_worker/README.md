# ⚡ FilmsOverWeb - Free Cloudflare Stream Worker Setup

By deploying this free Cloudflare Worker, all video stream traffic connects **directly from Google Drive to your user's browser via Cloudflare**, resulting in **0 MB bandwidth and 0% CPU load on your Render server**.

---

## 🚀 2-Minute Setup Guide

### Step 1: Create a Free Cloudflare Account
1. Open [dash.cloudflare.com](https://dash.cloudflare.com/) and sign up or log in.
2. Click on **Compute (Workers & Pages)** in the left sidebar.
3. Click **Create Application** $\to$ **Create Worker**.

### Step 2: Paste the Worker Code
1. Name your worker (e.g., `filmsoverweb-stream`).
2. Click **Deploy**.
3. Once deployed, click **Edit code**.
4. Replace all code in `worker.js` with the contents of [`cloudflare_worker/worker.js`](./worker.js).
5. Click **Save and Deploy**.

### Step 3: Copy Your Worker URL to FilmsOverWeb
1. Copy your worker's public URL from the top of the Cloudflare dashboard:
   *(Example: `https://filmsoverweb-stream.yourname.workers.dev`)*
2. In your FilmsOverWeb web app, log in as **SuperAdmin** and open **Settings** (`/superadmin/settings`).
3. Under **Cloudflare Stream Worker**, paste your worker URL.
4. Click **Save System Settings**.

---

## 🎯 How It Works

```
User's Browser (movi-player WASM)
        │
        ├──[1. Fetch Byte Range (CORS Allowed)]──> Cloudflare Worker (Free Unlimited Bandwidth)
        │                                                   │
        │                                                   ├──[2. Fetch from Google Drive API]──> Google Drive
        │                                                   │
        └──<──[3. Return Video Chunks Direct to Browser]────┘
```

- **Render Server:** 0 MB egress bandwidth consumed.
- **Client Playback:** 100% loss-free 4K HEVC / AV1 hardware decoding + client-side Dolby/DTS audio decoding.

---

## ⚠️ Important: Google Drive Public Download Quota ("Took too long to load")

If a video was loading in the morning and later fails saying **"took too long to load"**:

1. **Google Drive Anonymous Quota:**
   When files in Google Drive are accessed through public unauthenticated links (`drive.usercontent.google.com`), Google restricts files that exceed its hidden daily download/bandwidth limit with a `"Google Drive - Quota exceeded"` block (lasts ~24 hours).
2. **Cloudflare Edge Caching:**
   The updated `worker.js` automatically enables Cloudflare edge caching (`cf: { cacheEverything: true, cacheTtl: 86400 }`) and handles `HEAD` probe sizing, reducing Google Drive origin hits by up to 95%.
3. **Permanent High-Bandwidth Fix (Google Service Account):**
   To completely bypass Google Drive's anonymous public download quota:
   - Create a free Service Account in [Google Cloud Console](https://console.cloud.google.com/).
   - Enable the **Google Drive API**.
   - Share your Google Drive media folder with the Service Account email.
   - Paste the Service Account JSON into FilmsOverWeb **SuperAdmin Settings** (`/superadmin/settings`).
   - Your streams will now authenticate directly with Google Drive API v3 without anonymous public quota locks!
