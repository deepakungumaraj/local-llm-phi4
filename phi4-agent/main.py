from langchain_core.messages import HumanMessage
from agent import build_agent


def main():
    agent = build_agent()
    print("Phi-4 Local Agent -- type 'quit' to exit\n")
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye!")
            break

        result = agent.invoke({
            "messages": [HumanMessage(content=user_input)]
        })
        response = result["messages"][-1].content
        print(f"\nPhi-4: {response}\n")


if __name__ == "__main__":
    main()
