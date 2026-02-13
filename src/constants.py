# Feature flags
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
TESTING = False