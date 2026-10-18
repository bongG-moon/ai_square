# Copy to runtime_config.py. HCP Secret/process environment overrides these values.
# sso: HCP-verified company identity / local: provisioned local accounts
# mock: loopback-only development, NEVER an authentication method for deployment.
PTAI_AUTH_MODE = 'local'
PTAI_SECRET_KEY = ''  # Empty: generated once and retained in MongoDB settings.
PTAI_ADMIN_IDS = ''   # Base administrator IDs for BOTH local and SSO login, comma-separated.
PTAI_COOKIE_SECURE = False  # Set True behind production HTTPS, including non-SSO use.
PTAI_SESSION_COOKIE_NAME = 'pt_ai_square_session'  # Use a different name for parallel instances on one host.
PTAI_MAX_UPLOAD_MB = 128
PTAI_STORAGE_QUOTA_MB = 5120
PTAI_HOST = '127.0.0.1'
PTAI_PORT = 5080

# .env is not read. Enter all deployment settings directly in runtime_config.py.
# Same Mongo variable names as the reference Flask Portal.
# Empty URI: read-only demo/catalog.json preview, no login or persistence.
# Actual local trial: 'mongodb://127.0.0.1:27018/'
# Configured MongoDB failure never falls back to demo or SQLite.
MONGODB_URI = ''
MONGODB_DATABASE = 'pt_ai_square'
PTAI_ACTIVITY_COLLECTION = 'square_activity_events'  # Legacy activity collection, migration input only.
PTAI_MONGODB_TIMEOUT_MS = 3000
# Optional local trial settings (AUTH_MODE must be 'mock'):
PTAI_MOCK_USER = '1000001'
PTAI_MOCK_NAME = '개발 사용자'
PTAI_MOCK_ADMIN = True
# PTAI_DATA_DIR = r'C:\data\pt_ai_square'  # Preserve this folder when updating code.
