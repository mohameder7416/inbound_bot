import os
import openai
from dotenv import load_dotenv

# Load the .env file
load_dotenv()

# Set the OpenAI API key from the environment
openai.api_key = os.getenv("OPENAI_API_KEY")

def call_openai_llm(system_prompt, user_prompt, model="gpt-4"):
    """
    Calls OpenAI's chat completion API with a system and user prompt.

    Args:
        system_prompt (str): The system message to guide the LLM behavior.
        user_prompt (str): The user's actual query or message.
        model (str): The model to use (default is "gpt-3.5-turbo").

    Returns:
        str: The assistant's response.
    """
    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return response.choices[0].message['content'].strip()
    except Exception as e:
        return f"Error: {e}"
