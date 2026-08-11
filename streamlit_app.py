import streamlit as st
import datetime
import os
from dotenv import load_dotenv

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# Local development: load keys from a .env file (does nothing on Streamlit
# Cloud, since there is no .env file there - see the block below instead).
load_dotenv()

# Streamlit Community Cloud: keys are provided via st.secrets (configured in
# the app's "Secrets" settings in the dashboard), not a .env file. Copy them
# into os.environ so the existing tools/model_loader code - which reads keys
# with os.getenv() - works completely unchanged, locally or in the cloud.
#
# Locally (no secrets.toml file at all - normal when just using .env), even
# checking st.secrets raises StreamlitSecretNotFoundError, so this whole
# block is wrapped in try/except and simply does nothing in that case -
# load_dotenv() above already handled local development.
try:
    for key in [
        "GROQ_API_KEY", "TAVILY_API_KEY", "OPENWEATHERMAP_API_KEY",
        "EXCHANGE_RATE_API_KEY", "GPLACES_API_KEY", "OPENAI_API_KEY",
    ]:
        if key in st.secrets:
            os.environ[key] = st.secrets[key]
except Exception:
    pass

from agent.agentic_workflow import GraphBuilder
from utils.currency_converter import CurrencyConverter


import re
from collections import Counter

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def extract_places(markdown_text: str):
    """
    Pull out every place name that follows a Morning/Afternoon/Evening
    heading in the AI's response, e.g. '### Morning: Isha Yoga Centre'
    -> 'Isha Yoga Centre'.
    """
    pattern = r"###\s*[^\n:]*(?:Morning|Afternoon|Evening)\s*:\s*([^\n]+)"
    matches = re.findall(pattern, markdown_text, flags=re.IGNORECASE)
    return [m.strip() for m in matches]


def find_duplicate_places(markdown_text: str):
    """
    Returns a list of place names that appear more than once in the
    itinerary (across Plan A and Plan B combined, or within either plan).
    """
    places = extract_places(markdown_text)
    normalized = [p.lower().strip() for p in places]
    counts = Counter(normalized)
    return [place for place, c in counts.items() if c > 1]


def annotate_currency_conversion(markdown_text: str, home_currency: str = "INR"):
    """
    Deterministically appends a converted amount next to every Total and
    daily-expense figure in a non-home-currency budget table, using a real,
    direct exchange-rate API call in code - NOT relying on the AI to do this
    correctly. Prompt instructions and retry-based detection both proved
    unreliable for this specific requirement, so it is now enforced here
    with guaranteed, deterministic Python logic instead, the same way the
    calculator tool avoids trusting the AI's arithmetic.

    Handles both a single amount (e.g. "21,500") and a price RANGE (e.g.
    "$580-$1460"), converting every number found and preserving the range
    format in the appended INR approximation.

    Fails silently (returns the text unchanged) if no budget table is found,
    the trip is already in the home currency, a conversion is already
    present, or the exchange-rate API call itself fails for any reason -
    this must never break or block the rest of the travel plan.
    """
    currency_match = re.search(r"Amount\s*\(([A-Z]{3})\)", markdown_text)
    if not currency_match:
        return markdown_text

    currency = currency_match.group(1)
    if currency == home_currency:
        return markdown_text

    if re.search(r"₹|\bINR\b", markdown_text):
        return markdown_text  # AI already added its own conversion - don't duplicate

    try:
        api_key = os.getenv("EXCHANGE_RATE_API_KEY")
        converter = CurrencyConverter(api_key)
        rate = converter.convert(1, currency, home_currency)
    except Exception as e:
        print(f"[currency conversion] could not fetch live rate: {e}")
        return markdown_text

    def convert_one(num_str):
        amount = float(num_str.replace(",", "").replace("$", ""))
        return f"\u20b9{amount * rate:,.0f}"

    # Matches a single amount OR a range, with an optional leading $ on
    # either number (e.g. "21,500", "$580-$1460", "300 - 900")
    number_span = r"\$?[\d,]+\.?\d*(?:\s*[-\u2013\u2014]\s*\$?[\d,]+\.?\d*)?"

    def make_replacer(suffix=""):
        def replacer(m):
            label, span = m.group(1), m.group(2)
            nums = re.findall(r"[\d,]+\.?\d*", span)
            converted = [convert_one(n) for n in nums]
            approx = f"(approx {'-'.join(converted)})" if converted else ""
            return f"{label}{span} {currency} {approx}{suffix}"
        return replacer

    markdown_text = re.sub(
        r"(Total\s*[|\t]\s*)(" + number_span + r")",
        make_replacer(),
        markdown_text,
    )

    markdown_text = re.sub(
        r"(Approximate daily expense:\s*)(" + number_span + r")\s*" + re.escape(currency) + r"\s*per day",
        make_replacer(suffix=" per day"),
        markdown_text,
        flags=re.IGNORECASE,
    )

    return markdown_text


def escape_dollar_signs(text: str) -> str:
    """
    Streamlit's markdown renderer treats text between $ signs as LaTeX math,
    not currency - so a price like "$580-$1460" written by the AI gets
    silently mangled into a broken-looking formula instead of displaying as
    a dollar amount (this is exactly what happened with a real USD budget
    table). Escaping every literal $ as \\$ tells the renderer "this is a
    literal character, not the start of a math expression", while it still
    displays as a normal $ sign to the user.
    """
    return text.replace("$", "\\$")


def invoke_with_retry(react_app, messages, max_retries: int = 1):
    """
    Retries the agent call for two known, intermittent failure modes -
    neither of which reflects a real, unrecoverable error:

    1. 'tool_use_failed' - the model occasionally attempts a malformed
       inline tool call at the very end of a long generation (Groq error).
    2. Duplicate places - on longer trips, the model can occasionally repeat
       a place name between (or even within) Plan A and Plan B, despite the
       prompt explicitly forbidding it.

    (Currency conversion is NOT retried here anymore - it proved unreliable
    even across multiple retries, so it is now fixed deterministically with
    a direct, guaranteed code-level conversion in annotate_currency_conversion()
    after this function returns, instead of spending retry attempts hoping
    the AI does it correctly.)

    Any other kind of error fails immediately - this never hides a real
    problem, only these confirmed-intermittent ones. If every attempt still
    has duplicates, the last attempt is returned rather than failing the
    whole request, since an imperfect plan is still more useful than no plan.
    """
    last_error = None
    last_output = None
    for attempt in range(1, max_retries + 2):
        try:
            output = react_app.invoke(messages)
        except Exception as e:
            last_error = e
            if "tool_use_failed" in str(e) or "Failed to call a function" in str(e):
                print(f"[retry] attempt {attempt} hit tool_use_failed, retrying...")
                continue
            raise

        if isinstance(output, dict) and "messages" in output:
            content = output["messages"][-1].content
        else:
            content = str(output)

        dupes = find_duplicate_places(content)
        last_output = output

        if attempt <= max_retries and dupes:
            print(f"[retry] attempt {attempt} found duplicate places {dupes}, retrying...")
            continue

        return output

    if last_output is not None:
        return last_output
    raise last_error

st.set_page_config(
    page_title="🌍 Travel Planner Agentic Application",
    page_icon="🌍",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.title("🌍 Travel Planner Agentic Application")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
st.header("How can I help you in planning a trip? Let me know where do you want to visit.")

# Chat input box at bottom
with st.form(key="query_form", clear_on_submit=True):
    user_input = st.text_input("User Input", placeholder="e.g. Plan a trip to Goa for 5 days")
    submit_button = st.form_submit_button("Send")

if submit_button and user_input.strip():
    try:
        with st.spinner("Bot is thinking..."):
            # Call the LangGraph agent directly in this same process, instead
            # of making an HTTP request to a separate FastAPI server - there
            # is no separate server process available on Streamlit Cloud.
            graph_builder = GraphBuilder(model_provider="groq")
            react_app = graph_builder()
            output = invoke_with_retry(react_app, {"messages": [user_input]}, max_retries=1)

            if isinstance(output, dict) and "messages" in output:
                answer = output["messages"][-1].content
            else:
                answer = str(output)

            if not answer or not str(answer).strip():
                answer = (
                    "The AI model returned an empty response for this request. "
                    "This can happen occasionally with some models - please try "
                    "asking again, or rephrase your request."
                )
            else:
                # Guarantee the INR conversion is present for international
                # trips, deterministically - do not rely on the AI to add it.
                answer = annotate_currency_conversion(answer)
                # Prevent literal $ signs (e.g. from USD price ranges) from
                # being misinterpreted as LaTeX math by Streamlit's renderer.
                answer = escape_dollar_signs(answer)

        markdown_content = f"""# 🌍 AI Travel Plan

**Generated:** {datetime.datetime.now(IST).strftime('%Y-%m-%d at %H:%M')}
**Created by:** 😎Cool Dracula's Travel Agent

---

{answer}

---

<<<<<<< HEAD
*This travel plan was generated by AI. Please verify all information, especially prices, operating hours, and travel requirements before your trip.*
=======


*This travel plan was generated by AI. Kindly verify all information, especially prices, operating hours, and travel requirements before your trip. இந்த பயணத் திட்டம் AI மூலம் உருவாக்கப்பட்டது. உங்கள் பயணத்திற்கு முன், குறிப்பாக விலைகள், செயல்படும் நேரங்கள் மற்றும் பயணத்திற்குத் தேவையான விதிமுறைகள்/ஆவணங்கள் பற்றிய அனைத்து தகவல்களையும் சரிபார்த்துக் கொள்ளவும்.*
>>>>>>> 1ca33c93ee04b54cab65ac5c97ff304ef9046346
"""
        st.markdown(markdown_content)

    except Exception as e:
        error_text = str(e)
        if "rate_limit_exceeded" in error_text or "429" in error_text:
            st.error(
                "⏳ The AI has hit its free daily usage limit on Groq. This resets "
                "automatically - the error usually states how long to wait "
                "(often under 2 hours). Please try again a bit later."
            )
        else:
            st.error(f"The response failed due to: {e}")





