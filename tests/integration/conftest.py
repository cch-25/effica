import os

os.environ["APP_ENV"] = "test"
os.environ["APP_BACKEND"] = "memory"
os.environ["SESSION_SECRET"] = "integration-test-secret-at-least-thirty-two-bytes"
os.environ["OAUTH_REDIRECT_ALLOWLIST"] = "http://localhost:3000/auth/callback"
