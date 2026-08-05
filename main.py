from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agent.agentic_workflow import GraphBuilder
from utils.save_to_document import save_document
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


def invoke_with_retry(react_app, messages, max_retries: int = 2):
    """
    Some models occasionally attempt a malformed inline tool call at the very
    end of a long generation (Groq error code 'tool_use_failed'). This is
    usually a one-off sampling glitch, not a repeatable failure - the same
    request frequently succeeds on a retry. Retry a few times specifically
    for this error before giving up; any other kind of error fails immediately.
    """
    last_error = None
    for attempt in range(1, max_retries + 2):
        try:
            return react_app.invoke(messages)
        except Exception as e:
            last_error = e
            if "tool_use_failed" in str(e) or "Failed to call a function" in str(e):
                print(f"[retry] attempt {attempt} hit tool_use_failed, retrying...")
                continue
            raise
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
        output = invoke_with_retry(react_app, messages, max_retries=2)

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

        return {"answer": final_output}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})