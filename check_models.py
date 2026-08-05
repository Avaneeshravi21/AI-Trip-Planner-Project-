import requests
import os
from dotenv import load_dotenv

load_dotenv()
key = os.environ["GROQ_API_KEY"]

response = requests.get(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {key}"}
)

for model in response.json()["data"]:
    print(model["id"])