from firecrawl import FirecrawlApp
from app.services.llm_service import ask_openai, ask_anthropic
import os
from dotenv import load_dotenv
import json
from colorama import Fore, Style
from app.utils.prompts import company_name_prompt
load_dotenv()

def get_company_analysis(deal_name: str) -> str:
    app = FirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))

    company_name = ask_anthropic(
        user_content=company_name_prompt.format(call_title=deal_name),
        system_content="You are a smart financial analyst"
    )
    company_name = company_name.strip()
    url = ask_openai(
        system_content=f"You are a smart financial analyst",
        user_content=f"""
            What's the full website URL of the company associated with the company: "{company_name}". 
            Only return the main URL (home page) of the company. Skip any subdomains.
            If you cannot return a URL, return "None"
        """
    )
    if url == "None":
        return "Could not retrieve company information."
    print(Fore.GREEN + f"Scraping URL: {url}" + Style.RESET_ALL)
    scraped_data = app.scrape_url(
        url, 
        params={
            'onlyMainContent': True
        }, 
    )
    formatted_crawl_result = json.dumps(scraped_data, indent=4)
    user_content = f"""
        Your are given a company name and a scraped website data.
        Your task is to analyze the website data and provide a summary of the company.
        Here is the scraped data for the company {deal_name}:
        {formatted_crawl_result}
        Return a short (2-3 sentences) summary of what the company does, including its main products or services. 
        Optionally describe the types of users or customers the company targets, including specific industries, roles, or user personas.
    """
    response = ask_openai(
        system_content=f"You are a smart research analyst",
        user_content=user_content
    )
    return response