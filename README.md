# LiveX Chatbot

A Streamlit-based chatbot integrating with Cal.com and OpenAI for scheduling and booking management.

## Features
- List upcoming bookings.
- Show available slots.
- Create and cancel bookings with natural language support (e.g., "tomorrow 9am").

## Requirements
- Python 3.13+
- Streamlit >= 1.51.0
- openai >= 1.0.0 (tested with 1.51.0)
- pyenv (recommended for managing Python versions)

## Local Development (macOS)

To run the application directly on macOS:

### Quick local test (no container)

If you already have a `pyenv` environment named `livex-env`, you can run the entire dev stack (including logging to `livex_logs.txt`) with a single command:
```bash
pyenv activate livex-env && streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --logger.level debug > livex_logs.txt 2>&1
```
This is the same command used for day-to-day debugging: the core Streamlit call is `streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --logger.level debug`.

1.  **Setup Python Environment (Recommended)**:
    It is recommended to use `pyenv` to manage your Python version.
    ```bash
    # Install pyenv if you don't have it
    brew install pyenv
    # Install Python 3.13
    pyenv install 3.13.9
    # Create a virtual environment
    pyenv virtualenv 3.13.9 livex-env
    # Set the local python version
    pyenv local livex-env
    ```

2.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment**:
    - Create a `.env` file in the project root with the following content:
      ```
      OPENAI_API_KEY=your_openai_key
      CAL_API_KEY=your_cal_key
      USER_EMAIL=your_email
      USERNAME=your_cal_username
      EVENT_SLUG=your_event_slug
      ```
    - **Security Note**: Do not commit the `.env` file to version control.

4.  **Run the App**:
    This command activates the python environment, runs the app with debug logging, and saves the output to `livex_logs.txt`.
    ```bash
    pyenv activate livex-env && streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --logger.level debug > livex_logs.txt 2>&1
    ```
    You can access the application at `http://127.0.0.1:8501`. The logs will be saved in the `livex_logs.txt` file.

## Deployment

This repository uses [deployment.md](deployment.md) for the full Cloud Run playbook (prereqs, Colima/Buildx setup, troubleshooting, and security guidance). The README keeps only the high-level flow:

### Local Testing (Docker)

- Use Colima with Rosetta if you are on Apple Silicon (see detailed flags in `deployment.md`).
- Run the container image locally to mimic production:
  ```bash
  docker run --rm --platform linux/amd64 -p 8000:8000 \
    -e STREAMLIT_ENV=production \
    -e USER_EMAIL=your_email \
    -e USERNAME=your_cal_username \
    -e EVENT_SLUG=your_event_slug \
    -e OPENAI_API_KEY=your_openai_key \
    -e CAL_API_KEY=your_cal_key \
    us-central1-docker.pkg.dev/livex-app/livex-repo/livex-app:latest
  ```

### Google Cloud Run Deployment

1. Build and push an `linux/amd64` image (full Buildx instructions live in `deployment.md`):
   ```bash
   docker buildx build --platform linux/amd64 -t us-central1-docker.pkg.dev/your-gcp-project/your-repo/livex-app --push .
   ```
2. Deploy the pushed image:
   ```bash
   gcloud run deploy livex-app \
     --image us-central1-docker.pkg.dev/your-gcp-project/your-repo/livex-app:latest \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --port 8000 \
     --set-env-vars STREAMLIT_ENV=production,USER_EMAIL=your_email,USERNAME=your_cal_username,EVENT_SLUG=your_event_slug \
     --set-secrets=OPENAI_API_KEY=openai-key:latest,CAL_API_KEY=cal-key:latest \
     --project=your-gcp-project
   ```

**Note:** Replace `your-gcp-project`/`your-repo` with the values defined in `deployment.md`, and ensure `openai-key` and `cal-key` secrets exist in Secret Manager.

## Key Innovations

This project implements several key strategies to address the challenge of "hallucinations" where the Large Language Model (LLM) might generate incorrect or nonsensical dates.

*   **Standardized Time Handling:** All internal time representations use UTC in ISO 8601 format to ensure consistency and avoid ambiguity. Time is dynamically converted to the user's selected timezone for display purposes.

*   **Leveraging the LLM for Parsing:** The application offloads the complex task of parsing natural language date and time inputs (e.g., "tomorrow", "next Monday at 2pm") to the LLM, which is better equipped to handle a wide variety of user inputs and corner cases.

*   **Structured and Validated LLM Output:** The LLM is prompted to return data in a standardized UTC and ISO format. The application then validates the LLM's output. If the LLM returns a hallucinated or incorrect date, the system uses the more reliable `time_period` (duration in seconds) returned by the LLM to calculate a correct end date based on the current date. This provides a robust fallback mechanism.

*   **Proof of Concept Features:** The dynamic timezone and style selection are included as a proof of concept. Some functions related to these features may not be fully implemented and could result in errors.

## Optional CSS
- `static/style.css` is optional for custom styling. The app continues without it if missing.

## Security
- Rotate API keys if exposed (e.g., in logs or commits).
- Use `git filter-repo` to purge sensitive data from Git history if needed.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
