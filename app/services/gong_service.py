import sys
import os
from pathlib import Path

# Add the project root directory to Python path
project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from colorama import Fore, Style, init
import requests
import json
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any
from app.services.llm_service import ask_openai, ask_anthropic

from app.core.config import settings
from app.utils.prompts import champion_prompt, parr_principle_prompt, buyer_intent_prompt, pricing_concerns_prompt, no_decision_maker_prompt, already_has_vendor_prompt
from app.utils.general_utils import extract_company_name

import uuid
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

init()

def parse_markdown_buyer_intent(markdown_text: str, intent: str = "Likely to buy") -> Dict:
    """
    Parse markdown-formatted buyer intent response into structured dictionary format.
    
    Args:
        markdown_text: The markdown-formatted text from LLM
        intent: The buyer intent classification
        
    Returns:
        Dict with structured format: {"intent": str, "summary": dict}
    """
    try:
        sections = {}
        current_section = None
        current_bullets = []
        
        # Handle both actual newlines and escaped \n characters
        if '\\n' in markdown_text:
            lines = markdown_text.replace('\\n', '\n').split('\n')
        else:
            lines = markdown_text.split('\n')
        
        print(f"DEBUG: Parsing markdown with {len(lines)} lines")
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            print(f"DEBUG: Processing line: '{line[:50]}...'") if len(line) > 50 else print(f"DEBUG: Processing line: '{line}'")
                
            # Check if this is a section header (starts with ##)
            if line.startswith('## '):
                # Save previous section if it exists
                if current_section and current_bullets:
                    print(f"DEBUG: Saving section '{current_section}' with {len(current_bullets)} bullets")
                    sections[current_section] = current_bullets
                
                # Start new section
                current_section = line[3:].strip()  # Remove "## "
                current_bullets = []
                print(f"DEBUG: Starting new section: '{current_section}'")
                
            # Check if this is a bullet point (starts with - or •)
            elif (line.startswith('- ') or line.startswith('• ')) and current_section:
                # Handle both - and • bullet points
                if line.startswith('• '):
                    bullet_text = line[2:].strip()  # Remove "• "
                else:
                    bullet_text = line[2:].strip()  # Remove "- "
                    
                if bullet_text:
                    current_bullets.append(bullet_text)
                    print(f"DEBUG: Added bullet to '{current_section}': '{bullet_text[:50]}...'") if len(bullet_text) > 50 else print(f"DEBUG: Added bullet to '{current_section}': '{bullet_text}'")
        
        # Don't forget the last section
        if current_section and current_bullets:
            print(f"DEBUG: Saving final section '{current_section}' with {len(current_bullets)} bullets")
            sections[current_section] = current_bullets
        elif current_section:
            print(f"DEBUG: Section '{current_section}' has no bullets, not saving")
            
        print(f"DEBUG: Final sections created: {list(sections.keys())}")
        print(f"DEBUG: Total sections: {len(sections)}")
        
        return {
            "intent": intent,
            "summary": sections
        }
        
    except Exception as e:
        print(f"Error parsing markdown buyer intent: {str(e)}")
        return {
            "intent": "Unable to determine",
            "summary": {"Parsing Error": [f"Could not parse markdown response: {str(e)}"]}
        }

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
        'schedule', 'scheduled', 'calendar', 'invite', 'invitation', 'join', 'connect',
        'gong', 'recording', 'transcript', 'session', 'webinar', 'presentation', 'bank',

        # generic AI/product words
        'ai', 'al', 'land', 'platform', 'monitor', 'observe', 'genai', 'gen', 'generative',
        'evaluate', 'protect', 'users', 'team', 'enterprise', 'cloud', 'digital', 'innovation', 'developer',

        # very common business suffixes
        'group', 'company', 'inc', 'inc.', 'llc', 'corp', 'corporation', 'co', 'co.', 
        'plc', 'limited', 'ltd', 'pty', 'se', 'ag',

        # industry generic
        'automation', 'business', 'global', 'international', 'technologies', 'technology',
        'systems', 'solutions', 'services', 'network', 'networks', 'financial', 'capital',
        'federal', 'holdings', 'associates', 'industries', 'partners', 'consulting',
        'digital', 'analytics', 'data',

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

@dataclass
class Speaker:
    """Represents a speaker in a call with their details and transcript."""
    speaker_id: str
    speaker_name: str
    email: str
    affiliation: str  # Internal or External
    full_transcript: str = ""

    def to_dict(self) -> Dict:
        """Convert the speaker object to a dictionary format."""
        return {
            "speakerId": self.speaker_id,
            "speakerName": self.speaker_name,
            "email": self.email,
            "affiliation": self.affiliation,
            "full_transcript": self.full_transcript
        }

class GongService:
    def __init__(self):
        self.access_key = settings.GONG_ACCESS_KEY
        self.client_secret = settings.GONG_CLIENT_SECRET
        self.reschedule_window = 1


    def list_calls(self, call_date) -> List[Dict]:
        url = "https://us-5738.api.gong.io/v2/calls"

        # Format date strings for API
        from_datetime = f"{call_date}T00:00:00Z"
        to_datetime = f"{call_date}T23:59:59Z"

        params = {
            "fromDateTime": from_datetime,
            "toDateTime": to_datetime
        }
        
        response = requests.get(url, auth=(self.access_key, self.client_secret), params=params)
        if response.ok:
            calls = response.json().get("calls", [])
            
            # Get detailed information for each call including attendees
            for call in calls:
                call_id = call.get("id")
                if call_id:
                    # Get extensive call data
                    extensive_url = "https://us-5738.api.gong.io/v2/calls/extensive"
                    headers = {'Content-Type': 'application/json'}
                    extensive_payload = {
                        "filter": {
                            "callIds": [str(call_id)]
                        },
                        "contentSelector": {
                            "exposedFields": {
                                "parties": True,
                                "interaction": {
                                    "speakers": True
                                }
                            }
                        }
                    }
                    
                    extensive_response = requests.post(
                        extensive_url,
                        auth=(self.access_key, self.client_secret),
                        headers=headers,
                        json=extensive_payload
                    )
                    
                    if extensive_response.ok:
                        call_data = extensive_response.json()
                        calls_data = call_data.get("calls", [])
                        if calls_data:
                            # Add attendee information to the call object
                            call["attendees"] = []
                            for party in calls_data[0].get("parties", []):
                                attendee = {
                                    "name": party.get("name", "N/A"),
                                    "email": party.get("emailAddress", "N/A"),
                                    "affiliation": party.get("affiliation", "N/A")
                                }
                                call["attendees"].append(attendee)
            
            return calls
        else:
            return []

    def get_call_id(self, calls_from_gong, company_name, call_title=None) -> str | None:
        """Return the ID of a matching call based on company_name or call_title."""
        prefixes = ["[Gong] Google Meet:", "[Gong] Zoom:", "[Gong] WebEx:", "[Gong]"]
        
        if call_title:
            for prefix in prefixes:
                if call_title.startswith(prefix):
                    call_title = call_title[len(prefix):].strip()
                    break

            for gong_call in calls_from_gong:
                gong_call_title = gong_call.get("title", "").lower()
                for prefix in prefixes:
                    if gong_call_title.startswith(prefix.lower()):
                        gong_call_title = gong_call_title[len(prefix):].strip()
                        break
                if gong_call_title == call_title.lower():
                    return str(gong_call["id"])
        
        company_synonyms = company_name.split(",")

        print(f"Company synonyms: {company_synonyms}")

        for gong_call in calls_from_gong:
            
            title = gong_call.get("title", "")
            # Filter out filler words from title
            title_words = filter_filler_words(title)
            print(f"-- Matching call title words: {title_words} with company synonyms: {company_synonyms}")
            
            for synonym in company_synonyms:
                synonym = synonym.strip()
                # Filter out filler words from synonym
                synonym_tokens = filter_filler_words(synonym)

                # Check if any meaningful tokens from synonym are present in title words
                if synonym_tokens & title_words:
                    return str(gong_call["id"])
        
        return None

    def get_call_transcripts(self, call_ids, from_date, to_date) -> Dict[str, Any] | None:
        url = 'https://us-5738.api.gong.io/v2/calls/transcript'
        headers = {'Content-Type': 'application/json'}
        payload = {
            "filter": {
                "fromDateTime": from_date,
                "toDateTime": to_date,
                "callIds": [str(cid) for cid in call_ids]
            }
        }

        response = requests.post(url, auth=(self.access_key, self.client_secret), headers=headers, json=payload)

        if response.ok:
            return response.json()
        else:
            return None

    def get_concerns(self, call_title: str, call_date: str) -> Dict[str, Any]:
        """Analyze call transcripts for potential concerns using multiple prompts."""

        # Extract company name from call title
        company_name = extract_company_name(call_title)
        if company_name == "Unknown Company" or company_name == "Galileo":
            return {
                "pricing_concerns": {"has_concerns": False, "explanation": "Could not identify company"},
                "no_decision_maker": {"is_issue": False, "explanation": "Could not identify company"},
                "already_has_vendor": {"has_vendor": False, "explanation": "Could not identify company"}
            }

        try:
            if isinstance(call_date, str):
                target_date = datetime.strptime(call_date, "%Y-%m-%d")
            else:
                target_date = call_date
            
            start_date = target_date
            end_date = target_date + timedelta(days=self.reschedule_window)

            all_results = []
            current_date = start_date
            
            while current_date <= end_date:
                date_str = current_date.strftime("%Y-%m-%d")
                
                calls = self.list_calls(date_str)
                call_id = self.get_call_id(calls, company_name, call_title=call_title)
                
                if call_id:
                    start_time = f"{date_str}T00:00:00Z"
                    end_time = f"{date_str}T23:59:59Z"
                    transcripts_data = self.get_call_transcripts([call_id], start_time, end_time)

                    if transcripts_data and "callTranscripts" in transcripts_data:
                        combined_transcript = ""
                        for transcript in transcripts_data["callTranscripts"]:
                            for part in transcript.get("transcript", []):
                                speaker_id = part.get("speakerId", "unknown")
                                # Skip Galileo speakers
                                if "galileo.ai" in speaker_id.lower():
                                    continue
                                
                                if "sentences" in part:
                                    for sentence in part["sentences"]:
                                        combined_transcript += sentence.get("text", "") + " "

                        if combined_transcript.strip():
                            pricing_response = ask_openai(
                                user_content=pricing_concerns_prompt.format(transcript=combined_transcript)
                            )

                            pr_json = json.loads(pricing_response)

                            decision_maker_response = ask_openai(
                                user_content=no_decision_maker_prompt.format(transcript=combined_transcript)
                            )

                            dm_json = json.loads(decision_maker_response)

                            vendor_response = ask_openai(
                                user_content=already_has_vendor_prompt.format(transcript=combined_transcript)
                            )

                            vr_json = json.loads(vendor_response)

                            all_results.append({
                                "date": date_str,
                                "result": {
                                    "pricing_concerns": {
                                        "has_concerns": pr_json.get("pricing_concerns", False),
                                        "explanation": pr_json.get("explanation", "-- Not computed --")
                                    },
                                    "no_decision_maker": {
                                        "is_issue": dm_json.get("no_decision_maker", False),
                                        "explanation": dm_json.get("explanation", "-- Not computed --")
                                    },
                                    "already_has_vendor": {
                                        "has_vendor": vr_json.get("already_has_vendor", False),
                                        "explanation": vr_json.get("explanation", "-- Not computed --")
                                    }
                                }
                            })
            
                current_date += timedelta(days=1)

            if not all_results:
                return {
                    "pricing_concerns": {"has_concerns": False, "explanation": "No calls found"},
                    "no_decision_maker": {"is_issue": False, "explanation": "No calls found"},
                    "already_has_vendor": {"has_vendor": False, "explanation": "No calls found"}
                }

            # Return the most recent result if multiple calls found
            latest_result = all_results[-1]["result"]
            return latest_result

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {
                "pricing_concerns": {"has_concerns": False, "explanation": f"Error: {str(e)}"},
                "no_decision_maker": {"is_issue": False, "explanation": f"Error: {str(e)}"},
                "already_has_vendor": {"has_vendor": False, "explanation": f"Error: {str(e)}"}
            }

    def get_buyer_intent_json(self, call_transcript, seller_name) -> Dict:
        try:
            print("Getting buyer intent.")
            print("🔍 CALLING LLM for buyer intent analysis...")
            response = ask_anthropic(
                user_content=buyer_intent_prompt.format(
                    call_transcript=call_transcript, 
                    seller_name=seller_name
                ),
                system_content="You are a smart Sales Analyst that analyzes Sales calls."
            )
            print(f"Received response from LLM: {response[:100]}...")
            
            # First, try to parse as JSON (in case LLM returns proper JSON)
            try:
                intent_json = json.loads(response)
                print("Successfully parsed as JSON")
                
                # Check if the summary is a string that needs to be parsed as markdown
                if isinstance(intent_json.get("summary"), str) and intent_json["summary"].startswith("##"):
                    print("JSON summary is markdown string, parsing it into structured format...")
                    structured_summary = parse_markdown_buyer_intent(intent_json["summary"], intent_json.get("intent", "Likely to buy"))
                    intent_json["summary"] = structured_summary["summary"]
                    print(f"Converted markdown summary to structured format with {len(intent_json['summary'])} sections")
                    
            except json.JSONDecodeError:
                print("Response is not JSON, attempting to parse as markdown...")
                
                # Try to extract intent from the response
                intent = "Likely to buy"  # Default intent
                
                # Look for intent indicators in the response
                response_lower = response.lower()
                if "less likely to buy" in response_lower or "unlikely to buy" in response_lower:
                    intent = "Less likely to buy"
                elif "neutral" in response_lower:
                    intent = "Neutral"
                elif "likely to buy" in response_lower:
                    intent = "Likely to buy"
                
                # Parse the markdown response into structured format
                intent_json = parse_markdown_buyer_intent(response, intent)
                print(f"Parsed markdown into structured format with {len(intent_json.get('summary', {}))} sections")
                    
            # Ensure the response has the expected fields
            if "intent" not in intent_json:
                intent_json["intent"] = "Unable to determine"
            if "summary" not in intent_json:
                intent_json["summary"] = "No explanation provided"
            # Debug: Print the structure if it's a dictionary
            if isinstance(intent_json.get("summary"), dict):
                print(f"✅ Successfully structured buyer intent with sections: {list(intent_json['summary'].keys())}")
            else:
                print(f"⚠️ WARNING: intent_json summary is type {type(intent_json.get('summary'))}, not dict!")
            
            print("🎯 Returning intent_json successfully!")
            return intent_json
        except Exception as e:
            return {
                "intent": "Error",
                "summary": f"Error analyzing transcript: {str(e)}"
            }


    def get_transcript_and_topics(self, call_id, start_time, end_time) -> Tuple[str, List[str]]:
        """Get transcript and topics for a call"""
        full_transcript = ""
        topics = []
        call_transcripts = self.get_call_transcripts([call_id], start_time, end_time)

        if call_transcripts and "callTranscripts" in call_transcripts:
            for transcript in call_transcripts["callTranscripts"]:
                for tx in transcript["transcript"]:
                    if "topic" in tx:
                        topics.append(tx["topic"])
                    if "sentences" in tx:
                        for sentence in tx["sentences"]:
                            full_transcript += sentence["text"] + " "
        
        return full_transcript, topics

    def get_buyer_intent(self, call_title, call_date, seller_name):
        
        try:
            company_name = extract_company_name(call_title)
            if isinstance(call_date, datetime):
                call_date = call_date.strftime("%Y-%m-%d")
            
            # Default response if no call found
            default_response = {
                "intent": "Not available",
                "summary": f"No call found on {call_date}"
            }

            calls_from_gong = self.list_calls(call_date)
            call_id = self.get_call_id(calls_from_gong, company_name, call_title)

            if not call_id:
                # Try the next day
                try:
                    call_date = datetime.strptime(call_date, "%Y-%m-%d") + timedelta(days=1)
                    call_date = call_date.strftime("%Y-%m-%d")
                    
                    calls_from_gong = self.list_calls(call_date) # call again, for the next day

                    if not calls_from_gong or len(calls_from_gong) == 0:
                        return default_response
                        
                    call_id = self.get_call_id(calls_from_gong, company_name, call_title)
                    if not call_id:
                        return default_response
                except Exception as e:
                    return default_response

            if call_id:
                start_time = f"{call_date}T00:00:00Z"
                end_time = f"{call_date}T23:59:59Z"
                full_transcript, topics = self.get_transcript_and_topics(call_id, start_time, end_time)

                if not full_transcript:
                    return {
                        "intent": "No Transcript",
                        "summary": f"Call found but transcript unavailable for '{call_title}' on {call_date}"
                    }

                # Get buyer intent analysis for the transcript
                buyer_intent = self.get_buyer_intent_json(full_transcript, seller_name)
                return buyer_intent
            
            return default_response
        except Exception as e:
            return {
                "intent": "Error",
                "summary": f"Error analyzing call: {str(e)}"
            }

    def get_speaker_data(self, company_name: str, start_date: datetime, end_date: datetime) -> Dict[str, Speaker]:
        """Populate speaker data from Gong API calls within the given date range."""
        speaker_data: Dict[str, Speaker] = {}

        # Iterate through each day in the range
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            
            # Get calls for this day
            url = "https://us-5738.api.gong.io/v2/calls"
            from_datetime = f"{date_str}T00:00:00Z"
            to_datetime = f"{date_str}T23:59:59Z"
            
            params = {
                "fromDateTime": from_datetime,
                "toDateTime": to_datetime
            }

            response = requests.get(
                url, 
                auth=(self.access_key, self.client_secret), 
                params=params
            )
            
            if not response.ok:
                current_date += timedelta(days=1)
                continue
                
            calls = response.json().get("calls", [])

            # Loop through all the calls and match the title
            matching_calls = []
            matches = 0
            for call in calls:
                title = call.get("title", "")

                # Filter out filler words from company name and title
                company_name_tokens = filter_filler_words(company_name)
                title_tokens = filter_filler_words(title)

                if company_name_tokens & title_tokens:
                    matching_calls.append(call)
                    matches += 1

            # sort the matching calls by date
            matching_calls.sort(key=lambda x: x.get("startTime", ""))

            # Process each matching call (latest 10 calls)
            for call in matching_calls[:10]:
                call_id = call.get("id")
                
                # Get extensive call data for speaker information
                extensive_url = "https://us-5738.api.gong.io/v2/calls/extensive"
                headers = {'Content-Type': 'application/json'}
                extensive_payload = {
                    "filter": {
                        "callIds": [str(call_id)]
                    },
                    "contentSelector": {
                        "exposedFields": {
                            "parties": True,
                            "interaction": {
                                "speakers": True
                            }
                        }
                    }
                }
                
                extensive_response = requests.post(
                    extensive_url,
                    auth=(self.access_key, self.client_secret),
                    headers=headers,
                    json=extensive_payload
                )
                
                if not extensive_response.ok:
                    continue
                
                speaker_info = {}
                extensive_data = extensive_response.json()
                calls_data = extensive_data.get("calls", [])
                
                for call_data in calls_data:
                    # Extract party information (speakers)
                    parties = call_data.get("parties", [])
                    
                    for party in parties:
                        speaker_id = party.get("speakerId")
                        if speaker_id:
                            speaker_info[speaker_id] = {
                                "name": party.get("name", "Unknown"),
                                "email": party.get("emailAddress", ""),
                                "affiliation": party.get("affiliation", "Unknown")
                            }
                
                # Get transcript for this call
                transcript_url = 'https://us-5738.api.gong.io/v2/calls/transcript'
                transcript_payload = {
                    "filter": {
                        "fromDateTime": from_datetime,
                        "toDateTime": to_datetime,
                        "callIds": [str(call_id)]
                    }
                }

                transcript_response = requests.post(
                    transcript_url, 
                    auth=(self.access_key, self.client_secret), 
                    headers=headers, 
                    json=transcript_payload
                )
                
                if not transcript_response.ok:
                    continue
                    
                transcript_data = transcript_response.json()
                
                # Process all transcripts
                if "callTranscripts" in transcript_data:
                    for transcript in transcript_data["callTranscripts"]:
                        for part in transcript.get("transcript", []):
                            speaker_id = part.get("speakerId", "unknown")
                            
                            # Get speaker details from our mapping
                            details = speaker_info.get(speaker_id, {})
                            speaker_name = details.get("name", "Unknown Speaker")
                            speaker_email = details.get("email", "")
                            speaker_affiliation = details.get("affiliation", "Unknown")
                            
                            # Create or update speaker object
                            if speaker_id not in speaker_data:
                                speaker_data[speaker_id] = Speaker(
                                    speaker_id=speaker_id,
                                    speaker_name=speaker_name,
                                    email=speaker_email,
                                    affiliation=speaker_affiliation
                                )
                            
                            # Extract and concatenate all sentences from this speaker
                            if "sentences" in part:
                                for sentence in part["sentences"]:
                                    speaker_data[speaker_id].full_transcript += sentence.get("text", "") + " "

            current_date += timedelta(days=1)
        
        return speaker_data

    def get_champions(self, call_title, target_date=None) -> List[Dict]:
        try:
            company_name = extract_company_name(call_title)

            if target_date is None:
                target_date = datetime.now()
            
            start_date = target_date
            end_date = target_date + timedelta(days=self.reschedule_window)

            # Get speaker data using the new method
            speaker_data = self.get_speaker_data(company_name, start_date, end_date)

            # Convert speaker objects to dictionaries for compatibility
            speaker_transcripts = [speaker.to_dict() for speaker in speaker_data.values()]

            if len(speaker_transcripts) == 0:
                return []

            llm_responses = []
            for speaker_transcript in speaker_transcripts[:8]:
                if "galileo" not in speaker_transcript["email"].lower():

                    transcript = speaker_transcript["full_transcript"]

                    try:
                        speaker_response = ask_openai(
                            user_content=champion_prompt.format(transcript=transcript),
                            system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                        ).replace('```json', '').replace('```', '').replace('\n', '').replace('True', 'true').replace('False', 'false').strip()
                        speaker_response = json.loads(speaker_response)
                        speaker_response["email"] = speaker_transcript["email"]
                        speaker_response["speakerName"] = speaker_transcript["speakerName"]

                        parr_response = ask_openai(
                            user_content=parr_principle_prompt.format(speaker_name=speaker_transcript["speakerName"], transcript=transcript),
                            system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                        ).replace('```json', '').replace('json', '').replace('```', '').replace('\n', '').replace('True', 'true').replace('False', 'false').strip()
                        parr_response = json.loads(parr_response)

                        speaker_response["parr_analysis"] = parr_response

                        llm_responses.append(speaker_response)
                    except json.JSONDecodeError as e:
                        continue

            return llm_responses
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return []

    def get_additional_meetings(self, company_name: str, timeline_events: List[Dict], date_str: str) -> List[Dict]:
        try:
            print(f"Getting additional meetings for company {company_name} on date {date_str}.")
            existing_subjects = {event.get("subject", "").lower() for event in timeline_events}
            
            added_subjects = set()
            additional_meetings = []
            
            # Get calls for this date
            calls = self.list_calls(date_str)
            
            for call in calls:
                call_title = call.get("title", "").lower()
                print(f"Call title from Gong: {call_title} on date {date_str}")
                
                # Skip if call title is empty
                if not call_title:
                    continue
                    
                # Use the same matching logic as get_call_id
                company_name_synonyms = company_name.split(",")
                
                # Check if any company name token matches any title word
                is_match = False
                title_words = filter_filler_words(call_title)
                for company_synonym in company_name_synonyms:
                    synonym_tokens = filter_filler_words(company_synonym.strip())
                    if synonym_tokens & title_words:
                        is_match = True
                        break

                if not is_match:
                    continue
                    
                # Skip if this meeting already exists in timeline events or has been added
                if call_title.strip().lower() in {s.strip().lower() for s in existing_subjects} or call_title.strip().lower() in {s.strip().lower() for s in added_subjects}:
                    print("Skipping duplicate call title: ", call_title)
                    continue
                
                # Get call ID and transcript
                call_id = call.get("id")
                if not call_id:
                    continue
                    
                start_time = f"{date_str}T00:00:00Z"
                end_time = f"{date_str}T23:59:59Z"
                
                # Get transcript
                transcript_data = self.get_call_transcripts([call_id], start_time, end_time)
                if not transcript_data or "callTranscripts" not in transcript_data:
                    continue
                    
                # Combine all non-Galileo transcripts
                transcript = ""
                for call_transcript in transcript_data["callTranscripts"]:
                    for part in call_transcript.get("transcript", []):
                        speaker_id = part.get("speakerId", "unknown")
                        # Skip Galileo speakers
                        if "galileo.ai" in speaker_id.lower():
                            continue
                        
                        if "sentences" in part:
                            for sentence in part["sentences"]:
                                transcript += sentence.get("text", "") + " "
                
                if not transcript.strip():
                    continue
                
                # Get buyer intent
                buyer_intent = self.get_buyer_intent(
                    call_title=call.get("title", ""),
                    call_date=date_str,
                    seller_name="Galileo"
                )
                
                # Get sentiment
                sentiment = "-- Not computed --"
                if transcript:
                    # Truncate content to a reasonable length before analysis
                    max_content_length = 10000  # Roughly 2500 tokens
                    if len(transcript) > max_content_length:
                        transcript = transcript[:max_content_length] + "..."
                        
                    sentiment = ask_openai(
                        system_content="You are a smart Sales Operations Analyst that analyzes Sales emails.",
                        user_content=f"""
                        Classify the sentiment in this email as positive (likely to buy Galileo), negative (unlikely to buy Galileo), or neutral (no clear indication to buy Galileo):
                        {transcript}
                        Return only one word: positive, negative, neutral
                        """
                    )
                
                event = {
                    "id": f"gong_{uuid.uuid4()}",
                    "engagement_id": None,
                    "date_str": date_str,
                    "time_str": call.get("startTime", "").split("T")[1][:5] if "startTime" in call else "00:00",
                    "type": "Meeting",
                    "subject": call.get("title", ""),
                    "content": "",
                    "content_preview": "",
                    "sentiment": sentiment,
                    "buyer_intent": buyer_intent.get("intent"),
                    "buyer_intent_explanation": buyer_intent.get("summary")
                }
                
                # Add to our tracking set and list
                added_subjects.add(call_title)
                additional_meetings.append(event)
            
            return additional_meetings
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return []

    def get_meeting_insights(self, call_id: str) -> Dict:
        headers = {'Content-Type': 'application/json'}

        # Step 1: Get transcript
        transcript_url = 'https://us-5738.api.gong.io/v2/calls/transcript'
        transcript_payload = {"filter": {"callIds": [str(call_id)]}}
        transcript_response = requests.post(
            transcript_url,
            auth=(self.access_key, self.client_secret),
            headers=headers,
            json=transcript_payload
        )
        transcript_data = transcript_response.json()

        # Step 2: Extract speakerIds and full transcript
        speaker_ids = set()
        buyer_transcripts = ""
        for transcript in transcript_data.get("callTranscripts", []):
            for part in transcript.get("transcript", []):
                speaker_id = part.get("speakerId", "unknown")
                speaker_ids.add(speaker_id)
                for sentence in part.get("sentences", []):
                    buyer_transcripts += sentence.get("text", "") + " "

        print(f"{len(speaker_ids)} speakers detected on the buyer side.")
        
        # Step 3: Get speaker info using /v2/calls/extensive
        extensive_url = "https://us-5738.api.gong.io/v2/calls/extensive"
        extensive_payload = {
            "filter": {"callIds": [str(call_id)]},
            "contentSelector": {
                "exposedFields": {
                    "parties": True,
                    "interaction": {"speakers": True}
                }
            }
        }

        extensive_response = requests.post(
            extensive_url,
            auth=(self.access_key, self.client_secret),
            headers=headers,
            json=extensive_payload
        )

        buyer_attendees = []
        if extensive_response.ok:
            calls_data = extensive_response.json().get("calls", [])
            for call_data in calls_data:
                for party in call_data.get("parties", []):
                    print(f"Party: {party}")
                    email_address = party.get("emailAddress", "")
                    name = party.get("name", "Unknown name")
                    title = party.get("title", "Unknown title")
                    affiliation = party.get("affiliation", "Unknown affiliation")

                    if affiliation != "Internal":
                        if email_address and "galileo.ai" not in email_address.lower():
                            buyer_attendees.append({
                                "name": name,
                                "email": email_address,
                                "title": title
                            })
                        elif name:
                            buyer_attendees.append({
                                "name": name,
                                "title": title
                            })

        print(Fore.BLUE + f"Buyer attendees: {buyer_attendees}" + Style.RESET_ALL)

        # Step 5: Run intent detection
        buyer_intent = self.get_buyer_intent_json(
            buyer_transcripts,
            "Galileo",
        )

        champions = [{
            "email": "Not computed",
            "speakerName": "Not computed",
            "champion": False,
            "explanation": "Not computed",
            "parr_analysis": {
                "power": False,
                "authority": False,
                "resources": False,
                "relevance": False,
                "explanation": "Not computed"
            }
        }]

        call_url = f'https://us-5738.api.gong.io/v2/calls/{call_id}'
        call_response = requests.get(call_url, auth=(self.access_key, self.client_secret))
        call = call_response.json().get("call", {})

        insights = {
            "meeting_id": call_id,
            "meeting_title": call.get("title", ""),
            "meeting_date": call.get("scheduled", "").split("T")[0] if "scheduled" in call else "",
            "buyer_intent": buyer_intent,
            "champion_analysis": champions,
            "topics": "",
            "transcript": buyer_transcripts.strip(),
            "buyer_attendees": buyer_attendees,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

        return insights
