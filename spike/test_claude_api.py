"""
Day 5, step 1: confirm basic Claude API access works before building
anything RAG-related on top of it.
"""

import os
from anthropic import Anthropic

# claude-haiku-5-5: the cheapest current model, which is all a connectivity
# check needs. The earlier claude-sonnet-4-5 here was printing a deprecation
# warning on every run - it retires 30 Nov 2026.
MODEL = "claude-haiku-5-5"

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    raise RuntimeError(
        "ANTHROPIC_API_KEY not found in environment. "
        "Set it with: setx ANTHROPIC_API_KEY \"your-key-here\" "
        "then reopen your terminal."
    )

client = Anthropic(api_key=api_key)

print(f"Sending a test request to Claude API ({MODEL})...")
response = client.messages.create(
    model=MODEL,
    max_tokens=100,
    messages=[
        {"role": "user", "content": "Reply with exactly: API connection successful."}
    ]
)

print()
print("Response received:")
print(response.content[0].text)
print()
print("If you see 'API connection successful' above, the connection works.")
