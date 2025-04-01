champion_prompt = """
    You are a smart Sales Operations Analyst that analyzes Sales calls.
    You are given a transcript of what a potential buyer of Galileo said.
    Your job is to identify the champion of the call.

    DEFINITION OF CHAMPION:
    A champion is defined as someone who really loves the product and shows strong intent towards using or buying it. In this case the product is Galileo. Only assign champion as True if someone has sung high praises of the product or has exclaimed a desire to use or buy Galileo.
    For the explanation, be specific to this peron's thoughts, comments or feelings (whether they are positive or negative).

    DEFINITION OF BUSINESS PAIN:
    Business Pain or Problem is generally derived from some technical limitations, gaps, or problems which leads to something that generally negatively impacts the business
    This problem is something that the product hoepfully solves.

    Analyze the transcript and strictly return a JSON with the following fields:
    - champion: true or false (use lowercase, JSON boolean values)
    - explanation: A one-line explanation on why this person is a champion (or not a champion)
    - business_pain: A one-line description of the pain or problem

    GUIDELINES:
    1. Base your analysis solely on the evidence in the transcript
    2. Include specific quotes or paraphrases that justify your conclusion
    3. Focus on actions and statements that indicate buying influence, not just positive comments
    4. Consider both explicit statements and implicit indicators of championship
    
    Transcript:
    {transcript}

    STRICTLY return the JSON, nothing else. Use proper JSON boolean values (true/false, not True/False).
"""

company_name_prompt = """
    Extract name of the company from this call title.
    Call title: {call_title}
    
    Rules:
    1. If the title contains " - New Deal", extract everything before it
    2. If the title contains " <> ", extract everything before it
    3. If the title contains " - ", extract everything before it
    4. Exclude suffixes like "inc", "llc", "holdings", "technologies", "group", "corp", "company", "corporation" etc. from the company name
    5. For a healthcare company, exclude "health" or "healthcare" from the company name
    6. Remove any leading/trailing whitespace
    7. If you cannot find the company name, return "Unknown Company"

    For the following companies, return their short form:
    - "American Express" -> "Amex"
    
    Examples:
    - "Notable - New Deal" -> "Notable"
    - "Intro: Cascade <> Galileo" -> "Cascade"
    - "Company Name - Some Text" -> "Company Name"
    
    Only return the name of the company.
    Assume that Galileo is not a company name.
"""