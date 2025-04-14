import numpy as np
from typing import List
from openai import OpenAI
from app.core.config import settings

client = OpenAI(api_key=settings.OPENAI_API_KEY)
EMBEDDING_MODEL = "text-embedding-ada-002"

def get_embeddings(texts: List[str], model: str = EMBEDDING_MODEL) -> List[np.ndarray]:
    """Generates embeddings for a list of texts using OpenAI.
    Args:
        texts (List[str]): A list of text strings to embed.
        model (str): The embedding model to use.
    Returns:
        List[np.ndarray]: A list of embeddings as numpy arrays.
    """
    try:
        # Replace newlines for better embedding performance
        texts = [text.replace("\n", " ") for text in texts]
        data = client.embeddings.create(input=texts, model=model).data
        return [np.array(embedding.embedding) for embedding in data]
    except Exception as e:
        print(f"Error calling OpenAI Embedding API: {e}")
        # Return empty list or handle error as appropriate
        return [] 