from langchain_core.tools import tool
from simpleeval import simple_eval


@tool
def calculator(expression: str) -> str:
    """
    Evaluates a mathematical expression and returns the result.
    Use this for any math calculations.
    Example input: '25 * 4 + 10'
    """
    try:
        result = simple_eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_weather(city: str) -> str:
    """
    Returns the current weather for a given city.
    Use this when the user asks about weather.
    Example input: 'London'
    """
    weather_data = {
        "london": "Cloudy, 15°C",
        "new york": "Sunny, 22°C",
        "tokyo": "Rainy, 18°C",
        "paris": "Partly cloudy, 17°C",
    }
    return weather_data.get(city.lower(), f"Weather data not available for {city}")


@tool
def search_knowledge_base(query: str) -> str:
    """
    Searches a knowledge base for information about a topic.
    Use this when the user asks general knowledge questions.
    Example input: 'What is machine learning?'
    """
    knowledge = {
        "machine learning": "Machine learning is a subset of AI where systems learn from data.",
        "langchain": "LangChain is a framework for building LLM-powered applications.",
        "langgraph": "LangGraph is a library for building stateful, multi-actor LLM workflows.",
    }
    for key, value in knowledge.items():
        if key in query.lower():
            return value
    return "No relevant information found in the knowledge base."


tools = [calculator, get_weather, search_knowledge_base]
