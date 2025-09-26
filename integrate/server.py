from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import asyncio
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from prompt import SYSTEM_PROMPT, STARTUP_PROMPT
from mcp_use import MCPAgent, MCPClient
from streaming_tts import speak_text
from contextlib import asynccontextmanager

from stt import transcribe
# Load environment variables
load_dotenv()





agent = None


UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCPAgent when the server starts."""
    global agent
    try:
        config_file = r"C:\Users\Surya Narayanan K V\smart_glass\backend\broswer_mcp.json"
        client = MCPClient.from_config_file(config_file)
        llm = init_chat_model(
            "gemini-2.5-flash",
            model_provider="google_genai",
            temperature=0.00000001,
            top_p=0,
            max_tokens=1000,
        )

        agent = MCPAgent(
            llm=llm,
            client=client,
            max_steps=100,
            memory_enabled=True,
            system_prompt=SYSTEM_PROMPT,
        )

        # Run startup prompt
        await agent.run(STARTUP_PROMPT)
        print("Smart Glass API is ready!")

    except Exception as e:
        print(f"Failed to initialize agent: {e}")

    yield 


    print("Shutting down Smart Glass API...")


app = FastAPI(title="Smart Glass API", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    success: bool


async def chat(request):
    """Send a message to the smart glass agent"""
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        final_response = ""
        
        async for step in agent.stream(request, max_steps=30):
            if isinstance(step, str):
                final_response += step + " "
            else:
                action, observation = step
                print(f"Tool: {action.tool}, Input: {action.tool_input}")
        
        # Speak the response asynchronously
        if final_response.strip():
            asyncio.create_task(speak_text(final_response))
        
        return ChatResponse(
            response=final_response.strip(),
            success=True
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")

@app.post("/upload_raw")
async def upload_raw(request: Request):
    """Upload raw audio data from ESP32"""
    filename = request.headers.get("X-Filename", "uploaded.wav")

    data = await request.body()   # raw bytes
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as f:
        f.write(data)

    sentence = transcribe(file_path)
    if sentence:
        print(f"Transcribed: {sentence}")
        chat_response = await chat(sentence)

    else:
        print("No transcription found")

    return {"message": f"File saved as {filename}", "path": file_path}

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Smart Glass API is running"}

@app.get("/health")
async def health():
    """Health check with agent status"""
    return {
        "status": "healthy",
        "agent_ready": agent is not None
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)


