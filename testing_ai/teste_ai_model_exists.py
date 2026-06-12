import requests

#API_KEY = "SUA API KEY AQUI0"
MODEL = "gemini-2.5-flash"

#url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"

payload = {
    "contents": [{"parts": [{"text": "Responda apenas a palavra: Funciona!"}]}]
}

print("Enviando requisição direta para o Google...")
#response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})

#Lembre-se de substituir a URL e a chave de API acima pelos valores corretos para testar a resposta do modelo. O código abaixo é um exemplo de como processar a resposta, mas está comentado para evitar erros caso a requisição não seja feita.
"""if response.status_code == 200:
    print("\n✅ SUCESSO ABSOLUTO! A IA respondeu:")
    print(response.json()['candidates'][0]['content']['parts'][0]['text'])
else:
    print(f"\n❌ ERRO {response.status_code}:")
    print(response.text)"""