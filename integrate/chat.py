# main.py
import asyncio
import time
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from prompt import SYSTEM_PROMPT, STARTUP_PROMPT
from mcp_use import MCPAgent, MCPClient
from streaming_tts import speak_text  

async def main():
    load_dotenv()

    config_file = r"C:\Users\Surya Narayanan K V\smart_glass\backend\broswer_mcp.json"
    client = MCPClient.from_config_file(config_file)
    llm = init_chat_model(
        "gemini-2.5-flash",
        model_provider="google_genai",
        temperature=0.0
    )

    agent = MCPAgent(
        llm=llm,
        client=client,
        max_steps=100,
        memory_enabled=True,
        system_prompt=SYSTEM_PROMPT
    )
    
    print("Welcome to Smart Glass Chatbot! Type 'exit' to quit.\n")
    # Initial startup message
    start_startup = time.time()
    response = await agent.run(STARTUP_PROMPT)
    end_startup = time.time()
    print("Startup AI Response:", response)
    print(f"⏱ Startup response time: {end_startup - start_startup:.2f} seconds\n")
    await speak_text(response)  # Speak the initial message

    while True:
        user_input = await asyncio.to_thread(input, "You: ")
        if user_input.strip().lower() in {"exit", "quit"}:
            print("Goodbye!")
            break

        query_start = time.time()  # Start timer for user query
        final_response = ""
        async for step in agent.stream(user_input, max_steps=30):
            if isinstance(step, str):
                print("AI:", step)
                final_response += step + " "  # Collect LLM response text
            else:
                action, observation = step
                print("Calling:", action.tool)
                print("Input:", action.tool_input)

                # If observation is large, just show first 20 chars
                obs_preview = observation[:20] if isinstance(observation, str) else str(observation)
                print("Observation:", obs_preview)

        query_end = time.time()  # End timer for user query
        elapsed = query_end - query_start
        print(f"⏱ Time taken for this query: {elapsed:.2f} seconds\n")

        # Speak full LLM response after streaming finishes
        if final_response.strip():
            await speak_text(final_response)

if __name__ == "__main__":
    asyncio.run(main())
