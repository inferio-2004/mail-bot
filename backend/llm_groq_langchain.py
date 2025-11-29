# backend/llm_groq_langchain.py
"""
LangChain-compatible wrapper for Groq API using OpenAI interface.
Allows you to use LangChain chains, prompts, and tools with Groq.
"""

import os
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

groq_api_key = os.environ.get("GROQ_API_KEY")
if not groq_api_key:
    raise RuntimeError("GROQ_API_KEY not set in environment (set in .env or env vars)")

# Use Groq's OpenAI-compatible endpoint
llm = ChatOpenAI(
    openai_api_key=groq_api_key,
    openai_api_base="https://api.groq.com/openai/v1",
    model="llama-3.1-8b-instant",
    streaming=True,
    temperature=0.7,
    max_tokens=8192,
)

# Example usage:
if __name__ == "__main__":
    from langchain_core.prompts import ChatPromptTemplate
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are a helpful assistant."),
        ("human", "Say hello and list 2 fruits.")
    ])
    chain = prompt | llm
    for chunk in chain.stream({}):
        print(chunk.content, end="")
    print()
