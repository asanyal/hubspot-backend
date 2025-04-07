from app.services.llm_service import ask_anthropic
from app.utils.prompts import company_name_prompt

def extract_company_name(call_title):
    """Extract company name from call title"""
    response = ask_anthropic(
        user_content=company_name_prompt.format(call_title=call_title),
        system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
    )
    return response.strip() 
