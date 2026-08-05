# AI Trip Planner — using LLMs & LangGraph

An intelligent travel assistant that takes a plain request like *"Plan a 5-day trip to Goa"*
and returns a complete itinerary — attractions, restaurants, activities, transport, hotel
costs, a daily budget, and live weather — by using a LangGraph agent that calls real,
live tools instead of guessing from memory.   

🔗 **[Try the live demo here](https://47veztzwwib3fpa8mo9wjj.streamlit.app/#day-7)**

Built with **LangChain**, **LangGraph**, **FastAPI**, and **Streamlit**.
Runs **100% free** — every required API has a genuine free tier, no credit card needed.

See `BUGFIXES.md` for a full list of bugs found and corrected in this version.

---

## 1. Prerequisites

- Python 3.10 (a different version may cause package install issues)
- [uv](https://docs.astral.sh/uv/) (recommended, faster) **or** plain `pip` + `venv` (also fine)

---

## 2. Get your free API keys

You only need **4 keys**, and none of them require a credit card:

| Key | Where to get it (free) |
|---|---|
| `GROQ_API_KEY` | https://console.groq.com/keys |
| `TAVILY_API_KEY` | https://tavily.com |
| `OPENWEATHERMAP_API_KEY` | https://home.openweathermap.org/users/sign_up |
| `EXCHANGE_RATE_API_KEY` | https://www.exchangerate-api.com/ |

`GPLACES_API_KEY` and `OPENAI_API_KEY` are **optional** and can be left blank —
see `.env.name` for details on why.

---

## 3. Set up the environment

**Option A — using `uv` (recommended):**
```bash
uv venv env --python 3.10
```
Activate it:
```bash
# Windows
env\Scripts\activate.bat
# Mac/Linux
source env/bin/activate
```
Install dependencies:
```bash
uv pip install -r requirements.txt
```

**Option B — using plain `pip` + `venv`:**
```bash
python -m venv env
```
Activate it (same commands as above), then:
```bash
pip install -r requirements.txt
```

---

## 4. Set up your `.env` file

Copy the template and fill in your real keys:
```bash
# Windows
copy .env.name .env
# Mac/Linux
cp .env.name .env
```
Open `.env` and paste in the 4 free keys from Step 2. Leave `GPLACES_API_KEY` and
`OPENAI_API_KEY` blank unless you specifically want to use them.

---

## 5. Run the app

You need **two terminals**, both with the virtual environment activated.

**Terminal 1 — start the backend:**
```bash
uvicorn main:app --reload --port 8000
```

**Terminal 2 — start the frontend:**
```bash
streamlit run streamlit_app.py
```

Streamlit will open in your browser automatically (usually `http://localhost:8501`).
Type a request like *"Plan a 5-day trip to Goa"* and submit.

---

## 6. Project structure

```
agent/              -> LangGraph agent (decides when to call tools)
tools/               -> AI-callable tools (weather, places, currency, calculator)
utils/               -> the actual API-calling logic behind each tool
prompt_library/      -> the system prompt given to the AI
config/              -> config.yaml (model settings) + config loader
main.py              -> FastAPI backend (/query endpoint)
streamlit_app.py     -> Streamlit chat UI
notebook/            -> experiments.ipynb, used to test tools/agent in isolation
BUGFIXES.md          -> full list of bugs found & fixed in this version
```


🔗 **[Try the live demo here](https://47veztzwwib3fpa8mo9wjj.streamlit.app/#day-7)**

---

## Troubleshooting

- **"GPLACES_API_KEY not set" warning** — this is expected and harmless if you're
  running free-only. The app automatically uses Tavily instead.
- **Streamlit can't reach the backend** — make sure `uvicorn` (Terminal 1) is running
  *before* you submit a request in Streamlit.
- **`FileNotFoundError` for config.yaml** — make sure you're running commands from
  inside the project's root folder.
- **Import errors right after install** — double check you activated the virtual
  environment before running `pip install` / `uv pip install`.
