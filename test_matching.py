#!/usr/bin/env python3
import re
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize

# Download required NLTK data (run once)
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

def filter_filler_words(text: str) -> set:
    """
    Filter out filler words, special characters, and noisy words from text.
    Returns a set of meaningful words.
    """
    if not text:
        return set()
    
    # Remove special characters and convert to lowercase
    text = re.sub(r'[^\w\s]', ' ', text.lower())
    
    # Tokenize the text
    tokens = word_tokenize(text)
    
    # Get English stopwords
    stop_words = set(stopwords.words('english'))
    
    # Add custom noisy words
    custom_noise = {
        # existing
        'and', 'or', '&', 'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'with', 'by',
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did',
        'will', 'would', 'could', 'should', 'may', 'might', 'can', 'must', 'shall',
        'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
        'me', 'him', 'her', 'us', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their',
        'mine', 'yours', 'hers', 'ours', 'theirs', 'myself', 'yourself', 'himself', 'herself',
        'itself', 'ourselves', 'yourselves', 'themselves',
        'call', 'meeting', 'demo', 'discussion', 'talk', 'chat', 'conversation',
        'zoom', 'teams', 'webex', 'google', 'meet', 'video', 'audio', 'phone',
        'schedule', 'scheduled', 'calendar', 'invite', 'invitation', 'join',
        'gong', 'recording', 'transcript', 'session', 'webinar', 'presentation', 'bank',

        # generic AI/product words
        'ai', 'land', 'platform', 'monitor', 'observe', 'genai', 'gen', 'generative',
        'evaluate', 'protect', 'users', 'team', 'enterprise', 'cloud', 'digital', 'innovation',

        # very common business suffixes
        'group', 'company', 'inc', 'inc.', 'llc', 'corp', 'corporation', 'co', 'co.', 
        'plc', 'limited', 'ltd', 'pty', 'se', 'ag',

        # industry generic
        'automation', 'business', 'global', 'international', 'technologies', 'technology',
        'systems', 'solutions', 'services', 'network', 'networks', 'financial', 'capital', 
        'federal', 'holdings', 'associates', 'industries', 'partners', 'consulting',
        'digital', 'analytics',

        # suffix add-ons found in your list
        'labs', 'lab', 'studio', 'brands', 'health', 'care', 'ventures', 'markets', 'exchange',

        # filler / context words
        'new', 'deal', 'renewal', 'opp', 'pilot', 'project', 'team', 'cohort', 'fast', 'start',
        'oem', 'service', 'services', 'business', 'governance', 'central', 'office'
    }
        
    # Combine stopwords with custom noise
    all_noise = stop_words.union(custom_noise)
    
    # Filter out noise words and short words (less than 2 characters)
    meaningful_words = {
        token for token in tokens 
        if token not in all_noise and len(token) >= 2
    }
    
    return meaningful_words

def test_matching(deal_name: str, meeting_title: str) -> bool:
    """
    Test if a deal name matches a meeting title using the same logic as get_call_id.
    Returns True if there's a match, False otherwise.
    """
    print(f"\n{'='*80}")
    print(f"TESTING MATCH")
    print(f"Deal: '{deal_name}'")
    print(f"Meeting: '{meeting_title}'")
    print(f"{'='*80}")
    
    # Split deal name into synonyms (same as get_call_id logic)
    company_synonyms = deal_name.split(",")
    
    # Filter out filler words from meeting title
    meeting_tokens = filter_filler_words(meeting_title)
    print(f"Meeting tokens: {meeting_tokens}")
    print()
    
    # Check each synonym
    for synonym in company_synonyms:
        synonym = synonym.strip()
        synonym_tokens = filter_filler_words(synonym)
        
        print(f"Synonym: '{synonym}' -> Tokens: {synonym_tokens}")
        
        # Check if any meaningful tokens from synonym are present in meeting words
        intersection = synonym_tokens & meeting_tokens
        if intersection:
            print(f"✅ MATCH FOUND! Intersection: {intersection}")
            print(f"{'='*80}")
            return True
        else:
            print(f"❌ No match")
    
    print(f"🚫 NO OVERALL MATCH")
    print(f"{'='*80}")
    return False

if __name__ == "__main__":
    print("🧪 DEAL-MEETING MATCHING TEST SCRIPT")
    print("This script tests the matching logic from gong_service.get_call_id()")
    print("Enter your own deal names and meeting titles to test")
    print("(Press Ctrl+C to exit)")
    print()
    
    try:
        while True:
            deal_input = input("Enter deal name (or 'quit' to exit): ").strip()
            if deal_input.lower() in ['quit', 'exit', 'q']:
                break
                
            meeting_input = input("Enter meeting title: ").strip()
            if meeting_input.lower() in ['quit', 'exit', 'q']:
                break
                
            test_matching(deal_input, meeting_input)
            print()
            
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
