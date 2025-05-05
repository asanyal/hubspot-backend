import os
from openai import OpenAI
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

def estimate_token_count(text: str) -> int:
    """
    Estimate the number of tokens in a text string.
    This is a rough approximation - OpenAI's tokenizer is more sophisticated.
    """
    # Rough approximation: 1 token ≈ 4 characters for English text
    return len(text) // 4

def ask_openai(system_content: str, user_content: str) -> str:
    """
    Ask OpenAI a question with system and user content.
    Handles token limit errors by truncating content if necessary.
    """
    try:
        # Estimate total tokens
        total_tokens = estimate_token_count(system_content + user_content)
        max_tokens = 120000  # Leave some buffer from the 128k limit
        
        if total_tokens > max_tokens:
            # Calculate how much to truncate
            excess_tokens = total_tokens - max_tokens
            excess_chars = excess_tokens * 4  # Convert back to characters
            
            # Truncate user content (since it's usually the longer part)
            if len(user_content) > excess_chars:
                user_content = user_content[:-excess_chars] + "..."
                print(f"Warning: Content truncated to fit token limit. Original length: {total_tokens} tokens")
        
        api_key = os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        if "context_length_exceeded" in str(e):
            print(f"Error: Content too long ({total_tokens} tokens). Attempting to truncate...")
            # If we still hit the limit, try more aggressive truncation
            user_content = user_content[:100000] + "..."  # Truncate to roughly 25k tokens
            try:
                response = client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    messages=[
                        {"role": "system", "content": system_content},
                        {"role": "user", "content": user_content}
                    ]
                )
                return response.choices[0].message.content
            except Exception as e2:
                print(f"Error after truncation: {str(e2)}")
                return "Error: Content too long even after truncation"
        else:
            print(f"Error in ask_openai: {str(e)}")
            return "Error: Failed to get response from OpenAI"


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
    output = response.content[0].text.replace("```markdown", "").replace("```code", "").replace("```html", "").replace("```", "").replace('\n', ' ').replace("```json", "").replace("json", "")
    return output.strip()
