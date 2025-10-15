import os
import openai

# Set API key
openai.api_key = os.getenv("OPENAI_API_KEY")
model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")



def generate_react_code(prompt: str) -> str:
    """
    Generates React code using OpenAI (or any other AI model).
    """
    if not prompt:
        raise ValueError("Prompt cannot be empty")

    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an AI React code generator."},
                {"role": "user", "content": f"Generate optimized React code for: {prompt}"}
            ],
            temperature=0.3
        )

        return response.choices[0].message["content"]

    except Exception as e:
        raise RuntimeError(f"Error generating code: {e}")
