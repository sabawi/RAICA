import pytest
import requests
import logging

# Configure logging for pytest output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:5000"

@pytest.fixture(scope="session")
def api_base_url():
    """Fixture to provide the base URL, can be overridden via env var if needed."""
    return BASE_URL

@pytest.mark.integration
@pytest.mark.timeout(65) # Ensure test fails if it hangs longer than expected
def test_financial_news_streaming(api_base_url):
    """
    Test Case: Financial News Streaming Endpoint
    Feature: Verify the /llama3_1b/stream endpoint returns a valid stream 
             with financial context when prompted.
    
    Scenario:
    1. Send a POST request with a financial news prompt.
    2. Verify the response status is 200 OK.
    3. Read the first 5 chunks of the stream.
    4. Verify that the chunks contain data.
    5. Verify that the chunks contain financial-related keywords (feature validation).
    """
    
    prompt = "look up the latest financial news as of today then summarize it"
    payload = {
        "prompt": prompt,
        "toolsInUse": True
    }
    
    logger.info(f"🧪 Starting Financial News Test against {api_base_url}")

    try:
        # Using 'with' ensures the connection is closed properly
        with requests.post(
            f"{api_base_url}/llama3_1b/stream", 
            json=payload, 
            stream=True, 
            timeout=60
        ) as response:
            
            # 1. Status Code Check
            assert response.status_code == 200, \
                f"Endpoint returned status code {response.status_code}"
            
            logger.info(f"✅ Status Code: {response.status_code}")

            # 2. Stream Processing
            chunk_count = 0
            full_text_accumulated = ""
            financial_keywords = ['financial', 'news', 'market', 'stock', 'economy', 'business']
            keywords_found = set()

            # Read first 5 chunks to verify streaming behavior without long waits
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    chunk_count += 1
                    chunk_text = chunk.decode('utf-8', errors='ignore')
                    full_text_accumulated += chunk_text.lower()
                    
                    logger.debug(f"Chunk {chunk_count}: {len(chunk_text)} bytes")
                    
                    # Check for specific keywords in this chunk
                    for word in financial_keywords:
                        if word in chunk_text.lower():
                            keywords_found.add(word)
                    
                    if chunk_count >= 5:
                        logger.info(f"🛑 Stopping stream read after {chunk_count} chunks (Quick Test)")
                        break

            # 3. Data Integrity Checks
            assert chunk_count > 0, "No chunks were received from the stream (Stream might be empty)"
            
            # 4. Content Validation (Feature Specific)
            # We expect at least one financial keyword to appear in the response stream
            # to ensure the 'financial news' feature logic is triggered.
            # Note: We use a soft check here because the first chunk might be "Thinking..."
            # However, across 5 chunks, we should see some context.
            if not keywords_found:
                # We log a warning but might not fail hard if we just want to test connectivity,
                # BUT for a feature test, we should assert.
                # Given the "Quick" nature, we assert we found something.
                pytest.fail(
                    f"Financial content validation failed. "
                    f"Expected keywords like {financial_keywords} in stream. "
                    f"Accumulated text preview: {full_text_accumulated[:200]}"
                )
            
            logger.info(f"✅ Financial keywords detected: {keywords_found}")
            logger.info("✅ Test Passed: Financial news functionality appears active.")

    except requests.exceptions.Timeout:
        pytest.fail("Request timed out (60s). The financial news tool might be processing too slowly.")
    except requests.exceptions.ConnectionError:
        pytest.skip(f"Connection refused: Server not running at {api_base_url}")