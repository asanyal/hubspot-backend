from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.repositories.deal_info_repository import DealInfoRepository
from app.repositories.deal_timeline_repository import DealTimelineRepository
from app.repositories.deal_insights_repository import DealInsightsRepository
from collections import defaultdict

router = APIRouter()


@router.get("/hello")
async def hello_world() -> Dict[str, Any]:
    """
    Hello world endpoint for stage-level insights
    """
    return {
        "message": "Hello from Stage Insights API!",
        "status": "success"
    }


@router.get("/topics")
async def get_topics_by_stage(
    stage: Optional[str] = Query(None, description="Filter by specific stage"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format")
) -> Dict[str, Any]:
    """
    Get topics (buyer_intent_explanation headers) aggregated by deal stage.

    Args:
        stage: Optional filter for a specific stage (e.g., "3. Technical Validation")
        start_date: Optional start date filter for events (YYYY-MM-DD)
        end_date: Optional end date filter for events (YYYY-MM-DD)

    Returns:
        Dictionary with stages as keys and list of unique topics as values
    """
    try:
        deal_info_repo = DealInfoRepository()
        deal_timeline_repo = DealTimelineRepository()

        # Parse dates if provided
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            # Set to end of day
            end_dt = end_dt.replace(hour=23, minute=59, second=59)

        # Get all deals
        all_deals = deal_info_repo.get_all_deals()

        # Dictionary to store topics by stage
        # Format: {stage: set of topics}
        topics_by_stage = defaultdict(set)

        # Process each deal
        for deal in all_deals:
            deal_id = deal.get("deal_id")
            deal_stage = deal.get("stage", "Unknown")

            # Filter by stage if provided
            if stage and deal_stage != stage:
                continue

            # Get timeline for this deal
            timeline = deal_timeline_repo.get_by_deal_id(deal_id)

            if not timeline or "events" not in timeline:
                continue

            # Process events
            for event in timeline.get("events", []):
                # Apply date filter if provided
                if start_dt or end_dt:
                    event_date = event.get("event_date")
                    if isinstance(event_date, str):
                        event_date = datetime.strptime(event_date, "%Y-%m-%dT%H:%M:%S")

                    if start_dt and event_date < start_dt:
                        continue
                    if end_dt and event_date > end_dt:
                        continue

                # Extract topics from buyer_intent_explanation
                buyer_intent_explanation = event.get("buyer_intent_explanation", {})

                # Handle both dict and string cases
                if isinstance(buyer_intent_explanation, dict):
                    # Get all the header/topic keys
                    for topic in buyer_intent_explanation.keys():
                        topics_by_stage[deal_stage].add(topic)

        # Convert sets to sorted lists for JSON serialization
        result = {
            stage: sorted(list(topics))
            for stage, topics in topics_by_stage.items()
        }

        return {
            "status": "success",
            "data": result,
            "filters": {
                "stage": stage,
                "start_date": start_date,
                "end_date": end_date
            }
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching topics: {str(e)}")


@router.get("/use-cases")
async def get_use_cases_by_stage(
    stage: Optional[str] = Query(None, description="Filter by specific stage"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format")
) -> Dict[str, Any]:
    """
    Get use cases (topics with "Use Case:" prefix) aggregated by deal stage.

    Args:
        stage: Optional filter for a specific stage (e.g., "3. Technical Validation")
        start_date: Optional start date filter for events (YYYY-MM-DD)
        end_date: Optional end date filter for events (YYYY-MM-DD)

    Returns:
        Dictionary with stages as keys and list of unique use cases as values
    """
    try:
        deal_info_repo = DealInfoRepository()
        deal_timeline_repo = DealTimelineRepository()

        # Parse dates if provided
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            # Set to end of day
            end_dt = end_dt.replace(hour=23, minute=59, second=59)

        # Get all deals
        all_deals = deal_info_repo.get_all_deals()

        # Dictionary to store use cases by stage
        # Format: {stage: list of {use_case, deal_name} objects}
        use_cases_by_stage = defaultdict(list)

        # Process each deal
        for deal in all_deals:
            deal_id = deal.get("deal_id")
            deal_stage = deal.get("stage", "Unknown")

            # Filter by stage if provided
            if stage and deal_stage != stage:
                continue

            # Get timeline for this deal
            timeline = deal_timeline_repo.get_by_deal_id(deal_id)

            if not timeline or "events" not in timeline:
                continue

            # Track use cases already added for this deal to avoid duplicates
            deal_use_cases_added = set()

            # Process events
            for event in timeline.get("events", []):
                # Apply date filter if provided
                if start_dt or end_dt:
                    event_date = event.get("event_date")
                    if isinstance(event_date, str):
                        event_date = datetime.strptime(event_date, "%Y-%m-%dT%H:%M:%S")

                    if start_dt and event_date < start_dt:
                        continue
                    if end_dt and event_date > end_dt:
                        continue

                # Extract topics from buyer_intent_explanation
                buyer_intent_explanation = event.get("buyer_intent_explanation", {})

                # Handle both dict and string cases
                if isinstance(buyer_intent_explanation, dict):
                    # Get only the topics that start with "Use Case:"
                    for topic in buyer_intent_explanation.keys():
                        if topic.startswith("Use Case:"):
                            # Remove the "Use Case:" prefix and strip whitespace
                            clean_use_case = topic.replace("Use Case:", "").strip()

                            # Only add if not already added for this deal
                            if clean_use_case not in deal_use_cases_added:
                                use_cases_by_stage[deal_stage].append({
                                    "use_case": clean_use_case,
                                    "deal_name": deal_id
                                })
                                deal_use_cases_added.add(clean_use_case)

        # Sort the lists by use_case name
        result = {
            stage: sorted(use_cases, key=lambda x: x["use_case"])
            for stage, use_cases in use_cases_by_stage.items()
        }

        return {
            "status": "success",
            "data": result,
            "filters": {
                "stage": stage,
                "start_date": start_date,
                "end_date": end_date
            }
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching use cases: {str(e)}")


@router.get("/risks")
async def get_risks_by_stage(
    stage: Optional[str] = Query(None, description="Filter by specific stage"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format")
) -> Dict[str, Any]:
    """
    Get all risks associated with deals, aggregated by stage.

    Risks include:
    - Pricing concerns (from deal_insights)
    - No decision maker (from deal_insights)
    - Existing vendor (from deal_insights)
    - Low buyer intent (from deal_timeline events)

    Args:
        stage: Optional filter for a specific stage (e.g., "3. Technical Validation")
        start_date: Optional start date filter for events (YYYY-MM-DD)
        end_date: Optional end date filter for events (YYYY-MM-DD)

    Returns:
        Dictionary with stages as keys and list of risk objects as values
    """
    try:
        deal_info_repo = DealInfoRepository()
        deal_insights_repo = DealInsightsRepository()
        deal_timeline_repo = DealTimelineRepository()

        # Parse dates if provided
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            # Set to end of day
            end_dt = end_dt.replace(hour=23, minute=59, second=59)

        # Get all deals
        all_deals = deal_info_repo.get_all_deals()

        # Dictionary to store risks by stage
        # Format: {stage: list of risk objects}
        risks_by_stage = defaultdict(list)

        # Process each deal
        for deal in all_deals:
            deal_id = deal.get("deal_id")
            deal_stage = deal.get("stage", "Unknown")

            # Filter by stage if provided
            if stage and deal_stage != stage:
                continue

            # Get insights for this deal
            insights = deal_insights_repo.get_by_deal_id(deal_id)

            if insights:
                # Check for pricing concerns
                concerns_list = insights.get("concerns", [])

                # Handle both list and dict formats
                if isinstance(concerns_list, dict):
                    concerns_list = [concerns_list]

                # Process each concern entry
                for concern in concerns_list:
                    # Pricing concerns
                    pricing = concern.get("pricing_concerns", {})
                    if pricing.get("has_concerns"):
                        risks_by_stage[deal_stage].append({
                            "deal_name": deal_id,
                            "risk_type": "Pricing Concerns",
                            "explanation": pricing.get("explanation", "N/A")
                        })

                    # No decision maker
                    no_dm = concern.get("no_decision_maker", {})
                    if no_dm.get("is_issue"):
                        risks_by_stage[deal_stage].append({
                            "deal_name": deal_id,
                            "risk_type": "No Decision Maker",
                            "explanation": no_dm.get("explanation", "N/A")
                        })

                    # Existing vendor
                    vendor = concern.get("already_has_vendor", {})
                    if vendor.get("has_vendor"):
                        risks_by_stage[deal_stage].append({
                            "deal_name": deal_id,
                            "risk_type": "Existing Vendor",
                            "explanation": vendor.get("explanation", "N/A")
                        })

            # Get timeline for buyer intent risks
            timeline = deal_timeline_repo.get_by_deal_id(deal_id)

            if timeline and "events" in timeline:
                # Count low buyer intent events for this deal
                low_intent_count = 0

                for event in timeline.get("events", []):
                    # Apply date filter if provided
                    if start_dt or end_dt:
                        event_date = event.get("event_date")
                        if isinstance(event_date, str):
                            event_date = datetime.strptime(event_date, "%Y-%m-%dT%H:%M:%S")

                        if start_dt and event_date < start_dt:
                            continue
                        if end_dt and event_date > end_dt:
                            continue

                    # Check for low buyer intent
                    buyer_intent = event.get("buyer_intent", "").lower()

                    # Consider these as negative signals (excluding neutral)
                    negative_intents = [
                        "unlikely to buy",
                        "not likely to buy",
                        "less likely to buy",
                        "low intent",
                        "not interested"
                    ]

                    if any(neg in buyer_intent for neg in negative_intents):
                        low_intent_count += 1

                # Add single entry for this deal if it has low intent events
                if low_intent_count > 0:
                    event_word = "event" if low_intent_count == 1 else "events"
                    risks_by_stage[deal_stage].append({
                        "deal_name": deal_id,
                        "risk_type": "Low Buyer Intent",
                        "explanation": f"{low_intent_count} {event_word} with 'low buyer intent'"
                    })

        # Restructure to group by stage -> risk_type -> list of deals
        result = {}
        for stage_name, risks in risks_by_stage.items():
            # Group risks by risk_type and merge duplicate deal_names
            risks_by_type = defaultdict(lambda: defaultdict(list))
            for risk in risks:
                risk_type = risk["risk_type"]
                deal_name = risk["deal_name"]
                explanation = risk["explanation"]

                # Collect all explanations for the same deal under the same risk type
                risks_by_type[risk_type][deal_name].append(explanation)

            # Convert to final format with merged explanations
            final_risks = {}
            for risk_type, deals_dict in risks_by_type.items():
                deals_list = []
                for deal_name, explanations in deals_dict.items():
                    # Merge explanations with "; " separator
                    merged_explanation = "; ".join(explanations)
                    deals_list.append({
                        "deal_name": deal_name,
                        "explanation": merged_explanation
                    })
                final_risks[risk_type] = deals_list

            # Sort risk types by number of unique deals (descending), then sort deals within each risk type
            sorted_risks = sorted(final_risks.items(), key=lambda x: len(x[1]), reverse=True)
            result[stage_name] = {
                risk_type: sorted(deals, key=lambda x: x["deal_name"])
                for risk_type, deals in sorted_risks
            }

        return {
            "status": "success",
            "data": result,
            "filters": {
                "stage": stage,
                "start_date": start_date,
                "end_date": end_date
            }
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching risks: {str(e)}")


@router.get("/positives")
async def get_positives_by_stage(
    stage: Optional[str] = Query(None, description="Filter by specific stage"),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format")
) -> Dict[str, Any]:
    """
    Get all positive signals associated with deals, aggregated by stage.

    Positives include:
    - Likely to buy signals (from deal_timeline buyer_intent)

    Args:
        stage: Optional filter for a specific stage (e.g., "3. Technical Validation")
        start_date: Optional start date filter for events (YYYY-MM-DD)
        end_date: Optional end date filter for events (YYYY-MM-DD)

    Returns:
        Dictionary with stages as keys and list of positive signal objects as values
    """
    try:
        deal_info_repo = DealInfoRepository()
        deal_timeline_repo = DealTimelineRepository()

        # Parse dates if provided
        start_dt = None
        end_dt = None
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            # Set to end of day
            end_dt = end_dt.replace(hour=23, minute=59, second=59)

        # Get all deals
        all_deals = deal_info_repo.get_all_deals()

        # Dictionary to store positives by stage
        # Format: {stage: list of positive objects}
        positives_by_stage = defaultdict(list)

        # Process each deal
        for deal in all_deals:
            deal_id = deal.get("deal_id")
            deal_stage = deal.get("stage", "Unknown")

            # Filter by stage if provided
            if stage and deal_stage != stage:
                continue

            # Get timeline for buyer intent positives
            timeline = deal_timeline_repo.get_by_deal_id(deal_id)

            if timeline and "events" in timeline:
                # Count positive buyer intent events for this deal
                positive_intent_count = 0

                for event in timeline.get("events", []):
                    # Apply date filter if provided
                    if start_dt or end_dt:
                        event_date = event.get("event_date")
                        if isinstance(event_date, str):
                            event_date = datetime.strptime(event_date, "%Y-%m-%dT%H:%M:%S")

                        if start_dt and event_date < start_dt:
                            continue
                        if end_dt and event_date > end_dt:
                            continue

                    # Check for positive buyer intent
                    buyer_intent = event.get("buyer_intent", "").lower()

                    # Consider these as positive signals
                    positive_intents = [
                        "likely to buy",
                        "more likely to buy",
                        "high intent",
                        "strong intent",
                        "ready to buy",
                        "interested"
                    ]

                    if any(pos in buyer_intent for pos in positive_intents):
                        positive_intent_count += 1

                # Add single entry for this deal if it has positive intent events
                if positive_intent_count > 0:
                    event_word = "event" if positive_intent_count == 1 else "events"
                    positives_by_stage[deal_stage].append({
                        "deal_name": deal_id,
                        "positive_type": "Likely to Buy",
                        "explanation": f"{positive_intent_count} {event_word} with 'likely to buy' intent"
                    })

        # Restructure to group by stage -> positive_type -> list of deals
        result = {}
        for stage_name, positives in positives_by_stage.items():
            # Group positives by positive_type
            positives_by_type = defaultdict(list)
            for positive in positives:
                positives_by_type[positive["positive_type"]].append({
                    "deal_name": positive["deal_name"],
                    "explanation": positive["explanation"]
                })

            # Sort positive types by number of entries (descending), then sort deals within each positive type
            sorted_positives = sorted(positives_by_type.items(), key=lambda x: len(x[1]), reverse=True)
            result[stage_name] = {
                positive_type: sorted(deals, key=lambda x: x["deal_name"])
                for positive_type, deals in sorted_positives
            }

        return {
            "status": "success",
            "data": result,
            "filters": {
                "stage": stage,
                "start_date": start_date,
                "end_date": end_date
            }
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching positives: {str(e)}")
