import os
import litellm

# Sua chave do OpenRouter
os.environ["OPENROUTER_API_KEY"] = "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"
litellm._turn_on_debug()

print("Testando comunicação direta com o OpenRouter...")
try:
    response = litellm.completion(
        model="openrouter/auto",
        messages=[{"role": "user", "content": "Diga apenas 'Conectado!'"}]
    )
    print("\n✅ SUCESSO!", response.choices[0].message.content)
except Exception as e:
    print("\n❌ ERRO DETALHADO:", str(e))