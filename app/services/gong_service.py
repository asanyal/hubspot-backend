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
from app.services.llm_service import ask_openai

from app.core.config import settings
from app.utils.prompts import champion_prompt, parr_principle_prompt, buyer_intent_prompt, pricing_concerns_prompt, no_decision_maker_prompt, already_has_vendor_prompt
from app.utils.general_utils import extract_company_name

import uuid

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
        for gong_call in calls_from_gong:
            title_words = set(gong_call.get("title", "").split())
            for synonym in company_synonyms:
                if synonym in title_words:
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
            response = ask_openai(
                user_content=buyer_intent_prompt.format(call_transcript=call_transcript, seller_name=seller_name),
                system_content="You are a smart Sales Analyst that analyzes Sales calls."
            )
            
            # Clean the response by replacing newlines with spaces
            response = response.replace('\n', ' ')

            print(Fore.GREEN + f"Buyer intent response: {response}" + Style.RESET_ALL)
            
            # Try to parse as JSON
            try:
                intent_json = json.loads(response)
            except json.JSONDecodeError:
                print("Coupd not parse the buyer intent json into a JSON object")
                import re
                json_match = re.search(r'(\{.*\})', response, re.DOTALL)
                if json_match:
                    try:
                        intent_json = json.loads(json_match.group(1))
                    except:
                        intent_json = {
                            "intent": "Unable to determine",
                            "explanation": "Could not parse response"
                        }
                else:
                    intent_json = {
                        "intent": "Unable to determine",
                        "explanation": "Could not parse response"
                    }
                    
            # Ensure the response has the expected fields
            if "intent" not in intent_json:
                intent_json["intent"] = "Unable to determine"
            if "explanation" not in intent_json:
                intent_json["explanation"] = "No explanation provided"
            print("Returning intent_json successfully!")
            return intent_json
        except Exception as e:
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
                        "explanation": f"Call found but transcript unavailable for '{call_title}' on {call_date}"
                    }

                # Get buyer intent analysis for the transcript
                buyer_intent = self.get_buyer_intent_json(full_transcript, seller_name)
                print("In the function get_buyer_intent, output of get_buyer_intent_json: ", buyer_intent)
                return buyer_intent
            
            return default_response
        except Exception as e:
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
                company_name_synonyms = company_name.lower().split(",")
                
                # Check if any company name token is a substring of any title token
                is_match = False
                for company_synonym in company_name_synonyms:
                    if company_synonym.strip() in call_title.strip():
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
        transcript_url = 'https://us-5738.api.gong.io/v2/calls/transcript'
        transcript_payload = {
            "filter": {
                "callIds": [str(call_id)]
            }
        }

        transcript_response = requests.post(
            transcript_url, 
            auth=(self.access_key, self.client_secret), 
            headers=headers, 
            json=transcript_payload
        )
            
        transcript_data = transcript_response.json()

        call_url = f'https://us-5738.api.gong.io/v2/calls/{call_id}'
        call_response = requests.get(
            call_url,
            auth=(self.access_key, self.client_secret)
        )
        
        call = call_response.json().get("call", {})

        buyer_transcripts = ""

        if "callTranscripts" in transcript_data:
            for transcript in transcript_data["callTranscripts"]:
                for part in transcript.get("transcript", []):
                    speaker_id = part.get("speakerId", "unknown")
                    
                    # Extract and concatenate all sentences from this speaker
                    if "sentences" in part:
                        for sentence in part["sentences"]:
                            buyer_transcripts += sentence.get("text", "") + " "

        buyer_intent = self.get_buyer_intent_json(
            buyer_transcripts,
            "Galileo",
        )

        # TODO: Figure out a new way to get champions
        champions = [
            {
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
            }
        ]        

        # Compile insights
        insights = {
            "meeting_id": call_id,
            "meeting_title": call.get("title", ""),
            "meeting_date": call.get("scheduled", "").split("T")[0],
            "buyer_intent": buyer_intent,
            "champion_analysis": champions,
            "topics": "",
            "transcript": buyer_transcripts,
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

        return insights
            

if __name__ == "__main__":

    gong = GongService()
    
    test_cases = [
        {
            "company_name": extract_company_name("BrowserStack - New Deal"),
            "call_title": "",
            "date": "2025-04-23"
        }
    ]

    for test in test_cases:
        print(f"\nTesting with:")
        print(f"Company: {test['company_name']}")
        print(f"Call Title: {test['call_title']}")
        print(f"Date: {test['date']}")
        
        # Get calls for the date
        calls = gong.list_calls(test['date'])
        print(f"Found {len(calls)} calls for the date")

        for call in calls:
            print(f"Call: {call['title']}")
        
        call_id = gong.get_call_id(calls, test['company_name'], test['call_title'])

        print(f"Result: {'Found' if call_id else 'Not found'}")
        if call_id:
            print(f"Call ID: {call_id}")
