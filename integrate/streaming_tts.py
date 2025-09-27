import os
import asyncio
import pyaudio
import aiohttp
import wave
import datetime
from dotenv import load_dotenv
import time

# Load API key from .env or fallback
load_dotenv()
API_KEY = os.getenv("DEEPGRAM_API_KEY") or "c91848dd358152b1231646a2c9663dfdb02cf8b6"

# Deepgram TTS settings
TTS_MODEL = "aura-2-thalia-en"
DEEPGRAM_TTS_URL = f"https://api.deepgram.com/v1/speak?model={TTS_MODEL}&encoding=linear16&container=wav&sample_rate=24000"

# Audio playback constants (fixed for this model/encoding)
SAMPLE_RATE = 24000        # Frames per second
CHANNELS = 1               # Mono
FORMAT = pyaudio.paInt16   # 16-bit PCM (2 bytes per sample)
SAMPLE_WIDTH = 2          # Bytes per sample
CHUNK = 4800  # Bytes per read (~0.2s of audio at 24kHz mono)

# Folder for saving audio history
AUDIO_HISTORY_DIR = "audio_history"
os.makedirs(AUDIO_HISTORY_DIR, exist_ok=True)


async def speak_text(text: str, debug=True) -> str:
    """
    Converts text to speech using Deepgram TTS, streams playback, 
    and saves it to a timestamped file in audio_history/.
    """
    # Create unique file name
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = os.path.join(AUDIO_HISTORY_DIR, f"{timestamp}.wav")

    headers = {
        "Authorization": f"Token {API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"text": text}

    # Open PyAudio stream
    p = pyaudio.PyAudio()
    
    # IMPORTANT: Use frames (samples) for frames_per_buffer, not bytes
    FRAMES_PER_BUFFER = CHUNK // SAMPLE_WIDTH  # 2400 frames
    
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    output=True,
                    frames_per_buffer=FRAMES_PER_BUFFER)

    audio_frames = []
    audio_buffer = b''  # Buffer to accumulate data
    
    # Debug variables
    chunk_count = 0
    start_time = time.time()
    last_chunk_time = start_time

    async with aiohttp.ClientSession() as session:
        async with session.post(DEEPGRAM_TTS_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                print("Failed to get audio stream:", await resp.text())
                return None

            print("[INFO] Sample width:", SAMPLE_WIDTH, "bytes")
            print(f"[INFO] Frame size: {SAMPLE_WIDTH} bytes (channels={CHANNELS})")
            print(f"[INFO] Bytes per chunk: {CHUNK}")
            print("Speaking response...")

            async for chunk in resp.content.iter_chunked(CHUNK):
                if not chunk:
                    continue
                    
                chunk_count += 1
                current_time = time.time()
                
                if debug:
                    gap = (current_time - last_chunk_time) * 1000
                    print(f"Chunk #{chunk_count}: {len(chunk)} bytes, gap: {gap:.1f}ms")
                    
                    # First chunk timing
                    if chunk_count == 1:
                        ttfb = (current_time - start_time) * 1000
                        print(f"⚡ Time to first byte: {ttfb:.0f}ms")
                
                # Add chunk to buffer
                audio_buffer += chunk
                audio_frames.append(chunk)  # Save all chunks for file
                
                # Play complete frames from buffer
                while len(audio_buffer) >= CHUNK:
                    # Extract exactly CHUNK bytes (which equals FRAMES_PER_BUFFER frames)
                    frame_data = audio_buffer[:CHUNK]
                    audio_buffer = audio_buffer[CHUNK:]  # Remove played data
                    
                    # Ensure even number of bytes (for 16-bit samples)
                    if len(frame_data) % 2 != 0:
                        frame_data = frame_data[:-1]  # Remove last byte if odd
                        if debug:
                            print("⚠️  Trimmed odd byte from frame")
                    
                    # Play the frame
                    stream.write(frame_data)
                    if debug:
                        print(f"✅ Played frame: {len(frame_data)} bytes")
                
                last_chunk_time = current_time

            # Play any remaining buffered data
            if len(audio_buffer) > 0:
                # Ensure even length
                if len(audio_buffer) % 2 != 0:
                    audio_buffer = audio_buffer[:-1]
                
                if len(audio_buffer) > 0:
                    stream.write(audio_buffer)
                    if debug:
                        print(f"✅ Played final buffer: {len(audio_buffer)} bytes")

    stream.stop_stream()
    stream.close()
    p.terminate()

    # Save the complete audio to a WAV file
    with wave.open(output_file, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b''.join(audio_frames))

    # Final debug summary
    if debug:
        total_time = time.time() - start_time
        audio_duration = len(b''.join(audio_frames)) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)
        print(f"📊 Total chunks: {chunk_count}, Total time: {total_time:.1f}s, Audio duration: {audio_duration:.1f}s")

    print(f"Audio saved as: {output_file}")
    return output_file
