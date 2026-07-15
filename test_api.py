import httpx
import asyncio
import random
import string

async def test():
    async with httpx.AsyncClient() as client:
        # 1. Get Domains
        resp = await client.get("https://api.mail.tm/domains")
        print("Get Domains Status:", resp.status_code)
        if resp.status_code != 200:
            print("Failed to get domains:", resp.text)
            return
            
        domains = resp.json().get("hydra:member", [])
        if not domains:
            print("No domains returned.")
            return
        
        domain = domains[0]["domain"]
        print("Selected Domain:", domain)
        
        # 2. Generate Random Email
        username = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"{username}@{domain}"
        password = "SecurePassword123!"
        print(f"Attempting to register: {email} with password: {password}")
        
        # 3. Create Account
        resp = await client.post("https://api.mail.tm/accounts", json={
            "address": email,
            "password": password
        })
        print("Register Account Status:", resp.status_code)
        if resp.status_code not in (200, 201):
            print("Failed to register account:", resp.text)
            return
            
        account_data = resp.json()
        print("Account Registered:", account_data["address"])
        
        # 4. Get Token
        resp = await client.post("https://api.mail.tm/token", json={
            "address": email,
            "password": password
        })
        print("Get Token Status:", resp.status_code)
        if resp.status_code != 200:
            print("Failed to get token:", resp.text)
            return
            
        token_data = resp.json()
        token = token_data["token"]
        print("Token retrieved successfully!")
        
        # 5. Fetch Messages
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get("https://api.mail.tm/messages", headers=headers)
        print("Get Messages Status:", resp.status_code)
        if resp.status_code == 200:
            print("Messages List:", resp.json())
        else:
            print("Failed to get messages:", resp.text)

if __name__ == "__main__":
    asyncio.run(test())
