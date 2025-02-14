from openai import OpenAI

client = OpenAI(
  api_key="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"
)

completion = client.chat.completions.create(
  model="gpt-4o-mini",
  store=True,
  messages=[
    {"role": "user", "content": "write a haiku about ai"}
  ]
)

print(completion.choices[0].message);
