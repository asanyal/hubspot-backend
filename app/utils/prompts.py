champion_prompt = """
    You are a smart Sales Operations Analyst that analyzes Sales calls.
    You are given a transcript of what a potential buyer of Galileo said.
    Your job is to identify the champion of the call.

    DEFINITION OF CHAMPION:
    A champion is defined as someone who really loves the product and shows strong intent towards using or buying it. In this case the product is Galileo. Only assign champion as True if someone has sung high praises of the product or has exclaimed a desire to use or buy Galileo.
    For the explanation, be specific to this peron's thoughts, comments or feelings (whether they are positive or negative).

    Analyze the transcript and return a JSON with the following fields:
    - champion: true or false (use lowercase, JSON boolean values)
    - explanation: A one-line explanation on why this person is a champion (or not a champion)

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
    Infer the name of the company from the provided call title or email domain.
    Use your knowledge to infer the company being referred to.
    
    Call title or email domain: {call_title}

    RULES:
    1. If the title contains " - New Deal", extract everything before it
    2. If the title contains " <> ", extract everything before it
    3. If the title contains " - ", extract everything before it
    4. Exclude suffixes like "inc", "llc", "holdings", "technologies", "group", "corp", "company", "corporation" etc. from the company name
    5. For a healthcare company, exclude "health" or "healthcare" from the company name
    6. Remove any leading/trailing whitespace
    7. Return multiple possible variants of the company name, if applicable, such as abbreviations or common short forms (separated by spaces)
    8. If you cannot find the company name, return "Unknown Company"
    9. If the email domain is "galileo.ai", return "Unknown Company".
    10. "Galileo" or "galileo.ai" is not a company.

    For the following companies, return their short form:
    - "American Express" -> "Amex"
    - "Deutsche Bank" -> "DB"
    - "Deutsche Telekom" -> "DT"
    - "FreshWorks" -> "FW"

    Some companies have multiple names:
    - "DemandMatrix" -> "DemandBase"
    
    Examples:
    - "Notable - New Deal" -> "Notable"
    - "Intro: Cascade <> Galileo" -> "Cascade"
    - "Washington Post - New Deal" -> "Washington Post WashPost WaPo"
    - "General Dynamics Land Systems - New Deal" -> "General Dynamics Land Systems GDLS"
    - "Company Name - Some Text" -> "Company Name"

    EXCEPTIONS:
    - "ItsaCheckmate" -> "Checkmate"
    
    ONLY return the name(s) of the company in a format that could include the full name, abbreviation, or any widely recognized short form.
"""


parr_principle_prompt = """
    PAPR principle is a framework for analyzing the influence of people in a deal.
    It stands for Pain, Authority, Preference, and Role.

    Here's how it works:

    Take every influencer involved in your deal.
    Rank them on these aspects on a scale of 1-5:

    ::::: PAIN :::::
    How intense (or not) is their pain for what you solve?
    Low? Medium? High?

    ::::: AUTHORITY :::::
    How much authority do they (or could they) have on this deal?
    Low? Medium? High?


    ::::: PREFERENCE :::::
    How highly do they prefer your solution vs. someone else's?
    Low? Medium? High?

    ::::: ROLE :::::
    How involved are they in this particular decision process?
    Low? Medium? High?

    Here's an example:

    Let's say I have a director of sales involved in my deal. 

    Here's how she stacks up:

    PAIN: Very high.
    AUTHORITY: High. She's not the DM, but her voice is respected.
    PREFERENCE: Low. She prefers a competitor.
    ROLE: High. Very involved in the decision process.

    What's your move?
    You can't ignore her.
    Her authority is too high. 
    You'll lose.
    My move?
    Find an internal coach.
    Learn why she prefers the competitor.
    If it's non emotional (i.e. she doesn't HATE us, but prefers the others for rational reasons) then I can overcome it myself, I'll meet with her head-on.
    Turn a skeptic into a champion.
    But if she HATES us for some reason?
    My words may carry no influence.
    So I'll enlist my champion to sell on my behalf.
    Now. Here's where things get powerful:

    Take the opposite example:

    Let's say I have A DIFFERENT director of sales involved in my deal. 

    Here's how he stacks up:

    PAIN: Very high.
    AUTHORITY: Low. Not respected. Coach says people don't like him.
    PREFERENCE: Low. He prefers a competitor to pclub.io.
    ROLE: Somewhat high. Involved in the decision process.

    What's your move?
    Polar opposite as before.

    If I'm confident in my coach's inside knowledge on him carrying no influence?
    I'm going to ignore him.

    Box him out of the deal (I'm such a meanie I know).
    The point of all of this?

    The PAPR framework eliminate random acts of multi-threading.
    You can see that based on how they rank, your actions will differ.
    That's how you dramatically boost your win rates with multi-threading.

    Rank this person on the PAPR criteria.

    Return a JSON with the following fields:
    - pain: 1-5
    - authority: 1-5
    - preference: 1-5
    - role: 1-5
    - parr_explanation: A one-line explanation of the analysis based on the PAPR framework

    Speaker: {speaker_name}
    Transcript:
    {transcript}

    STRICTLY return only the JSON content, no prefix or suffix.
"""

buyer_intent_prompt = """
    Analyze the transcript of a sales call between a potential buyer and Galileo.

    Your goal is to assess the buyer's intent and determine whether the overall engagement is trending positively or negatively.

    Define intent based strictly on clear evidence of buyer interest or disinterest, not on generic politeness or small talk.

    Positive signals include:
        •	Expressions of urgency
        •	Explicit product enthusiasm or praise
        •	Strong alignment with pain points
        •	Clear ownership of next steps

    Negative signals include:
        •	Frustration, hesitation, or skepticism
        •	Confusion about product fit
        •	Deferral, lack of urgency, or unclear ownership

    Output must be valid JSON with the following two fields only:
        1.	"intent": One of the following values:
        •	"Less likely to buy"
        •	"Unsure"
        •	"Neutral"
        •	"Likely to buy"
        2.	"explanation": A structured string broken down into the following headers:
        •	Background & Team Context
        •	Current State & Use Cases
        •	Gap Analysis & Pain Points
        •	Positive & Negative Signals
        •	Next Steps & Requirements

    Each section should be concise and grounded only in what is explicitly said in the transcript.
    Avoid speculation.
    For ONLY the explanation section, use markdown formatting for the headers, the text etc.
    Return only the JSON response, no commentary or explanation before or after.

    Seller: {seller_name}
    Transcript: {call_transcript}

    STRICTLY return the JSON, nothing prefix or suffix.
"""

pricing_concerns_prompt = """
    Analyze the transcripts below and see if there are any pricing concerns.
    Note: Galileo is the seller, not the buyer. Only analyze the buyer's concerns.
    Return a JSON with the following fields:
    - pricing_concerns: true or false (use lowercase, JSON boolean values)
    - explanation: A one-line explanation on why this person has pricing concerns (or not)

    Transcript:
    {transcript}

    STRICTLY return the JSON, nothing else.
"""

no_decision_maker_prompt = """
    Your task is to analyze the transcripts below and see if there are any decision makers.
    Note: Galileo is the seller, not the buyer. Only analyze the buyer's concerns.
    Analyze at the Background & Team Context from the transcripts
    - If the analysis yields that any of the speakers is a Manager of teams, Director, VP, C-level or Cofounder, then they are a decision maker.
    - If the analysis yields that the they are a developer (engineer), then they are not a decision maker.

    Return a JSON with the following fields:
    - no_decision_maker: true or false (use lowercase, JSON boolean values)
    - explanation: A one-line explanation on why this person is not a decision maker (or is)

    Transcript:
    {transcript}

    STRICTLY return the JSON, nothing else.
"""

already_has_vendor_prompt = """
    analyze the transcripts below and see if the buyer already has a vendor.
    Vendors can be competitors or tools that are being built internally by the buyer.
    Note: Galileo is the seller, not the buyer. Only analyze the buyer's concerns.
    Competitors of Galileo are:
    - Braintrust
    - LangSmith
    - Vellum
    - LangFuse
    - Arize or Phoenix
    - Comet (Opik)
    - Helicone
    - HoneyHive
    - PromptFoo
    - LangWatch
    - Any other LLM Evaluation or Observability tools

    Return a JSON with the following fields:
    - already_has_vendor: true or false (use lowercase, JSON boolean values)
    - explanation: A one-line explanation on why this person already has a vendor (or not)

    Transcript:
    {transcript}

    STRICTLY return the JSON, nothing else.
"""
