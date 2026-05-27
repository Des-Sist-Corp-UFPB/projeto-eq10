import requests

url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=AIzaSyB18RhBigW10p_qSLhVvkndkyMRwRyKYAI"
headers = {"Content-Type": "application/json"}
data = {
    "contents": [{"parts": [{"text": "Explain how AI works"}]}]
}

response = requests.post(url, headers=headers, json=data)
print("Status:", response.status_code)
print("Response:", response.text)
