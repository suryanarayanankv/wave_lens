import time
from elevenlabs.client import ElevenLabs

ELEVENLABS_API_KEY = ""

def transcribe(audio_path: str) -> str:
    """
    Transcribe audio file using ElevenLabs, print each sentence, and return full concatenated text.
    Also prints the time taken for transcription.
    """
    full_text = ""
    try:
        elevenlabs = ElevenLabs(api_key=ELEVENLABS_API_KEY)

        # Start timer
        start_time = time.time()

        with open(audio_path, "rb") as audio_file:
            transcription = elevenlabs.speech_to_text.convert(
                file=audio_file,
                model_id="scribe_v1",
                tag_audio_events=True,
                language_code="eng",
                diarize=True,
            )

        # End timer
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"[STT] Transcription took {elapsed_time:.2f} seconds")

        if transcription.text:
            print("[STT] Transcription:")
            # Split the transcription into sentences for printing (similar to original format)
            sentences = transcription.text.split('. ')
            for sentence in sentences:
                if sentence.strip():
                    # Add period back if it's not the last sentence
                    text = sentence.strip()
                    if not text.endswith('.') and sentence != sentences[-1]:
                        text += '.'
                    print(f"[STT] {text}")
                    full_text += text + " "
            full_text = full_text.strip()
        else:
            print("[STT] No transcription found")

    except Exception as e:
        print(f"STT Exception: {e}")

    return full_text
