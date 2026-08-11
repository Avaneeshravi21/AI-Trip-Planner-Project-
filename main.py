from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agent.agentic_workflow import GraphBuilder
from utils.save_to_document import save_document
from utils.currency_converter import CurrencyConverter
from starlette.responses import JSONResponse
import os
import datetime
from dotenv import load_dotenv
from pydantic import BaseModel
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # set specific origins in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class QueryRequest(BaseModel):
    question: str


import re
from collections import Counter


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

@app.post("/query")
async def query_travel_agent(query:QueryRequest):
    try:
        print(query)
        graph = GraphBuilder(model_provider="groq")
        react_app=graph()
        #react_app = graph.build_graph()

        # Diagram export is optional/cosmetic and depends on an external service
        # (mermaid.ink). It must never be allowed to fail the actual user request,
        # so it is isolated in its own try/except.
        try:
            png_graph = react_app.get_graph().draw_mermaid_png()
            with open("my_graph.png", "wb") as f:
                f.write(png_graph)
            print(f"Graph saved as 'my_graph.png' in {os.getcwd()}")
        except Exception as diagram_error:
            print(f"[non-fatal] Could not render graph diagram: {diagram_error}")

        # Assuming request is a pydantic object like: {"question": "your text"}
        messages={"messages": [query.question]}
        output = invoke_with_retry(react_app, messages, max_retries=1)

        # If result is dict with messages:
        if isinstance(output, dict) and "messages" in output:
            final_output = output["messages"][-1].content  # Last AI response
        else:
            final_output = str(output)

        # Defensive fallback: some models can occasionally return an empty
        # final message (e.g. only reasoning, no visible answer). Rather than
        # silently returning a blank plan, surface a clear, honest message.
        if not final_output or not str(final_output).strip():
            final_output = (
                "The AI model returned an empty response for this request. "
                "This can happen occasionally with some models - please try "
                "asking again, or rephrase your request."
            )
        else:
            # Guarantee the INR conversion is present for international
            # trips, deterministically - do not rely on the AI to add it.
            final_output = annotate_currency_conversion(final_output)
            # Prevent literal $ signs (e.g. from USD price ranges) from being
            # misinterpreted as LaTeX math by any downstream markdown renderer.
            final_output = escape_dollar_signs(final_output)

        return {"answer": final_output}
    except Exception as e:
        error_text = str(e)
        if "rate_limit_exceeded" in error_text or "429" in error_text:
            friendly_message = (
                "The AI has hit its free daily usage limit on Groq. This resets "
                "automatically - Groq's own error usually states how long to wait "
                "(often under 2 hours). Please try again a bit later."
            )
            return JSONResponse(status_code=429, content={"error": friendly_message})
        return JSONResponse(status_code=500, content={"error": error_text})