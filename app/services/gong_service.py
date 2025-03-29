from colorama import Fore, Style, init
from app.core.config import settings
import requests
import json
from datetime import datetime, timedelta
from app.services.llm_service import ask_openai, ask_anthropic
from collections import OrderedDict
import time

init()

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
        self.reschedule_window = 10
        
        # Initialize the champion cache
        # Default: 100 entries with 7-day TTL
        cache_capacity = getattr(settings, 'GONG_CACHE_CAPACITY', 100)
        cache_ttl = getattr(settings, 'GONG_CACHE_TTL', 604800)  # 7 days in seconds
        self.champion_cache = LRUCache(capacity=cache_capacity, ttl=cache_ttl)

    def list_calls(self, call_date):
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
            print(Fore.RED + f"Error fetching calls: {response.status_code}, {response.text}" + Style.RESET_ALL)
            return []
            
    def find_call_by_title(self, calls, call_title):
        """Find a call by its title (case-insensitive)"""
        for call in calls:
            title = call.get("title", "").lower()
            if call_title.lower() in title or title in call_title.lower():
                return str(call["id"])
        return None

    def get_call_transcripts(self, call_ids, from_date, to_date):
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

    def get_buyer_intent_json(self, call_transcript, seller_name, call_date_str):
        prompt = f"""
            Analyze the buyer sentiment from this transcript. 
            Return the intent, and a one-line explanation in JSON. 
            Intent options: Less likely to buy, Neutral, Unsure, Likely to buy, Very likely to buy
            If there is any explicit frustration, hesitation, or uncertainty in buying - choose Less likely to buy.
            Choose 'Very likely to buy' only if there is strong interest from the buyer 
            i.e. they mention they love the product.
            Include (in the explanation) the challenges or problems the buyer is facing (if they explicitly mention them).
            The output should be JSON with 2 fields only: intent and explanation.
            Seller: {seller_name}
            Transcript: {call_transcript}
        """

        try:
            response = ask_anthropic(
                user_content=prompt,
                system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
            )
            
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
                        # If still failing, create a default response
                        intent_json = {
                            "intent": "Unable to determine",
                            "explanation": "Could not parse response"
                        }
                else:
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
                
            print(Fore.CYAN + f"Buyer Intent (based on call transcript) - call dated {call_date_str}: {intent_json['intent']}" + Style.RESET_ALL)
            return intent_json
        except Exception as e:
            print(Fore.RED + f"Error in get_buyer_intent_json: {str(e)}" + Style.RESET_ALL)
            return {
                "intent": "Error",
                "explanation": f"Error analyzing transcript: {str(e)}"
            }


    def get_transcript_and_topics(self, call_id, start_time, end_time):
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

    def get_buyer_intent_for_call(self, call_title, call_date_str, seller_name):
        try:
            if isinstance(call_date_str, datetime):
                call_date_str = call_date_str.strftime("%Y-%m-%d")
            
            # Default response if no call found
            default_response = {
                "intent": "Not available",
                "explanation": f"No call found on {call_date_str}"
            }

            # Try to find the call
            calls = self.list_calls(call_date_str)
            call_id = self.find_call_by_title(calls, call_title)

            if not call_id:
                # Try the next day
                try:
                    call_date = datetime.strptime(call_date_str, "%Y-%m-%d") + timedelta(days=1)
                    call_date_str = call_date.strftime("%Y-%m-%d")
                    print(f"Call not found. Checking {call_date_str}")
                    
                    calls = self.list_calls(call_date_str) # call again, for the next day
                    if not calls or len(calls) == 0:
                        print(f"No calls found on {call_date_str}.")
                        return default_response
                        
                    print(f"{len(calls)} calls found on {call_date_str}. Now searching for specific title.")
                    call_id = self.find_call_by_title(calls, call_title)
                    if not call_id:
                        print(f"Could not find a call with title '{call_title}' on {call_date_str} either!")
                        return default_response
                except Exception as e:
                    print(f"Error checking next day: {str(e)}")
                    return default_response

            if call_id:
                start_time = f"{call_date_str}T00:00:00Z"
                end_time = f"{call_date_str}T23:59:59Z"
                full_transcript, topics = self.get_transcript_and_topics(call_id, start_time, end_time)

                if not full_transcript:
                    print("No transcript found")
                    return {
                        "intent": "No Transcript",
                        "explanation": f"Call found but transcript unavailable for '{call_title}' on {call_date_str}"
                    }

                # Get buyer intent analysis for the transcript
                return self.get_buyer_intent_json(full_transcript, seller_name, call_date_str)
            
            return default_response
        except Exception as e:
            print(Fore.RED + f"Error in get_buyer_intent_for_call: {str(e)}" + Style.RESET_ALL)
            return {
                "intent": "Error",
                "explanation": f"Error analyzing call: {str(e)}"
            }

    def extract_company_name(self, call_title):
        """Extract company name from call title"""
        prompt = f"""
            Extract name of the company from this call title.
            Call title: {call_title}
            
            Rules:
            1. If the title contains " - New Deal", extract everything before it
            2. If the title contains " <> ", extract everything before it
            3. If the title contains " - ", extract everything before it
            4. Exclude suffixes like "inc", "llc", "holdings", "group", "corp", "company", "corporation" etc. from the company name
            5. For a healthcare company, exclude "health" or "healthcare" from the company name
            6. Remove any leading/trailing whitespace
            7. If you cannot find the company name, return "Unknown Company"
            
            Examples:
            - "Notable - New Deal" -> "Notable"
            - "Intro: Cascade <> Galileo" -> "Cascade"
            - "Company Name - Some Text" -> "Company Name"
            
            Only return the name of the company.
            Assume that Galileo is not a company name.
        """
        response = ask_anthropic(
            user_content=prompt,
            system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
        )
        return response.strip()

    def get_speaker_champion_results(self, call_title, target_date=None):
        try:
            company_name = self.extract_company_name(call_title)
            if company_name == "Unknown Company":
                return []

            # Check if we have cached results for this deal
            cache_key = company_name.lower()
            cached_result = self.champion_cache.get(cache_key)
            if cached_result:
                print(Fore.GREEN + f"Retrieved champion data for '{company_name}' from cache" + Style.RESET_ALL)
                return cached_result

            print(Fore.GREEN + f"Extracted company name: {company_name}" + Style.RESET_ALL)

            if target_date is None:
                target_date = datetime.now()
            
            # Calculate date range
            start_date = target_date
            end_date = target_date + timedelta(days=self.reschedule_window)
            
            print(Fore.CYAN + f"Searching for calls '{company_name}' around {target_date.strftime('%Y-%m-%d')} +/- {self.reschedule_window} days" + Style.RESET_ALL)
            
            # Dictionary to store transcripts by speaker
            speaker_data = {}
            
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
                for call in calls:
                    title = call.get("title", "").lower()
                    
                    if company_name.lower() in title:
                        matching_calls.append(call)
                        print(Fore.CYAN + f"[MATCH] {date_str}: Comparing '{company_name.lower()}' with '{title}'" + Style.RESET_ALL)

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
                                
                                # Create a unique key for this speaker
                                unique_key = f"{speaker_id}"
                                
                                # Initialize this speaker if not already in the dictionary
                                if unique_key not in speaker_data:
                                    speaker_data[unique_key] = {
                                        "speakerId": speaker_id,
                                        "speakerName": speaker_name,
                                        "email": speaker_email,
                                        "affiliation": speaker_affiliation,
                                        "full_transcript": ""
                                    }
                                
                                # Extract and concatenate all sentences from this speaker
                                if "sentences" in part:
                                    for sentence in part["sentences"]:
                                        speaker_data[unique_key]["full_transcript"] += sentence.get("text", "") + " "
                
                # Move to next day
                current_date += timedelta(days=1)
            
            # Format the results as an array
            result = list(speaker_data.values())
            print(Fore.GREEN + f"\nTotal speakers found: {len(result)} = [{', '.join([speaker['speakerName'] for speaker in result])}]" + Style.RESET_ALL)

            champion_prompt = """
                You are a smart Sales Operations Analyst that analyzes Sales calls.
                You are given a transcript of what a potential buyer of Galileo said.
                Your job is to identify the champion of the call.
                DEFINITION OF CHAMPION:
                A champion is defined as someone who really loves the product and shows strong intent towards using or buying it. In this case the product is Galileo. Only assign champion as True if someone has sung high praises of the product or has exclaimed a desire to use or buy Galileo.
                For the explanation, be specific to this peron's thoughts, comments or feelings (whether they are positive or negative).

                Analyze the transcript and strictly return a JSON with the following fields:
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

            # loop through result, for each speaker (only if they are external) print the full transcript
            llm_responses = []
            for speaker in result[:20]:
                if "galileo" not in speaker["email"].lower():
                    print(Fore.CYAN + f"Analyzing {speaker['email']}..." + Style.RESET_ALL)
                    transcript = speaker["full_transcript"]
                    llm_response = ask_anthropic(
                        user_content=champion_prompt.format(transcript=transcript),
                        system_content="You are a smart Sales Operations Analyst that analyzes Sales calls."
                    )
                    try:
                        # Clean up the response by removing markdown code blocks and newlines
                        cleaned_response = llm_response.replace('```json', '').replace('```', '').replace('\n', '').strip()
                        # Replace Python boolean values with JSON boolean values
                        cleaned_response = cleaned_response.replace('True', 'true').replace('False', 'false')
                        llm_response = json.loads(cleaned_response)
                        llm_response["email"] = speaker["email"]
                        llm_responses.append(llm_response)
                    except json.JSONDecodeError as e:
                        print(Fore.RED + f"Error parsing LLM response: {e}" + Style.RESET_ALL)
                        print(Fore.RED + f"Raw response: {llm_response}" + Style.RESET_ALL)
                        continue

            print(Fore.GREEN + f"\nFinal results: {len(llm_responses)} speakers analyzed" + Style.RESET_ALL)
            
            # Cache the results with the company name as the key
            self.champion_cache.put(cache_key, llm_responses)
            print(Fore.GREEN + f"Cached champion data for '{company_name}'" + Style.RESET_ALL)
            
            return llm_responses
            
        except Exception as e:
            print(Fore.RED + f"Error in get_speaker_transcripts: {str(e)}" + Style.RESET_ALL)
            import traceback
            traceback.print_exc()
            return []
            
    def clear_champion_cache(self):
        """Clears the champion cache"""
        self.champion_cache.clear()
        print(Fore.GREEN + "Champion cache cleared" + Style.RESET_ALL)
        
    def remove_from_champion_cache(self, deal_name):
        """Removes a specific deal from the champion cache"""
        key = self.extract_company_name(deal_name).lower()
        self.champion_cache.remove(key)
        print(Fore.GREEN + f"Removed '{key}' from champion cache" + Style.RESET_ALL)
        
    def get_cached_champion_deals(self):
        """Returns a list of deal names currently in the cache"""
        return self.champion_cache.keys()

# if __name__ == "__main__":
#     gong_service = GongService()
#     result = gong_service.get_speaker_transcripts("Intro: Cascade <> Galileo", 10)
#     print(Fore.YELLOW + "*"*100 + Style.RESET_ALL)
#     print(Fore.GREEN + f"Result: {result}" + Style.RESET_ALL)
#     print(Fore.YELLOW + "*"*100 + Style.RESET_ALL)