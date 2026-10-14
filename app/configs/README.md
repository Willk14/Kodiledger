# Backend Configuration

- `environment.py` defines environment variables and defaults through Pydantic
  Settings.
- `database.py` constructs the application and system database engines and
  session dependencies.
- `app.py` contains FastAPI metadata and application-level middleware setup.

Keep secrets in the process environment or an ignored local `.env` file. Do not
commit credentials.
