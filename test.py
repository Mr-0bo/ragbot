import requests
API_KEY = "AQ.Ab8RN6KbNXPRO6smUEjZGyZbhaLG37WrhFp8-HxY97LArAcfuA"

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"

r= requests.get(url)

print(r.status_code)
print(r.text)
print(API_KEY)
print(len(API_KEY))