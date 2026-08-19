import os

from openai import OpenAI

client = OpenAI(
    base_url=os.environ["FOUNDRY_CHAT_BASE_URL"],
    api_key=os.environ["FOUNDRY_API_KEY"],
)

response = client.chat.completions.create(
    model=os.environ.get("MODEL_DEPLOYMENT_NAME", "zai-org--glm-47-flash"),
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
