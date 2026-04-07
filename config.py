import os
from dotenv import load_dotenv

load_dotenv(r"C:\Users\user\podcast-transcript-agent\.env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TAVILY_API_KEY    = os.getenv("TAVILY_API_KEY")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY")
