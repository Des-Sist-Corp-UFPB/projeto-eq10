import requests

# Cole sua chave real aqui
API_KEY = "SUA CHABE DE API AQUI" 

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
response = requests.get(url)

if response.status_code == 200:
    data = response.json()
    print("✅ Modelos disponíveis para a sua chave:\n")
    for model in data.get('models', []):
        # Filtra apenas os modelos que geram texto
        if 'generateContent' in model.get('supportedGenerationMethods', []):
            nome = model['name'].replace('models/', '')
            print(f" -> {nome}")
else:
    print("❌ Erro ao consultar a API:", response.text)