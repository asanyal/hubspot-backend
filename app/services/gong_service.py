from colorama import Fore, Style, init

import requests
import json
from datetime import datetime, timedelta, timezone
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.config import settings
from app.services.llm_service import ask_anthropic
from app.utils.prompts import champion_prompt, parr_principle_prompt, buyer_intent_prompt, pricing_concerns_prompt, no_decision_maker_prompt, already_has_vendor_prompt
from app.utils.general_utils import extract_company_name

import time

init()

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

class LRUCache:
    """
    LRU (Least Recently Used) cache implementation with time-based expiration.
    """
    def __init__(self, capacity=100, ttl=86400):  # Default TTL: 24 hours
        self.cache = OrderedDict()
        self.capacity = capacity
        self.ttl = ttl  # Time to live in seconds
        self.timestamps = {}  # To store when each item was added/updated
    
    def get(self, key):
        if key not in self.cache:
            return None
        
        # Check if the item has expired
        if time.time() - self.timestamps[key] > self.ttl:
            self.remove(key)
            return None
            
        # Move the item to the end (most recently used)
        self.cache.move_to_end(key)
        return self.cache[key]
    
    def put(self, key, value):
        # If key exists, update its value and move it to the end
        if key in self.cache:
            self.cache[key] = value
            self.cache.move_to_end(key)
        else:
            # If cache is full, remove the least recently used item
            if len(self.cache) >= self.capacity:
                self.cache.popitem(last=False)
                
            # Add the new item
            self.cache[key] = value
            
        # Update the timestamp
        self.timestamps[key] = time.time()
    
    def remove(self, key):
        if key in self.cache:
            del self.cache[key]
            del self.timestamps[key]
    
    def keys(self):
        return list(self.cache.keys())
    
    def clear(self):
        self.cache.clear()
        self.timestamps.clear()

class GongService:
    def __init__(self):
        self.access_key = settings.GONG_ACCESS_KEY
        self.client_secret = settings.GONG_CLIENT_SECRET
        self.reschedule_window = 1

        cache_capacity = getattr(settings, 'GONG_CACHE_CAPACITY', 100)
        cache_ttl = getattr(settings, 'GONG_CACHE_TTL', 604800)  # 7 days in seconds
        self.champion_cache = LRUCache(capacity=cache_capacity, ttl=cache_ttl)

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
            return calls
        else:
            return []

    def get_call_id(self, calls, company_name) -> str | None:
        """Find a call by matching any word in call_title against the call's title (case-insensitive)"""
        company_name_tokens = set(company_name.lower().split())
        print(Fore.RED + f"Company name tokens: {company_name_tokens}" + Style.RESET_ALL)

        for call in calls:
            title_tokens = set(call.get("title", "").lower().split())
            print(Fore.RED + f"Title tokens: {title_tokens}" + Style.RESET_ALL)
            if company_name_tokens & title_tokens:
                return str(call["id"])
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
            print(Fore.RED + f"Error fetching transcripts: {response.status_code}, {response.text}" + Style.RESET_ALL)
            return None

    def get_concerns(self, call_title: str, call_date: str) -> Dict[str, Any]:
        """Analyze call transcripts for potential concerns using multiple prompts."""
        print(Fore.MAGENTA + f"Analyzing potential concerns for call: {call_title} on {call_date}" + Style.RESET_ALL)

        # Extract company name from call title
        company_name = extract_company_name(call_title)
        if company_name == "Unknown Company" or company_name == "Galileo":
            print(Fore.RED + f"No company found from call title: {call_title}" + Style.RESET_ALL)
            return {
                "pricing_concerns": {"has_concerns": False, "explanation": "Could not identify company"},
                "no_decision_maker": {"is_issue": False, "explanation": "Could not identify company"},
                "already_has_vendor": {"has_vendor": False, "explanation": "Could not identify company"}
            }

        print(Fore.MAGENTA + f"Extracted company name: {company_name}" + Style.RESET_ALL)
        
        def parse_llm_response(response: str, default_key: str) -> Dict:
            """Helper function to parse LLM response and handle errors"""
            try:
                # Clean the response
                response = response.replace('```json', '').replace('```', '').replace('\n', '').strip()
                
                # Try to parse as JSON
                try:
                    return json.loads(response)
                except json.JSONDecodeError:
                    # If the response isn't valid JSON, try to extract JSON from text
                    import re
                    json_match = re.search(r'(\{.*\})', response, re.DOTALL)
                    if json_match:
                        try:
                            return json.loads(json_match.group(1))
                        except:
                            print(Fore.RED + f"Error parsing JSON: {response}" + Style.RESET_ALL)
                            return {default_key: False, "explanation": "Could not parse response"}
                    else:
                        print(Fore.RED + f"Error parsing JSON: {response}" + Style.RESET_ALL)
                        return {default_key: False, "explanation": "Could not parse response"}
            except Exception as e:
                print(Fore.RED + f"Error processing response: {str(e)}" + Style.RESET_ALL)
                return {default_key: False, "explanation": f"Error: {str(e)}"}
        
        try:
            # Convert string date to datetime if needed
            if isinstance(call_date, str):
                target_date = datetime.strptime(call_date, "%Y-%m-%d")
            else:
                target_date = call_date

            # Calculate date range
            start_date = target_date
            end_date = target_date + timedelta(days=self.reschedule_window)

            print(Fore.MAGENTA + f"Searching for calls from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}" + Style.RESET_ALL)
            
            # Track all results
            all_results = []
            current_date = start_date
            
            while current_date <= end_date:
                date_str = current_date.strftime("%Y-%m-%d")
                print(Fore.MAGENTA + f"\nChecking date: {date_str}" + Style.RESET_ALL)
                
                # Get calls for this date
                calls = self.list_calls(date_str)
                call_id = self.get_call_id(calls, company_name)  # Use company_name instead of call_title
                
                if call_id:
                    print(Fore.GREEN + f"Found call on {date_str}" + Style.RESET_ALL)
                    
                    # Get transcripts
                    start_time = f"{date_str}T00:00:00Z"
                    end_time = f"{date_str}T23:59:59Z"
                    transcripts_data = self.get_call_transcripts([call_id], start_time, end_time)

                    if transcripts_data and "callTranscripts" in transcripts_data:
                        # Combine all non-Galileo transcripts
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
                            # Analyze with each prompt
                            print(Fore.MAGENTA + "Analyzing pricing concerns..." + Style.RESET_ALL)
                            pricing_response = ask_anthropic(
                                user_content=pricing_concerns_prompt.format(transcript=combined_transcript),
                                system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                            )
                            pricing_analysis = parse_llm_response(pricing_response, "pricing_concerns")

                            print(Fore.MAGENTA + "Analyzing decision maker presence..." + Style.RESET_ALL)
                            decision_maker_response = ask_anthropic(
                                user_content=no_decision_maker_prompt.format(transcript=combined_transcript),
                                system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                            )
                            decision_maker_analysis = parse_llm_response(decision_maker_response, "no_decision_maker")

                            print(Fore.MAGENTA + "Analyzing existing vendor status..." + Style.RESET_ALL)
                            vendor_response = ask_anthropic(
                                user_content=already_has_vendor_prompt.format(transcript=combined_transcript),
                                system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                            )
                            vendor_analysis = parse_llm_response(vendor_response, "already_has_vendor")

                            # Add results for this call
                            all_results.append({
                                "date": date_str,
                                "result": {
                                    "pricing_concerns": {
                                        "has_concerns": pricing_analysis.get("pricing_concerns", False),
                                        "explanation": pricing_analysis.get("explanation", "No explanation provided")
                                    },
                                    "no_decision_maker": {
                                        "is_issue": decision_maker_analysis.get("no_decision_maker", False),
                                        "explanation": decision_maker_analysis.get("explanation", "No explanation provided")
                                    },
                                    "already_has_vendor": {
                                        "has_vendor": vendor_analysis.get("already_has_vendor", False),
                                        "explanation": vendor_analysis.get("explanation", "No explanation provided")
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
            print(Fore.MAGENTA + f"Analysis complete. Found {len(all_results)} calls. Returning most recent result." + Style.RESET_ALL)
            return latest_result

        except Exception as e:
            print(Fore.RED + f"Error in get_potential_concerns: {str(e)}" + Style.RESET_ALL)
            import traceback
            traceback.print_exc()
            return {
                "pricing_concerns": {"has_concerns": False, "explanation": f"Error: {str(e)}"},
                "no_decision_maker": {"is_issue": False, "explanation": f"Error: {str(e)}"},
                "already_has_vendor": {"has_vendor": False, "explanation": f"Error: {str(e)}"}
            }

    def get_buyer_intent_json(self, call_transcript, seller_name, call_date_str) -> Dict:
        try:
            response = ask_anthropic(
                user_content=buyer_intent_prompt.format(call_transcript=call_transcript, seller_name=seller_name),
                system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
            )
            
            # Clean the response by replacing newlines with spaces
            response = response.replace('\n', ' ')
            
            # Try to parse as JSON
            try:
                intent_json = json.loads(response)
            except json.JSONDecodeError:
                # If the response isn't valid JSON, try to extract JSON from text
                # Sometimes the LLM might include explanation text outside the JSON
                import re
                json_match = re.search(r'(\{.*\})', response, re.DOTALL)
                if json_match:
                    try:
                        intent_json = json.loads(json_match.group(1))
                    except:
                        print(Fore.RED + f"Error parsing JSON: {response}" + Style.RESET_ALL)
                        # If still failing, create a default response
                        intent_json = {
                            "intent": "Unable to determine",
                            "explanation": "Could not parse response"
                        }
                else:
                    print(Fore.RED + f"Error parsing JSON: {response}" + Style.RESET_ALL)
                    # Create default response
                    intent_json = {
                        "intent": "Unable to determine",
                        "explanation": "Could not parse response"
                    }
                    
            # Ensure the response has the expected fields
            if "intent" not in intent_json:
                intent_json["intent"] = "Unable to determine"
            if "explanation" not in intent_json:
                intent_json["explanation"] = "No explanation provided"
                
            print(Fore.MAGENTA + f"Buyer Intent (based on call transcript) - call dated {call_date_str}: {intent_json['intent']}" + Style.RESET_ALL)
            return intent_json
        except Exception as e:
            print(Fore.RED + f"Error in get_buyer_intent_json: {str(e)}" + Style.RESET_ALL)
            return {
                "intent": "Error",
                "explanation": f"Error analyzing transcript: {str(e)}"
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
                "explanation": f"No call found on {call_date}"
            }

            calls = self.list_calls(call_date)
            call_id = self.get_call_id(calls, company_name)

            if not call_id:
                # Try the next day
                try:
                    call_date = datetime.strptime(call_date, "%Y-%m-%d") + timedelta(days=1)
                    call_date = call_date.strftime("%Y-%m-%d")
                    
                    calls = self.list_calls(call_date) # call again, for the next day

                    if not calls or len(calls) == 0:
                        return default_response
                        
                    call_id = self.get_call_id(calls, company_name)
                    if not call_id:
                        return default_response
                except Exception as e:
                    print(Fore.RED + f"Error checking next day: {str(e)}" + Style.RESET_ALL)
                    return default_response

            if call_id:
                start_time = f"{call_date}T00:00:00Z"
                end_time = f"{call_date}T23:59:59Z"
                full_transcript, topics = self.get_transcript_and_topics(call_id, start_time, end_time)

                if not full_transcript:
                    print(Fore.RED + "No transcript found" + Style.RESET_ALL)
                    return {
                        "intent": "No Transcript",
                        "explanation": f"Call found but transcript unavailable for '{call_title}' on {call_date}"
                    }

                # Get buyer intent analysis for the transcript
                return self.get_buyer_intent_json(full_transcript, seller_name, call_date)
            
            return default_response
        except Exception as e:
            print(Fore.RED + f"Error in get_buyer_intent_for_call: {str(e)}" + Style.RESET_ALL)
            return {
                "intent": "Error",
                "explanation": f"Error analyzing call: {str(e)}"
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
                print(Fore.RED + f"Error fetching calls: {response.status_code}" + Style.RESET_ALL)
                current_date += timedelta(days=1)
                continue
                
            calls = response.json().get("calls", [])

            # Loop through all the calls and match the title
            matching_calls = []
            matches = 0
            for call in calls:
                title = call.get("title", "").lower()

                company_name_tokens = company_name.lower().split(" ")
                title_tokens = title.lower().split(" ")

                if any(token in title_tokens for token in company_name_tokens):
                    matching_calls.append(call)
                    matches += 1
                    print(Fore.MAGENTA + f"[MATCH] {date_str}: Comparing '{company_name.lower()}' with '{title}'" + Style.RESET_ALL)

            print(Fore.MAGENTA + f"{matches} matching calls found on {date_str}" + Style.RESET_ALL)
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
                    print(Fore.RED + f"Error fetching extensive data: {extensive_response.status_code}" + Style.RESET_ALL)
                    print(Fore.RED + f"Response body: {extensive_response.text}" + Style.RESET_ALL)
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
                    print(Fore.RED + f"Error fetching transcript: {transcript_response.status_code}" + Style.RESET_ALL)
                    print(Fore.RED + f"Response body: {transcript_response.text}" + Style.RESET_ALL)
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
            if company_name == "Unknown Company":
                return []

            # Check if we have cached results for this deal
            cache_key = f"{company_name.lower()}_{target_date.strftime('%Y-%m-%d')}"
            print(Fore.MAGENTA + f"Extracted company name: {company_name}" + Style.RESET_ALL)

            if target_date is None:
                target_date = datetime.now()
            
            # Calculate date range
            start_date = target_date
            end_date = target_date + timedelta(days=self.reschedule_window)

            print(Fore.MAGENTA + f"Champion Extraction: Searching for calls '{company_name}' around {target_date.strftime('%Y-%m-%d')} + {self.reschedule_window} days" + Style.RESET_ALL)
            
            # Get speaker data using the new method
            speaker_data = self.get_speaker_data(company_name, start_date, end_date)
            print(Fore.MAGENTA + f"Champion Extraction: {len(speaker_data)} speaker data retrieved." + Style.RESET_ALL)

            # Convert speaker objects to dictionaries for compatibility
            speaker_transcripts = [speaker.to_dict() for speaker in speaker_data.values()]

            print(Fore.MAGENTA + f"\nChampion Extraction: Total speakers found: {len(speaker_transcripts)} = [{', '.join([speaker['speakerName'] for speaker in speaker_transcripts])}]" + Style.RESET_ALL)
            if len(speaker_transcripts) == 0:
                print(Fore.MAGENTA + "Champion Extraction: No speakers found, returning empty response" + Style.RESET_ALL)
                return []

            llm_responses = []
            print(Fore.MAGENTA + f"=== ANALYZING TOP 20 SPEAKERS ===" + Style.RESET_ALL)
            for speaker_transcript in speaker_transcripts[:20]:
                if "galileo" not in speaker_transcript["email"].lower():
                    print(Fore.MAGENTA + f"Champion Extraction: Analyzing {speaker_transcript['email']}..." + Style.RESET_ALL)

                    transcript = speaker_transcript["full_transcript"]

                    try:
                        speaker_response = ask_anthropic(
                            user_content=champion_prompt.format(transcript=transcript),
                            system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                        ).replace('```json', '').replace('```', '').replace('\n', '').replace('True', 'true').replace('False', 'false').strip()
                        speaker_response = json.loads(speaker_response)
                        speaker_response["email"] = speaker_transcript["email"]
                        speaker_response["speakerName"] = speaker_transcript["speakerName"]

                        parr_response = ask_anthropic(
                            user_content=parr_principle_prompt.format(speaker_name=speaker_transcript["speakerName"], transcript=transcript),
                            system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                        ).replace('```json', '').replace('json', '').replace('```', '').replace('\n', '').replace('True', 'true').replace('False', 'false').strip()
                        parr_response = json.loads(parr_response)

                        speaker_response["parr_analysis"] = parr_response

                        llm_responses.append(speaker_response)
                    except json.JSONDecodeError as e:
                        print(Fore.RED + f"Champion Extraction: Error parsing LLM response: {e}" + Style.RESET_ALL)
                        print(Fore.RED + f"Champion Extraction: Raw response: {speaker_response}" + Style.RESET_ALL)
                        continue

            print(Fore.MAGENTA + f"\nChampion Extraction: {len(llm_responses)} speakers analyzed" + Style.RESET_ALL)

            # Cache the results with the company name and date as the key
            self.champion_cache.put(cache_key, llm_responses)
            print(Fore.MAGENTA + f"Champion Extraction: Cached champion data" + Style.RESET_ALL)
            
            return llm_responses
            
        except Exception as e:
            print(Fore.RED + f"Champion Extraction: Error in get_speaker_transcripts: {str(e)}" + Style.RESET_ALL)
            import traceback
            traceback.print_exc()
            return []

    def clear_champion_cache(self) -> None:
        """Clears the champion cache"""
        self.champion_cache.clear()
        print(Fore.MAGENTA + "Champion cache cleared" + Style.RESET_ALL)
        
    def remove_from_champion_cache(self, deal_name) -> None:
        """Removes a specific deal from the champion cache"""
        key = extract_company_name(deal_name).lower()
        self.champion_cache.remove(key)
        print(Fore.MAGENTA + f"Removed '{key}' from champion cache" + Style.RESET_ALL)
        
    def get_cached_champion_deals(self) -> List[str]:
        """Returns a list of deal names currently in the cache"""
        return self.champion_cache.keys()

    def get_meeting_insights(self, meeting_id: str) -> Dict:
        """
        Get meeting insights from Gong API for a specific meeting.
        This method always makes a fresh API call to ensure we get the latest data.
        
        Args:
            meeting_id: The Gong meeting ID
            
        Returns:
            Dict containing meeting insights including buyer intent and champion analysis
        """
        try:
            print(Fore.BLUE + f"\n=== Fetching Fresh Meeting Insights from Gong API ===" + Style.RESET_ALL)
            print(Fore.BLUE + f"Meeting ID: {meeting_id}" + Style.RESET_ALL)
            
            # Get meeting data from Gong API
            url = f"https://us-5738.api.gong.io/v2/calls/extensive"
            headers = {'Content-Type': 'application/json'}
            payload = {
                "filter": {
                    "callIds": [str(meeting_id)]
                },
                "contentSelector": {
                    "exposedFields": {
                        "parties": True,
                        "interaction": {
                            "transcript": True,
                            "topics": True
                        }
                    }
                }
            }
            
            print(Fore.BLUE + "Making API call to Gong..." + Style.RESET_ALL)
            response = requests.post(
                url,
                auth=(self.access_key, self.client_secret),
                headers=headers,
                json=payload
            )
            
            if not response.ok:
                print(Fore.RED + f"Error fetching meeting data from Gong: {response.status_code}" + Style.RESET_ALL)
                print(Fore.RED + f"Response: {response.text}" + Style.RESET_ALL)
                return None
                
            meeting_data = response.json()
            calls = meeting_data.get("calls", [])
            
            if not calls:
                print(Fore.YELLOW + f"No meeting data found for ID: {meeting_id}" + Style.RESET_ALL)
                return None
                
            call = calls[0]  # Get the first (and should be only) call
            
            # Extract company name from call title
            company_name = extract_company_name(call.get("title", ""))
            print(Fore.MAGENTA + f"Extracted company name from call title: {company_name}" + Style.RESET_ALL)
            
            # Extract transcript and topics
            transcript = ""
            topics = []
            for part in call.get("interaction", {}).get("transcript", []):
                if "sentences" in part:
                    for sentence in part["sentences"]:
                        transcript += sentence.get("text", "") + " "
                if "topic" in part:
                    topics.append(part["topic"])
            
            # Get buyer intent analysis
            print(Fore.BLUE + "Analyzing buyer intent from transcript..." + Style.RESET_ALL)
            buyer_intent = self.get_buyer_intent_json(
                transcript,
                "Atin Sanyal",  # TODO: Get actual seller name
                call.get("startTime", "").split("T")[0]  # Extract date from startTime
            )
            
            # Get champion analysis
            print(Fore.BLUE + "Analyzing champions from transcript..." + Style.RESET_ALL)
            champions = self.get_champions(
                call.get("title", ""),
                datetime.strptime(call.get("startTime", "").split("T")[0], "%Y-%m-%d")
            )
            
            # Compile insights
            insights = {
                "meeting_id": meeting_id,
                "meeting_title": call.get("title", ""),
                "meeting_date": call.get("startTime", "").split("T")[0],
                "buyer_intent": buyer_intent,
                "champion_analysis": champions,
                "topics": topics,
                "transcript": transcript,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            print(Fore.GREEN + "Successfully fetched and analyzed meeting insights" + Style.RESET_ALL)
            return insights
            
        except Exception as e:
            print(Fore.RED + f"Error in get_meeting_insights: {str(e)}" + Style.RESET_ALL)
            import traceback
            traceback.print_exc()
            return None

if __name__ == "__main__":
    gong_service = GongService()
    
    date_str = "2025-04-17"
    call_title = "Pandadoc"
    
    print(Fore.YELLOW + "="*100 + Style.RESET_ALL)
    print(Fore.GREEN + f"Testing get_potential_concerns for {call_title}" + Style.RESET_ALL)
    print(Fore.YELLOW + "="*100 + Style.RESET_ALL)
    

    calls = gong_service.list_calls(date_str)
    call_id = gong_service.get_call_id(calls, call_title)
    print(Fore.GREEN + f"Found call ID: {call_id}" + Style.RESET_ALL)

    start_time = f"{date_str}T00:00:00Z"
    end_time = f"{date_str}T23:59:59Z"
    transcripts_data = gong_service.get_call_transcripts([call_id], start_time, end_time)
    print(Fore.GREEN + f"{transcripts_data}" + Style.RESET_ALL)
