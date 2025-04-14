from datetime import datetime, timedelta
from typing import List, Tuple
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from app.core.config import settings
from app.services.openai_service import get_embeddings

def month_to_datetime(month_str: str) -> datetime:
    """Convert short month name to datetime object for the first day of the month"""
    month_map = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    month = month_map.get(month_str.lower())
    if not month:
        raise ValueError(f"Invalid month: {month_str}")
    return datetime(datetime.now().year, month, 1)

def get_month_range(start_month: str, end_month: str) -> List[datetime]:
    """Get list of datetime objects for each month in the range"""
    start = month_to_datetime(start_month)
    end = month_to_datetime(end_month)
    
    if start > end:
        raise ValueError("Start month must be before end month")
        
    months = []
    current = start
    while current <= end:
        months.append(current)
        if current.month == 12:
            current = datetime(current.year + 1, 1, 1)
        else:
            current = datetime(current.year, current.month + 1, 1)
    return months

def chunk_transcript(transcript: str, chunk_size: int = settings.CHUNK_SIZE) -> List[str]:
    """Split transcript into chunks of approximately chunk_size words"""
    words = transcript.split()
    chunks = []
    current_chunk = []
    current_size = 0
    
    for word in words:
        current_chunk.append(word)
        current_size += 1
        
        if current_size >= chunk_size:
            chunks.append(' '.join(current_chunk))
            current_chunk = []
            current_size = 0
            
    if current_chunk:
        chunks.append(' '.join(current_chunk))
        
    return chunks

def find_similar_chunks(
    query_embedding: np.ndarray,
    chunk_embeddings: List[np.ndarray],
    chunk_texts: List[str],
    top_k: int = settings.TOP_K_CHUNKS
) -> List[Tuple[str, float]]:
    """Find top_k most similar chunks to the query"""
    similarities = cosine_similarity(
        query_embedding.reshape(1, -1),
        np.array(chunk_embeddings)
    )[0]
    
    # Get indices of top_k most similar chunks
    top_indices = np.argsort(-similarities)[:top_k]
    
    # Return tuples of (chunk_text, similarity_score)
    return [(chunk_texts[i], float(similarities[i])) for i in top_indices] 