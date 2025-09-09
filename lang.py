import pandas as pd
from langchain_ollama import OllamaLLM

# Load Excel
df = pd.read_excel("sfa_dp.xlsx")

# Normalize headers and matching column
df.columns = df.columns.str.strip()
df['Code Fonction'] = df['Code Fonction'].astype(str).str.lower().str.strip()

# Start LLaMA 3
llm = OllamaLLM(model='llama3')

# Custom column renaming for display
display_names = {
    'Code Fonction': 'sfa code',
    'wording System in ENG': 'system'
}

while True:
    user_input = input("\nYou: ").lower().strip()

    if user_input in ['exit', 'quit']:
        print("Goodbye!")
        break

    # Match user input to Code Fonction
    matched_rows = df[df['Code Fonction'] == user_input]

    if not matched_rows.empty:
        row = matched_rows.iloc[0]
        print("\n📄 Matched Row:\n")
        for col in df.columns:
            label = display_names.get(col, col)
            print(f"{label}: {row[col]}")
    else:
        print("\n🤖 No match found in 'Code Fonction'. Sending to LLaMA...")
       # response = llm.invoke(user_input)
       # print(f"\n🤖 LLaMA 3: {response}")
