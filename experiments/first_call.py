import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

MODEL = "claude-sonnet-5"

MOTION = "This house would ban private cars from city centres"
SIDE = "For"

SUBMISSION = """Banning private cars from city centres would make cities better
places to live. When you remove cars, you remove the noise, the danger and the
pollution that comes with them. Cities like Amsterdam have shown that this works.
People would walk and cycle more, which is healthier, and businesses would benefit
from more foot traffic. The streets could be used for parks and cafes instead of
parking. Cars are a twentieth century solution to a problem that cities no longer
have, and keeping them is simply a failure of imagination."""

SYSTEM_PROMPT = "You are a debate coach. Grade the student's argument."

user_message = f"""Motion: {MOTION}
Side: {SIDE}

Argument:
{SUBMISSION}"""

response = client.messages.create(
    model=MODEL,
    max_tokens=2000,
    system=SYSTEM_PROMPT,
    messages=[
        {"role": "user", "content": user_message},
    ],
)

print("content blocks returned:", [block.type for block in response.content])
print()

text_parts = [block.text for block in response.content if block.type == "text"]
feedback = "\n".join(text_parts)

if not feedback:
    print("!! No text block came back. Probably truncated - raise max_tokens.")
else:
    print(feedback)

print("\n" + "=" * 60)
print("model:        ", response.model)
print("stop reason:  ", response.stop_reason)
print("input tokens: ", response.usage.input_tokens)
print("output tokens:", response.usage.output_tokens)