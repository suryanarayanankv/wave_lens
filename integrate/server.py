from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import asyncio
import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from prompt import SYSTEM_PROMPT, STARTUP_PROMPT
from mcp_use import MCPAgent, MCPClient
from streaming_tts import speak_text
from contextlib import asynccontextmanager
from stt import transcribe
from langchain.chat_models import init_chat_model

# Load environment variables
load_dotenv()

agent = None
gemini_client = None  # Native Gemini client
latest_image_path = None
pending_image_path = None
image_upload_time = None
AUDIO_WAIT_TIMEOUT = 30

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MCPAgent and Gemini client when the server starts."""
    global agent, gemini_client
    try:
        # Initialize native Gemini client (for image processing)
        gemini_client = genai.Client()
        print("✅ Native Gemini client initialized successfully")
        
        # Initialize MCP Agent (for text-only queries with tools)
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
        print("✅ Smart Glass API is ready!")

    except Exception as e:
        print(f"❌ Failed to initialize: {e}")

    yield 

    print("Shutting down Smart Glass API...")

app = FastAPI(title="Smart Glass API", lifespan=lifespan)

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    success: bool

async def chat_with_image_native(text_prompt, image_path):
    """Send a message with image using native Gemini client"""
    if not gemini_client:
        raise HTTPException(status_code=500, detail="Gemini client not initialized")
    
    try:
        print(f"🔍 Processing image: {image_path}")
        print(f"🔍 With prompt: {text_prompt}")
        
        # Read image bytes (same as your working code)
        with open(image_path, 'rb') as f:
            image_bytes = f.read()
        
        print(f"✅ Image loaded: {len(image_bytes)} bytes")
        
        # Use native Gemini API (same as your working code)
        response = gemini_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg'),
                text_prompt
            ]
        )
        
        final_response = response.text
        print(f"✅ Got response from Gemini: {len(final_response)} characters")
        
        # Speak the response asynchronously
        if final_response.strip():
            asyncio.create_task(speak_text(final_response))
        
        return ChatResponse(
            response=final_response.strip(),
            success=True
        )
        
    except Exception as e:
        print(f"❌ Error processing image message: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing image message: {str(e)}")

async def chat(request):
    """Send a message to the smart glass agent (text-only, with tools)"""
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        print(f"🔍 Processing text query: {request}")
        
        final_response = ""
        
        async for step in agent.stream(request, max_steps=30):
            if isinstance(step, str):
                final_response += step + " "
            else:
                action, observation = step
                print(f"🔧 Tool: {action.tool}, Input: {action.tool_input}")
        
        print(f"✅ Got text response: {len(final_response)} characters")
        
        # Speak the response asynchronously
        if final_response.strip():
            asyncio.create_task(speak_text(final_response))
        
        return ChatResponse(
            response=final_response.strip(),
            success=True
        )
        
    except Exception as e:
        print(f"❌ Error processing text message: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")

def check_pending_image():
    """Check if there's a pending image waiting for audio within timeout"""
    global pending_image_path, image_upload_time
    
    if pending_image_path and image_upload_time:
        elapsed_time = time.time() - image_upload_time
        if elapsed_time <= AUDIO_WAIT_TIMEOUT:
            return pending_image_path
        else:
            print(f"⏰ Image timeout exceeded ({elapsed_time:.1f}s), clearing pending image")
            pending_image_path = None
            image_upload_time = None
    
    return None

async def process_audio_with_pending_image(sentence, image_path):
    """Process audio with the pending image"""
    global pending_image_path, image_upload_time
    
    try:
        print(f"🎤+📷 Processing audio '{sentence}' with image: {image_path}")
        chat_response = await chat_with_image_native(sentence, image_path)
        
        # Clear pending image after processing
        pending_image_path = None
        image_upload_time = None
        
        return chat_response
        
    except Exception as e:
        print(f"❌ Error processing audio with image: {e}")
        # Clear pending image on error
        pending_image_path = None
        image_upload_time = None
        raise

@app.post("/upload_raw")
async def upload_raw(request: Request):
    """Upload raw audio data from ESP32"""
    filename = request.headers.get("X-Filename", "uploaded.wav")

    data = await request.body()
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as f:
        f.write(data)

    print(f"🎤 Audio uploaded: {filename} ({len(data)} bytes)")

    sentence = transcribe(file_path)
    if sentence:
        print(f"🎤 Transcribed: '{sentence}'")
        
        # Check if there's a pending image waiting for this audio
        pending_image = check_pending_image()
        
        if pending_image:
            # Process audio with the pending image
            try:
                chat_response = await process_audio_with_pending_image(sentence, pending_image)
                return {
                    "message": f"Audio processed with image: {filename}",
                    "path": file_path,
                    "transcription": sentence,
                    "processed_with_image": True,
                    "image_path": pending_image,
                    "response": chat_response.response,
                    "success": True
                }
            except Exception as e:
                return {
                    "message": f"Error processing audio with image: {filename}",
                    "path": file_path,
                    "transcription": sentence,
                    "processed_with_image": True,
                    "image_path": pending_image,
                    "error": str(e),
                    "success": False
                }
        else:
            # Process audio only (no pending image)
            try:
                chat_response = await chat(sentence)
                return {
                    "message": f"Audio processed: {filename}",
                    "path": file_path,
                    "transcription": sentence,
                    "processed_with_image": False,
                    "response": chat_response.response,
                    "success": True
                }
            except Exception as e:
                return {
                    "message": f"Error processing audio: {filename}",
                    "path": file_path,
                    "transcription": sentence,
                    "processed_with_image": False,
                    "error": str(e),
                    "success": False
                }
    else:
        print("❌ No transcription found")
        return {
            "message": f"File saved as {filename}",
            "path": file_path,
            "transcription": None,
            "error": "No transcription found",
            "success": False
        }

@app.post("/upload_image")
async def upload_image(request: Request):
    """Upload image data from ESP32"""
    global latest_image_path, pending_image_path, image_upload_time
    
    filename = request.headers.get("X-Filename", f"photo_{int(time.time())}.jpg")
    
    data = await request.body()
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    with open(file_path, "wb") as f:
        f.write(data)
    
    # Update the latest image path
    latest_image_path = file_path
    
    # Set as pending image waiting for audio
    pending_image_path = file_path
    image_upload_time = time.time()
    
    print(f"📷 Image saved and set as pending: {filename} ({len(data)} bytes)")
    print(f"⏰ Waiting for audio input within {AUDIO_WAIT_TIMEOUT} seconds...")
    
    return {
        "message": f"Image saved as {filename} - waiting for audio input",
        "path": file_path,
        "size": len(data),
        "status": "waiting_for_audio",
        "timeout_seconds": AUDIO_WAIT_TIMEOUT,
        "success": True
    }

@app.get("/status")
async def get_status():
    """Get current status of pending operations"""
    global pending_image_path, image_upload_time
    
    status = {
        "agent_ready": agent is not None,
        "gemini_ready": gemini_client is not None,
        "latest_image": latest_image_path,
        "pending_image": None,
        "time_remaining": 0
    }
    
    if pending_image_path and image_upload_time:
        elapsed_time = time.time() - image_upload_time
        time_remaining = max(0, AUDIO_WAIT_TIMEOUT - elapsed_time)
        
        if time_remaining > 0:
            status["pending_image"] = pending_image_path
            status["time_remaining"] = int(time_remaining)
        else:
            # Clear expired pending image
            pending_image_path = None
            image_upload_time = None
    
    return status

@app.post("/clear_pending")
async def clear_pending():
    """Clear any pending image (for testing/debugging)"""
    global pending_image_path, image_upload_time
    
    pending_image_path = None
    image_upload_time = None
    
    return {"message": "Pending image cleared", "success": True}

@app.post("/test_image")
async def test_image_processing():
    """Test endpoint to verify image processing works"""
    global latest_image_path
    
    if not latest_image_path or not os.path.exists(latest_image_path):
        return {
            "error": "No recent image found",
            "success": False
        }
    
    try:
        test_response = await chat_with_image_native(
            "Describe this image in detail.", 
            latest_image_path
        )
        
        return {
            "message": "Image processing test successful",
            "image_path": latest_image_path,
            "response": test_response.response,
            "success": True
        }
    except Exception as e:
        return {
            "error": f"Image processing test failed: {str(e)}",
            "image_path": latest_image_path,
            "success": False
        }

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "Smart Glass API is running"}

@app.get("/health")
async def health():
    """Health check with all components status"""
    return {
        "status": "healthy",
        "agent_ready": agent is not None,
        "gemini_ready": gemini_client is not None,
        "upload_dir": UPLOAD_DIR,
        "pending_image": pending_image_path is not None
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)