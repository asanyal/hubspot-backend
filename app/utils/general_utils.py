from app.services.llm_service import ask_openai
from app.utils.prompts import company_name_prompt
from colorama import Fore, Style

def extract_company_name(call_title_or_deal_name):
    """Extract company name from call title"""
    response = ask_openai(
        user_content=company_name_prompt.format(call_title=call_title_or_deal_name),
        system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
    )
    print(Fore.MAGENTA + f"Extracted company name: {response}" + Style.RESET_ALL)
    return response.strip() 
