# Livex App Deployment Guide to Google Cloud Run

This guide details the deployment of the `livex-app` (a Streamlit-based booking assistant using OpenAI and Cal.com APIs) to Google Cloud Run, including local configuration on a macOS Apple Silicon (ARM64) machine with Colima. It addresses architecture mismatches, port issues, API errors, and security best practices.

**Date**: November 10, 2025  
**Project**: livex-app  
**Environment**: Google Cloud Run, Artifact Registry, Secret Manager  
**Local Setup**: macOS Sequoia 15+, Colima, Docker CLI, Python 3.13.9

---

## Table of Contents
1. [Prerequisites](#1-prerequisites)
2. [Local Configuration](#2-local-configuration)
3. [Build and Push Docker Image](#3-build-and-push-docker-image)
4. [Update Cloud Run Deployment with New Image](#4-update-cloud-run-deployment-with-new-image)
5. [Verify Deployment](#5-verify-deployment)
6. [Fix Cal.com API 404 Error](#6-fix-calcom-api-404-error)
7. [Security Best Practices](#7-security-best-practices)
8. [Troubleshooting](#8-troubleshooting)
9. [Testing Application Functionality](#9-testing-application-functionality)
10. [Notes](#10-notes)

---

## 1. Prerequisites

Ensure the following are installed and configured:

- **macOS**: Sequoia 15+ (Apple Silicon, ARM64).
- **Colima**: v0.9.1 for Docker runtime.
  ```bash
  brew install colima
  ```
- **Docker CLI**: v27+ for building images.
  ```bash
  brew install docker
  ```
- **gcloud CLI**: v546.0.0 for Google Cloud operations.
  ```bash
  gcloud components update
  ```
- **Python**: 3.13.9 for local testing.
  ```bash
  pyenv install 3.13.9
  pyenv global 3.13.9
  ```
- **Rosetta 2**: For `amd64` emulation.
  ```bash
  /usr/sbin/softwareupdate --install-rosetta --agree-to-license
  ```
- **Google Cloud Project**: `livex-app` (ID: 880770500925).
- **Artifact Registry**: `us-central1-docker.pkg.dev/livex-app/livex-repo`.
- **Secret Manager**: Secrets `openai-key` and `cal-key`.

---

## 2. Local Configuration

Configure your local environment to support `amd64` builds and Cloud Run deployment.

### 2.1 Start Colima with Rosetta 2
Colima runs Docker in a VM with Rosetta 2 for `amd64` emulation.

```bash
colima stop
colima start --cpu 4 --memory 8 --vm-type=vz --vz-rosetta --mount-type=virtiofs
```

Verify:
```bash
colima status
```
Expected:
```
INFO[0000] colima is running using macOS Virtualization.Framework
INFO[0000] arch: aarch64
INFO[0000] runtime: docker
INFO[0000] mountType: virtiofs
INFO[0000] docker socket: unix:///Users/mhuo/.colima/default/docker.sock
INFO[0000] containerd socket: unix:///Users/mhuo/.colima/default/containerd.sock
```

### 2.2 Install Docker Buildx
Buildx enables multi-platform builds (e.g., `linux/amd64`).

```bash
mkdir -p ~/.docker/cli-plugins
curl -L -o ~/.docker/cli-plugins/docker-buildx "https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.darwin-arm64"
chmod +x ~/.docker/cli-plugins/docker-buildx
```

Verify:
```bash
docker buildx version
```
Expected:
```
github.com/docker/buildx v0.17.1 ...
```

Set up a builder:
```bash
docker buildx create --name mybuilder --use
docker buildx inspect --bootstrap
```
Expected:
```
Name: mybuilder
Driver: docker-container
Nodes:
- Name: mybuilder0
  Endpoint: unix:///var/run/docker.sock
  Platforms: linux/arm64, linux/amd64, linux/arm/v7
```

### 2.3 Test AMD64 Emulation
Confirm Rosetta 2 supports `amd64`:
```bash
docker run --platform linux/amd64 hello-world
```
Expected:
```
Hello from Docker!
```

---



## 3. Build and Push Docker Image

Build the image for `linux/amd64` to match Cloud Run’s requirements.

```bash
cd /Users/mhuo/github/livex
docker buildx build --platform linux/amd64 --no-cache -t us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app --push .
```

Verify:
```bash
gcloud artifacts docker images list us-central1-docker.pkg.dev/livex-app/livex-repo --project=livex-app
```
Expected:
```
REPOSITORY                                   DIGEST
us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app  sha256:...
```

Check architecture:
```bash
docker pull us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app:latest
docker inspect us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app:latest | grep Architecture
```
Expected:
```
"Architecture": "amd64"
```

---

## 4. Update Cloud Run Deployment with New Image

After pushing the container in [Section 3](#3-build-and-push-docker-image), update the Cloud Run service to point to that new image tag or digest. Pinning to the digest ensures the exact build is deployed.

1. Capture the digest of the freshly pushed image:
   ```bash
   IMAGE_PATH=us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app
   IMAGE_DIGEST=$(gcloud artifacts docker images describe ${IMAGE_PATH}:latest \
     --project=livex-app \
     --format='value(image_summary.digest)')
   echo "Deploying ${IMAGE_PATH}@${IMAGE_DIGEST}"
   ```
2. Update the Cloud Run service (zero downtime) to use the new image:
   ```bash
   gcloud run deploy livex-app \
     --image ${IMAGE_PATH}@${IMAGE_DIGEST} \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --port 8000 \
     --set-env-vars STREAMLIT_ENV=production,USER_EMAIL=mhuo.live@gmail.com,USERNAME=michaelhuo,EVENT_SLUG=30min,STYLE_SCHEME=3,APP_HOST=0.0.0.0,APP_PORT=8000 \
     --set-secrets=OPENAI_API_KEY=openai-key:latest,CAL_API_KEY=cal-key:latest \
     --service-account 880770500925-compute@developer.gserviceaccount.com \
     --timeout 300 \
     --project=livex-app \
     --revision-suffix=$(date +%y%m%d%H%M)
   ```
3. Confirm that traffic now points to the new revision:
   ```bash
   gcloud run services describe livex-app \
     --region us-central1 \
     --project=livex-app \
     --format="value(status.traffic.statuses)"
   ```
   Expected: Revision with the timestamped suffix receives 100% traffic.

---

## 5. Verify Deployment

Check service status:
```bash
gcloud run services describe livex-app --region=us-central1 --project=livex-app
```
Expected:
```
metadata:
  name: livex-app
spec:
  template:
    spec:
      containers:
      - env:
        - name: STREAMLIT_ENV
          value: production
        - name: USER_EMAIL
          value: mhuo.live@gmail.com
        - name: OPENAI_API_KEY
          valueFrom:
            secretKeyRef:
              name: openai-key
              key: latest
status:
  url: https://livex-app-880770500925.us-central1.run.app
```

Test the app:
```bash
curl https://livex-app-880770500925.us-central1.run.app
```
Expected: Streamlit HTML landing page.

Check logs:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=livex-app" \
  --project=livex-app \
  --limit=100 \
  --format="table(timestamp, severity, textPayload)"
```

---

## 6. Fix Cal.com API 404 Error

The 404 error occurred due to an invalid date range (`start=2025-11-11`, `end=2023-10-17`). The updated `api.py` ensures:
- `start_date` is today or later.
- `end_date` is after `start_date` (default: +7 days).
- Proper logging for debugging.

Test locally:
```bash
docker run --rm --platform linux/amd64 -p 8000:8000 \
  -e STREAMLIT_ENV=production \
  -e USER_EMAIL=mhuo.live@gmail.com \
  -e USERNAME=michaelhuo \
  -e EVENT_SLUG=30min \
  -e STYLE_SCHEME=3 \
  -e APP_HOST=0.0.0.0 \
  -e APP_PORT=8000 \
  -e PORT=8000 \
  -e OPENAI_API_KEY=your_test_openai_key \
  -e CAL_API_KEY=your_test_cal_key \
  us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app:latest
```
- Access `http://localhost:8000` and test “show my slots”.

---

## 7. Security Best Practices

### 8.1 Revoke Exposed API Keys
Revoke the exposed keys:
- `OPENAI_API_KEY=`
- `CAL_API_KEY=`

Generate new keys and update Secret Manager:
```bash
gcloud secrets versions add openai-key --data-file=- <<< "your_new_openai_key" --project=livex-app
gcloud secrets versions add cal-key --data-file=- <<< "your_new_cal_key" --project=livex-app
```

### 8.2 Remove `.env` from Git
```bash
cd /Users/mhuo/github/livex
git filter-repo --path .env --invert-paths --force
git push origin main --force
```

### 8.3 Verify Secret Permissions
Ensure the service account has access:
```bash
gcloud secrets get-iam-policy openai-key --project=livex-app
gcloud secrets get-iam-policy cal-key --project=livex-app
```
Expected:
```
bindings:
- members:
  - serviceAccount:880770500925-compute@developer.gserviceaccount.com
  role: roles/secretmanager.secretAccessor
```

Grant if missing:
```bash
gcloud secrets add-iam-policy-binding openai-key \
  --member="serviceAccount:880770500925-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=livex-app
gcloud secrets add-iam-policy-binding cal-key \
  --member="serviceAccount:880770500925-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project=livex-app
```

---

## 8. Troubleshooting

### 9.1 Exec Format Error
If logs show `exec format error`:
- Verify image architecture:
  ```bash
  docker inspect us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app:latest | grep Architecture
  ```
  Expected: `"Architecture": "amd64"`.
- Rebuild:
  ```bash
  docker buildx build --platform linux/amd64 --no-cache -t us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app --push .
  ```

### 9.2 Port Mismatch
If Streamlit uses 8501 instead of 8000:
- Check logs for `PORT` usage.
- Ensure `app.py` respects `os.getenv("PORT")`.

### 9.3 API 404 Error Persists
If `get_available_slots` still returns 404:
- Check logs for the API URL and parameters.
- Test the API manually:
  ```bash
  curl -H "Authorization: Bearer your_new_cal_key" \
    "https://api.cal.com/v2/slots?eventTypeSlug=30min&username=michaelhuo&start=2025-11-11T00:00:00Z&end=2025-11-18T23:59:59Z&duration=30&format=range&cal-api-version=2024-09-04"
  ```
- Verify `eventTypeSlug` and `username` in Cal.com.

### 9.4 Secret Access Issues
If logs show "CAL_API_KEY not found":
- Verify permissions:
  ```bash
  gcloud secrets get-iam-policy cal-key --project=livex-app
  ```

---

## 9. Testing Application Functionality

Test the app at `https://livex-app-880770500925.us-central1.run.app`:
- **Commands**:
  - “show my events”
  - “show my slots”
  - “book my first available slot of 30 minutes with susan@viai.ai for dinner”
- **Expected**:
  - “show my events”: Lists upcoming bookings or “No upcoming events found.”
  - “show my slots”: Lists available slots for the next 7 days.
  - “book my first available slot”: Creates a booking if slots are available.

If errors occur, check logs:
```bash
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=livex-app" \
  --project=livex-app \
  --limit=100 \
  --format="table(timestamp, severity, textPayload)"
```

---

## 10. Notes
- **Security**: Always mask API keys in logs and commands.
- **Buildx**: Use Buildx for future builds to avoid legacy builder issues.
- **Cal.com**: Ensure `eventTypeSlug=30min` and `username=michaelhuo` are valid in your Cal.com account.

This artifact covers all steps to deploy `livex-app` successfully. Run the commands in sequence, and share outputs for any issues!
