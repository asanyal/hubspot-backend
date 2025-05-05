import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from app.services.gong_service import GongService

class TestGongService:
    @pytest.fixture
    def gong_service(self):
        """Create a GongService instance for testing"""
        return GongService()

    @pytest.fixture
    def mock_calls_response(self):
        """Mock response for list_calls"""
        return {
            "calls": [
                {
                    "id": "123",
                    "title": "Call with Pandadoc",
                    "startTime": "2024-04-17T10:00:00Z"
                },
                {
                    "id": "456",
                    "title": "Follow up with Pandadoc",
                    "startTime": "2024-04-17T14:00:00Z"
                }
            ]
        }

    @pytest.fixture
    def mock_transcript_response(self):
        """Mock response for get_call_transcripts"""
        return {
            "callTranscripts": [
                {
                    "transcript": [
                        {
                            "speakerId": "speaker1",
                            "sentences": [
                                {"text": "Hello, this is a test call."},
                                {"text": "We're discussing the product."}
                            ]
                        }
                    ]
                }
            ]
        }

    def test_list_calls(self, gong_service, mock_calls_response):
        """Test list_calls function"""
        with patch('requests.get') as mock_get:
            # Configure mock
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.json.return_value = mock_calls_response
            mock_get.return_value = mock_response

            # Call the function
            result = gong_service.list_calls("2024-04-17")

            # Assertions
            assert len(result) == 2
            assert result[0]["id"] == "123"
            assert result[1]["id"] == "456"
            mock_get.assert_called_once()

    def test_find_call_id_by_title(self, gong_service):
        """Test find_call_id_by_title function"""
        calls = [
            {"id": "123", "title": "Call with Pandadoc"},
            {"id": "456", "title": "Follow up with Pandadoc"}
        ]

        # Test exact match
        assert gong_service.find_call_id_by_title(calls, "Call with Pandadoc") == "123"
        
        # Test case-insensitive match
        assert gong_service.find_call_id_by_title(calls, "pandadoc") == "123"
        
        # Test partial match
        assert gong_service.find_call_id_by_title(calls, "Follow up") == "456"
        
        # Test no match
        assert gong_service.find_call_id_by_title(calls, "Nonexistent") is None

    def test_get_call_transcripts(self, gong_service, mock_transcript_response):
        """Test get_call_transcripts function"""
        with patch('requests.post') as mock_post:
            # Configure mock
            mock_response = MagicMock()
            mock_response.ok = True
            mock_response.json.return_value = mock_transcript_response
            mock_post.return_value = mock_response

            # Call the function
            result = gong_service.get_call_transcripts(
                ["123"],
                "2024-04-17T00:00:00Z",
                "2024-04-17T23:59:59Z"
            )

            # Assertions
            assert result == mock_transcript_response
            assert "callTranscripts" in result
            mock_post.assert_called_once()

    @patch('app.services.gong_service.ask_anthropic')
    def test_get_buyer_intent_for_call(self, mock_ask_anthropic, gong_service):
        """Test get_buyer_intent_for_call function"""
        # Mock the LLM response
        mock_ask_anthropic.return_value = '{"intent": "likely to buy", "explanation": "Customer showed strong interest"}'

        # Mock list_calls and get_call_transcripts
        with patch.object(gong_service, 'list_calls') as mock_list_calls, \
             patch.object(gong_service, 'get_call_transcripts') as mock_get_transcripts:
            
            # Configure mocks
            mock_list_calls.return_value = [{"id": "123", "title": "Call with Pandadoc"}]
            mock_get_transcripts.return_value = {
                "callTranscripts": [{
                    "transcript": [{
                        "sentences": [{"text": "We're very interested in your product"}]
                    }]
                }]
            }

            # Call the function
            result = gong_service.get_buyer_intent_for_call(
                "Pandadoc",
                "2024-04-17",
                "Test Seller"
            )

            # Assertions
            assert result["intent"] == "likely to buy"
            assert "explanation" in result
            mock_ask_anthropic.assert_called_once()

    @patch('app.services.gong_service.ask_anthropic')
    def test_get_champion_results(self, mock_ask_anthropic, gong_service):
        """Test get_champion_results function"""
        # Mock the LLM responses
        mock_ask_anthropic.side_effect = [
            '{"champion": true, "explanation": "Strong advocate", "business_pain": "Need better solution"}',
            '{"pain": 8, "authority": 7, "preference": 9, "role": 8, "parr_explanation": "Good fit"}'
        ]

        # Mock populate_speaker_data
        with patch.object(gong_service, 'populate_speaker_data') as mock_populate_speakers:
            # Configure mock
            mock_populate_speakers.return_value = {
                "speaker1": MagicMock(
                    speaker_id="speaker1",
                    speaker_name="John Doe",
                    email="john@example.com",
                    affiliation="External",
                    full_transcript="We need a better solution"
                )
            }

            # Call the function
            result = gong_service.get_champion_results(
                "Pandadoc",
                datetime(2024, 4, 17)
            )

            # Assertions
            assert len(result) > 0
            assert result[0]["champion"] is True
            assert "explanation" in result[0]
            assert "parr_analysis" in result[0]
            assert result[0]["email"] == "john@example.com"
            assert result[0]["speakerName"] == "John Doe"

    def test_error_handling(self, gong_service):
        """Test error handling in various functions"""
        with patch('requests.get') as mock_get:
            # Configure mock to simulate API error
            mock_response = MagicMock()
            mock_response.ok = False
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_get.return_value = mock_response

            # Test list_calls error handling
            result = gong_service.list_calls("2024-04-17")
            assert result == []

        with patch('requests.post') as mock_post:
            # Configure mock to simulate API error
            mock_response = MagicMock()
            mock_response.ok = False
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_post.return_value = mock_response

            # Test get_call_transcripts error handling
            result = gong_service.get_call_transcripts(
                ["123"],
                "2024-04-17T00:00:00Z",
                "2024-04-17T23:59:59Z"
            )
            assert result is None 