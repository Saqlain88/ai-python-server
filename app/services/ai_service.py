import os

from openai import OpenAI

client = OpenAI(
  api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
)
model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
client = OpenAI()

def generate_react_code(prompt: str) -> str:
    """
    Generates React code using OpenAI (or any other AI model).
    """
    if not prompt:
        raise ValueError("Prompt cannot be empty")

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an AI React code generator."},
                {"role": "user", "content": f"Generate optimized React code for: {prompt}"}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content

    except Exception as e:
        raise RuntimeError(f"Error generating code: {e}")
