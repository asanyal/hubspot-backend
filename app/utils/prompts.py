champion_prompt = """
You are a Sales Operations Analyst tasked with analyzing sales call transcripts to identify champions.

You are given a transcript that includes what a potential buyer said during a call about Galileo.

---

**DEFINITION OF A CHAMPION:**  
A champion is someone who **actively supports** Galileo internally and **demonstrates clear intent to use, advocate for, or help drive the purchase** of the product. Champions often express:
- Strong personal enthusiasm for Galileo's value
- Clear alignment with Galileo’s mission or pain points it solves
- Ownership of next steps (e.g. initiating a trial, sharing with internal stakeholders)
- Influence within the organization (e.g. decision-making role, introducing Galileo to others)

**Important:**  
Do **not** label someone as a champion just because they are polite or mildly positive. Only mark `true` if there is strong, action-oriented advocacy.

---

**Return this JSON output only:**
- `"champion"`: `true` or `false` (JSON boolean, lowercase only)
- `"explanation"`: A single sentence clearly justifying your conclusion. Mention specific quotes or paraphrased comments from the transcript that demonstrate (or disprove) champion behavior.

---

**GUIDELINES:**
1. Use only the content from the transcript; avoid assumptions.
2. Look for both **explicit statements** (e.g. "we really want to buy this") and **implicit actions** (e.g. "I'll share this with my VP").
3. Focus on **buying influence and intent**, not just product appreciation.

---

Transcript:
{transcript}

STRICTLY return a JSON object. No extra commentary, no markdown. Use proper JSON boolean values (`true` / `false` only).
"""

company_name_prompt = """
    Infer the name of the company from the provided title.
    Use your knowledge to infer the company being referred to.
    
    Title: {call_title}

    INSTRUCTIONS:
    1. The returned list should be comma separated.
    2. If the title contains " - New Deal", extract everything before it
    3. Exclude suffixes like "inc", "llc", "holdings", "technologies", "group", "corp", "company", "corporation" etc. from the company name
    4. For a healthcare company, EXCLUDE "health" or "healthcare" from the company name
    5. Return multiple possible variants of the company name, if applicable, such as abbreviations or common short forms (separated by spaces)
    6. If you cannot find the company name, return "Unknown Company"
    7. If the email domain is "galileo.ai", return "Unknown Company".
    8. Galileo, galileo.ai, Run Galileo, rungalileo.io are not companies.
    9. EXCLUDE or ignore "Galileo" in all cases.
    10. Title may also contain a team name 
    11. Gong, Zoom, Teams are not companies.
    e.g. "Deutsche Bank - Bank on Tech (BOT)". In this case, extract both the company name, the team name and all abbreviations possible e.g. "Deutsche Bank, DB, Bank of Tech, BOT"

    For companies that are well known by their short form, INCLUDE the short form in the output (separated by commas):
    - "American Express" -> "American Express, Amex"
    - "Deutsche Bank" -> "Deutsche Bank, DB"
    - "Deutsche Telekom" -> "Deutsche Telekom, DT"
    - "FreshWorks" -> "FreshWorks, FW"
    - "Bank of America" -> "Bank of America, BofA"

    Some companies have multiple names:
    - "DemandMatrix" -> "DemandBase"

    Examples:
    - "Notable - New Deal" -> "Notable"
    - "Intro: Cascade <> Galileo" -> "Cascade"
    - "Intro: Cascade Health <> Galileo" -> "Cascade"
    - "Washington Post - New Deal" -> "Washington Post, WashPost, WaPo"
    - "General Dynamics Land Systems - New Deal" -> "General Dynamics Land Systems, GDLS"
    - "Company Name - Some Text" -> "Company Name"

    EXCEPTIONS:
    - "ItsaCheckmate" -> "Checkmate"
    
    ONLY return the name of the company and any short abbreviations (if applicable) in a comma-separated format.
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
Analyze the call transcript of a sales meeting between a potential buyer and Galileo.

Your objective is to **evaluate the buyer's purchasing intent**, based strictly on **explicit, action-oriented signals**, not on tone, politeness, or generic enthusiasm.

**Important: Positive sentiment alone is *not* a reliable indicator of buying intent.** Only use clear behavioral or verbal evidence when determining buyer intent.

---

**Valid buying intent signals (Likely to Buy):**
- Explicitly asking for pricing, or implementation steps
- Stating specific pain points that Galileo can solve, with urgency
- Assigning team members or setting dates to evaluate/test/buy
- Mentioning budget or decision-making timelines
- Referencing internal alignment or championing efforts

**Valid disinterest signals (Less Likely to Buy):**
- Expressing confusion about Galileo's value or differentiation
- Expressing any kind of frustration
- Stating they are not a decision maker or their team is not the ideal fit
- Stalling behavior: no urgency, no follow-up ownership
- Sharing concerns or blockers to using Galileo

---

Return a **valid JSON** object with the following fields:

1. "intent": One of these values only  
   - "Less likely to buy"  
   - "Neutral"  
   - "Likely to buy"  
   **Be conservative** — only mark "Likely to buy" if strong buying actions or commitments are stated.

2. "explanation": Use this structure in markdown formatting. Each section should capture as much detail from the call and based only on the transcript (no assumptions):

   - ## Background & Team Context  
   - ## Current State & Use Cases  
   - ## Gap Analysis & Pain Points  
   - ## Positive & Negative Signals  
   - ## Next Steps & Requirements

---

INSTRUCTIONS:
- Each section must be directly grounded in the transcript, no speculation.
- Avoid inflating intent due to enthusiasm unless linked to action.
- Do not include any preamble or explanation — return ONLY the JSON object as output.

Seller: {seller_name}  
Transcript: {call_transcript}
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
    Your task is to analyze the transcripts below and see if there are any decision makers on the call.
    A decision maker is someone that has "AUTHORITY".

    ::::: AUTHORITY :::::
    How much authority do they (or could they) have on this deal?
    Low? Medium? High?

    ::::: ROLE :::::
    How involved are they in this particular decision process?
    Low? Medium? High?

    Here's an example:

    Let's say I have a director of engineering involved in my deal. 
    Here's how she stacks up:
    AUTHORITY: High. Even if she's not a direct decision maker, her voice is respected.
    ROLE: High. Very involved in the decision process.

    Let's say I have A DIFFERENT Director involved in this deal. 

    Here's how he stacks up:
    AUTHORITY: Low. Not respected. People don't like him.
    ROLE: Somewhat high. Involved in the decision process.

    Individual contributors (software engineers, data scientists are very likely not decision makers)

    NOTE
    Galileo is the seller. Only analyze the buyer's concerns. Analyze at the Background & Team Context from the transcripts
    - If the analysis yields that any of the speakers has high authority and high role - very likely they are a strong decision maker
    - If the analysis yields that any of the speakers has low authority and high role - very likely they are still a decision maker
    - If the analysis yields that the they are a developer (engineer), then they are not a decision maker.

    Rank this person based on:
    - authority: 0-5
    - role: 0-5

    Whether they are a decision maker or not depends on the average score of the authority and the role.
    If the score is closer to 5, they will be a decision maker.

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
    NOTE:
    Galileo is the seller, not the buyer.
    Galileo cannot be a competitor.
    Only analyze the buyer's concerns. Competitors of Galileo include:
    - Braintrust
    - LangSmith
    - Lakera AI
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
