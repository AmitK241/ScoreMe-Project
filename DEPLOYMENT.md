# Quick Deployment Guide

This project can be deployed either as a **unified full-stack service** (FastAPI serves both the API and the Frontend dashboard on a single port with zero CORS issues) or as **separate frontend and backend services**.

---

## ⚡ Option 1: Instant Public URL (Fastest for Live Demos • 30 Seconds)

If you need a public URL immediately to show judges or team members without deploying to the cloud:

Make sure both backend (port 8000) and frontend (port 3000) are running locally, then open a new terminal:

```bash
# Using localtunnel (no account required):
npx localtunnel --port 3000
```
or
```bash
# Using ngrok:
ngrok http 3000
```

You will get a live public HTTPS URL (e.g., `https://calm-decision-92.loca.lt`) accessible from any phone or computer.

---

## 🚀 Option 2: Render.com (Free Cloud Web Service • 2 Minutes)

Render provides free hosting and deploys directly from GitHub.

1. Push this project to a GitHub repository:
   ```bash
   git init
   git add .
   git commit -m "Decision platform ready for deployment"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo-name>.git
   git push -u origin main
   ```

2. Go to **[dashboard.render.com](https://dashboard.render.com)**:
   - Click **New +** > **Web Service**
   - Connect your GitHub repository
   - Configure the service:
     - **Name**: `decision-platform`
     - **Runtime**: `Python 3`
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - In **Environment Variables**, add:
     - `PYTHONPATH`: `src:backend`
   - Click **Create Web Service**.

Your app will be live at `https://decision-platform-xxxx.onrender.com`:
- **Dashboard**: `https://decision-platform-xxxx.onrender.com/`
- **Swagger Docs**: `https://decision-platform-xxxx.onrender.com/docs`
- **API**: `https://decision-platform-xxxx.onrender.com/requests`

---

## 🚆 Option 3: Railway.app (Automatic Docker Deployment • 2 Minutes)

Railway auto-detects the included `Dockerfile` and deploys it in one click:

1. Go to **[railway.app](https://railway.app)**.
2. Click **New Project** > **Deploy from GitHub repo**.
3. Select your repository.
4. Click **Deploy Now**.
5. Under Settings > Networking, click **Generate Domain**.

Your app is live with SSL enabled!

---

## 🪶 Option 4: Fly.io (CLI Deployment • 1 Minute)

With the [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/) installed:

```bash
# From the project root:
fly launch

# When prompted:
# - Choose app name
# - Select region
# - Select existing fly.toml

fly deploy
```

---

## 🌐 Option 5: Decoupled Deployment (Frontend on Vercel + Backend on Render)

If you prefer keeping them on separate hosts:

1. **Deploy Backend**: Follow Option 2 (Render) or Option 3 (Railway) to get your backend URL:
   `https://my-decision-backend.onrender.com`

2. **Deploy Frontend on Vercel**:
   - Install Vercel CLI (`npm i -g vercel`) or visit [vercel.com](https://vercel.com).
   - Import your repository, set the **Root Directory** to `frontend`.
   - Click **Deploy**.

3. In the deployed frontend, the top-right **API** field allows you to enter your deployed backend URL.

