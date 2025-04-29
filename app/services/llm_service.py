import os
from openai import OpenAI
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

def ask_openai(
    user_content,
    system_content="You are a smart assistant", 
    model="gpt-4o-mini"
):
    api_key = os.getenv("OPENAI_API_KEY")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
    )
    output = response.choices[0].message.content.replace("```markdown", "").replace("```code", "").replace("```html", "").replace("```", "").replace('\n', ' ')
    return output


def ask_anthropic(
    user_content,
    system_content="You are a smart assistant",
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    model="claude-3-7-sonnet-20250219"
):
    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        system=system_content,
        messages=[
            {"role": "user", "content": user_content}
        ],
        max_tokens=1024,
        temperature=0
    )
    output = response.content[0].text.replace("```markdown", "").replace("```code", "").replace("```html", "").replace("```", "").replace('\n', ' ')
    return output
